"""
Session persistence protocol.

`SessionStore` is what the engine and CLI depend on. `FileSessionStore` is
the default; an in-memory store exists for tests. Swapping in a database
means implementing three methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..models import CouncilState


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """Lightweight listing row — cheap to produce, no full state load."""

    idea_id: str
    premise: str
    status: str
    turn_count: int
    max_turns: int
    council_size: int
    created_at: datetime
    updated_at: datetime


class SessionNotFound(LookupError):
    pass


@runtime_checkable
class SessionStore(Protocol):
    def save(self, state: CouncilState) -> None: ...

    def load(self, idea_id: str) -> CouncilState: ...

    def list(self) -> list[SessionSummary]: ...

    def resolve_id(self, prefix: str) -> str:
        """Expand a unique id prefix to a full id. Raise SessionNotFound otherwise."""
        ...


class MemorySessionStore:
    """Dict-backed store for tests and embedding."""

    def __init__(self) -> None:
        self._states: dict[str, CouncilState] = {}

    def save(self, state: CouncilState) -> None:
        state.updated_at = datetime.now()
        self._states[state.idea_id] = state.model_copy(deep=True)

    def load(self, idea_id: str) -> CouncilState:
        try:
            return self._states[idea_id].model_copy(deep=True)
        except KeyError:
            raise SessionNotFound(idea_id) from None

    def list(self) -> list[SessionSummary]:
        return [
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
            for s in sorted(self._states.values(), key=lambda s: s.updated_at, reverse=True)
        ]

    def resolve_id(self, prefix: str) -> str:
        return _resolve_prefix(prefix, self._states.keys())


def _resolve_prefix(prefix: str, ids) -> str:
    matches = [i for i in ids if i.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SessionNotFound(prefix)
    raise SessionNotFound(f"Ambiguous id prefix {prefix!r} matches {len(matches)} sessions")
