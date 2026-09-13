"""
Intake service — everything that happens before the debate engine runs.

Builds a `CouncilState` from a premise, optional reference files, and
settings; generates or extends the council roster. No UI here: the CLI's
interactive editing loop calls these methods between prompts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .llm import CouncilLLM
from .models import SUPPORTED_EXTENSIONS, CouncilState, ExpertMember, FileReference
from .settings import Settings

logger = logging.getLogger("aicouncil")


@dataclass
class FileLoadResult:
    accepted: list[FileReference] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)  # (path, reason)


def load_reference_files(paths: list[Path], settings: Settings) -> FileLoadResult:
    """Read reference files, enforcing type and size limits. Never raises for a bad file."""
    result = FileLoadResult()
    total = 0
    for path in paths:
        if not path.exists():
            result.skipped.append((path, "not found"))
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            result.skipped.append((path, f"unsupported type {path.suffix!r}"))
            continue
        size = path.stat().st_size
        if size > settings.max_file_size:
            result.skipped.append((path, f"{size // 1024}KB exceeds per-file limit"))
            continue
        if total + size > settings.max_total_file_size:
            result.skipped.append((path, "cumulative size limit reached"))
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            result.skipped.append((path, "not UTF-8"))
            continue
        result.accepted.append(
            FileReference(path=str(path), alias=path.name, content=content, size_bytes=size)
        )
        total += size
    return result


class IntakeService:
    def __init__(self, llm: CouncilLLM, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    def new_state(
        self,
        premise: str,
        *,
        model: str | None = None,
        moderator_model: str | None = None,
        max_turns: int | None = None,
        files: list[FileReference] | None = None,
    ) -> CouncilState:
        s = self._settings
        expert_model = model or s.model
        state = CouncilState(
            original_premise=premise,
            model=expert_model,
            moderator_model=moderator_model or s.moderator_model or expert_model,
            max_turns=max_turns or s.max_turns,
            max_resolution_turns=s.max_resolution_turns,
            file_references=files or [],
        )
        if state.file_references:
            summary = self._llm.summarize_files(state.file_references, model=state.moderator_model)
            state.context_summary = summary.summary
        return state

    def generate_council(self, state: CouncilState, size: int | None = None) -> list[ExpertMember]:
        intake = self._llm.generate_council(
            state.original_premise,
            state.context_summary,
            council_size=size or self._settings.council_size,
            model=state.moderator_model,
        )
        return [ExpertMember(role=s.role, system_prompt=s.system_prompt) for s in intake.council]

    def generate_member(self, state: CouncilState, intent: str) -> ExpertMember:
        suggestion = self._llm.generate_member(
            intent, state.original_premise, state.council, model=state.moderator_model
        )
        return ExpertMember(role=suggestion.role, system_prompt=suggestion.system_prompt)
