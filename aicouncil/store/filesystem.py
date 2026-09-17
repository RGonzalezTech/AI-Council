"""
Filesystem session store — human-readable layout.

    <sessions_dir>/<idea_id>/
    ├── state.json                  # Full CouncilState (authoritative checkpoint)
    ├── idea.txt                    # Premise, for grepping
    ├── council.json                # Council roster
    ├── proposal.md                 # Current proposal
    ├── proposals/
    │   ├── draft_v1.md             # First compiled draft
    │   └── round_<n>.md            # Proposal at the end of each round
    ├── perspectives/<slug>.json
    ├── objections/<id>.json
    ├── council.log                 # Debug log (written by logging, not this module)
    ├── final_report.md             # Written by the report renderer
    └── debate_log.md

`state.json` is the only file `load()` needs; everything else is a
convenience projection for humans and tooling. Writes are atomic.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from ..models import CouncilState
from .base import SessionNotFound, SessionSummary, _resolve_prefix

logger = logging.getLogger("aicouncil")


def _slug(text: str) -> str:
    return re.sub(r"[^\w]+", "_", text).strip("_").lower() or "unnamed"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class FileSessionStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ── Paths ────────────────────────────────────────────────

    def session_dir(self, idea_id: str, create: bool = True) -> Path:
        d = self.root / idea_id
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d

    # ── SessionStore ─────────────────────────────────────────

    def save(self, state: CouncilState) -> None:
        state.updated_at = datetime.now()
        d = self.session_dir(state.idea_id)

        _atomic_write(d / "state.json", state.model_dump_json(indent=2))
        _atomic_write(d / "idea.txt", state.original_premise)
        _atomic_write(
            d / "council.json",
            json.dumps({"council": [m.model_dump() for m in state.council]}, indent=2),
        )

        if state.context_summary:
            _atomic_write(d / "context_summary.md", state.context_summary)

        if state.initial_perspectives:
            pdir = d / "perspectives"
            pdir.mkdir(exist_ok=True)
            for p in state.initial_perspectives:
                _atomic_write(pdir / f"{_slug(p.expert_role)}.json", p.model_dump_json(indent=2))

        if state.current_proposal:
            _atomic_write(d / "proposal.md", state.current_proposal)
            hist = d / "proposals"
            hist.mkdir(exist_ok=True)
            if state.turn_count == 0:
                _atomic_write(hist / "draft_v1.md", state.current_proposal)
            else:
                _atomic_write(hist / f"round_{state.turn_count}.md", state.current_proposal)

        objections = [*state.objection_queue, *state.resolved_objections]
        if objections:
            odir = d / "objections"
            odir.mkdir(exist_ok=True)
            seen: set[str] = set()
            for o in objections:
                if o.id in seen:
                    continue
                seen.add(o.id)
                _atomic_write(odir / f"{o.id}.json", o.model_dump_json(indent=2))

        logger.debug("Checkpoint → %s", d)

    def load(self, idea_id: str) -> CouncilState:
        f = self.root / idea_id / "state.json"
        if not f.exists():
            raise SessionNotFound(idea_id)
        return CouncilState.model_validate_json(f.read_text(encoding="utf-8"))

    def list(self) -> list[SessionSummary]:
        if not self.root.exists():
            return []
        rows: list[SessionSummary] = []
        for d in self.root.iterdir():
            f = d / "state.json"
            if not d.is_dir() or not f.exists():
                continue
            try:
                s = CouncilState.model_validate_json(f.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 — corrupt sessions must not kill listing
                logger.warning("Skipping unreadable session %s: %s", d.name, exc)
                continue
            rows.append(
                SessionSummary(
                    idea_id=s.idea_id,
                    premise=s.original_premise,
                    status=s.global_status,
                    turn_count=s.turn_count,
                    max_turns=s.max_turns,
                    council_size=len(s.council),
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                )
            )
        rows.sort(key=lambda r: r.updated_at, reverse=True)
        return rows

    def resolve_id(self, prefix: str) -> str:
        if (self.root / prefix / "state.json").exists():
            return prefix
        if not self.root.exists():
            raise SessionNotFound(prefix)
        return _resolve_prefix(prefix, (d.name for d in self.root.iterdir() if d.is_dir()))
