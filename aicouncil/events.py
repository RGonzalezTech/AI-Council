"""
Typed events emitted by the debate engine.

The engine never renders anything. It emits these events to an `EventSink`;
front-ends (Rich CLI, logs, web sockets, tests) subscribe and decide what to
show. Adding a new front-end means implementing `EventSink` — the engine does
not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .models import CouncilState, Objection


@dataclass(frozen=True, slots=True)
class Event:
    """Base class for all engine events."""


# ─── Lifecycle ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PhaseStarted(Event):
    phase: str  # "drafting" | "debating"
    state: CouncilState


@dataclass(frozen=True, slots=True)
class Message(Event):
    """Free-form status line from a named actor (Moderator / expert / System)."""

    actor: str
    text: str
    level: str = "info"  # info | success | warning | error | dim


# ─── Parallel work ──────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ParallelStarted(Event):
    """A batch of concurrent LLM calls is about to begin."""

    title: str
    labels: tuple[str, ...]
    batch_id: str


@dataclass(frozen=True, slots=True)
class ParallelItemDone(Event):
    batch_id: str
    label: str


@dataclass(frozen=True, slots=True)
class ParallelFinished(Event):
    batch_id: str


# ─── Drafting ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DraftReady(Event):
    state: CouncilState
    points_of_debate: tuple[str, ...] = field(default_factory=tuple)


# ─── Debate ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ReviewRoundStarted(Event):
    state: CouncilState


@dataclass(frozen=True, slots=True)
class ReviewRoundFinished(Event):
    """All verdicts collected; `state.domain_states` reflects them."""

    state: CouncilState


@dataclass(frozen=True, slots=True)
class VoteCompleted(Event):
    objections: tuple[Objection, ...]
    tallies: dict[str, int]
    winner: Objection


@dataclass(frozen=True, slots=True)
class ObjectionSelected(Event):
    objection: Objection


@dataclass(frozen=True, slots=True)
class ObjectionResolved(Event):
    objection: Objection
    decision: str
    diff: str


@dataclass(frozen=True, slots=True)
class ObjectionDeadlocked(Event):
    objection: Objection


@dataclass(frozen=True, slots=True)
class DebateFinished(Event):
    """Terminal or stalemate status reached."""

    state: CouncilState


# ─── Sink protocol ──────────────────────────────────────────


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


class NullSink:
    """Discards every event. Useful for headless runs and tests."""

    def emit(self, event: Event) -> None:
        return None


class RecordingSink:
    """Keeps every event in memory. Useful for tests and post-hoc inspection."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def of_type(self, kind: type[Event]) -> list[Event]:
        return [e for e in self.events if isinstance(e, kind)]


class MultiSink:
    """Fan one event stream out to several sinks."""

    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = sinks

    def emit(self, event: Event) -> None:
        for sink in self._sinks:
            sink.emit(event)
