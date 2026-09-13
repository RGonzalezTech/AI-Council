"""
Composition root and public façade.

`Council` wires the default implementations together. Library users who
want a different store, sink, gateway, or prompt set construct the pieces
themselves and pass them in — nothing here is required.

    from aicouncil import Council
    council = Council()
    state = council.new_session("Should we build X?")
    state.council = council.intake.generate_council(state)
    state = council.run(state)
    council.write_reports(state)
"""

from __future__ import annotations

import logging
from pathlib import Path

from .engine import DebateEngine
from .events import EventSink, NullSink
from .intake import IntakeService, load_reference_files
from .llm import CouncilLLM, InstructorGateway, LLMGateway, PromptLibrary
from .models import CouncilState
from .reports import MarkdownRenderer, ReportRenderer
from .settings import Settings
from .store import FileSessionStore, SessionStore

logger = logging.getLogger("aicouncil")


class Council:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        gateway: LLMGateway | None = None,
        prompts: PromptLibrary | None = None,
        store: SessionStore | None = None,
        sink: EventSink | None = None,
        renderer: ReportRenderer | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.store: SessionStore = store or FileSessionStore(self.settings.sessions_dir)
        self.sink: EventSink = sink or NullSink()
        self.llm = CouncilLLM(gateway or InstructorGateway(self.settings), prompts)
        self.intake = IntakeService(self.llm, self.settings)
        self.engine = DebateEngine(self.llm, self.store, self.sink, self.settings)
        self.renderer: ReportRenderer = renderer or MarkdownRenderer()

    # ── Sessions ─────────────────────────────────────────────

    def new_session(
        self,
        premise: str,
        *,
        model: str | None = None,
        moderator_model: str | None = None,
        max_turns: int | None = None,
        files: list[Path] | None = None,
    ) -> CouncilState:
        loaded = load_reference_files(files or [], self.settings)
        for path, reason in loaded.skipped:
            logger.warning("Skipped %s: %s", path, reason)
        state = self.intake.new_state(
            premise,
            model=model,
            moderator_model=moderator_model,
            max_turns=max_turns,
            files=loaded.accepted,
        )
        self.store.save(state)
        return state

    def load(self, idea_id: str) -> CouncilState:
        return self.store.load(self.store.resolve_id(idea_id))

    def run(self, state: CouncilState) -> CouncilState:
        return self.engine.run(state)

    # ── Stalemate decisions ──────────────────────────────────

    def extend(self, state: CouncilState, extra_turns: int = 10) -> CouncilState:
        state.max_turns += extra_turns
        state.global_status = "debating"
        self.store.save(state)
        return state

    def accept(self, state: CouncilState) -> CouncilState:
        state.global_status = "approved"
        self.store.save(state)
        return self.engine.summarize(state)

    def reject(self, state: CouncilState) -> CouncilState:
        state.global_status = "rejected"
        self.store.save(state)
        return state

    # ── Reports ──────────────────────────────────────────────

    def write_reports(self, state: CouncilState) -> list[Path]:
        """Render reports into the session directory (file store only)."""
        if not isinstance(self.store, FileSessionStore):
            raise TypeError("write_reports requires a FileSessionStore; use render_reports instead")
        out: list[Path] = []
        d = self.store.session_dir(state.idea_id)
        for doc in self.renderer.render(state):
            p = d / doc.filename
            p.write_text(doc.content, encoding="utf-8")
            out.append(p)
        return out

    def render_reports(self, state: CouncilState):
        return self.renderer.render(state)
