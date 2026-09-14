"""
Domain models for the council state machine.

`CouncilState` is the single source of truth for a session. It is a pure
data object: no I/O, no LLM, no rendering. Everything else operates on it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

GlobalStatus = Literal["intake", "drafting", "debating", "approved", "rejected", "stalemate"]
ReviewStatus = Literal["review_pending", "reviewing", "approved", "objecting"]
ObjectionStatus = Literal["pending", "in_resolution", "resolved", "overruled", "deadlocked"]

TERMINAL_STATUSES: frozenset[str] = frozenset({"approved", "rejected"})


# ─── Council Members ────────────────────────────────────────


class ExpertMember(BaseModel):
    """A single expert on the council."""

    role: str = Field(description="Concise title, e.g. 'Security Architect'")
    system_prompt: str = Field(description="Personality, expertise, and priorities")
    model: str | None = Field(
        default=None,
        description="Optional per-expert model override. None → session default.",
    )


# ─── Domain State ────────────────────────────────────────────


class DomainState(BaseModel):
    """Tracks an individual expert's current review status."""

    status: ReviewStatus = "review_pending"


# ─── Perspectives (Draft Phase) ─────────────────────────────


class InitialPerspective(BaseModel):
    """An expert's first-impression take on the raw idea."""

    expert_role: str
    perspective: str
    key_concerns: list[str] = Field(default_factory=list)
    suggested_approach: str = ""


# ─── Objections & Resolution ────────────────────────────────


class ProposedSolution(BaseModel):
    """A solution offered by an expert during objection resolution."""

    expert_role: str
    solution: str
    attempt: int = Field(default=1, description="Which resolution attempt produced this.")


class Objection(BaseModel):
    """
    A first-class record of a single objection raised during debate.

    Lifecycle: pending → in_resolution → resolved | deadlocked | overruled.

    `objection_text` is immutable once raised. If the objector remains
    unsatisfied after a resolution attempt, their narrowed concern is appended
    to `revisions`; `current_concern` always yields the latest wording.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raised_by: str
    objection_text: str
    revisions: list[str] = Field(
        default_factory=list,
        description="Narrowed concerns after each unsatisfied resolution attempt.",
    )
    status: ObjectionStatus = "pending"
    consulted_experts: list[str] = Field(default_factory=list)
    proposed_solutions: list[ProposedSolution] = Field(default_factory=list)
    resolution_turns: int = 0
    resolution_summary: str | None = None
    proposal_diff: str | None = None
    turn_raised: int = 0
    turn_resolved: int | None = None

    @property
    def current_concern(self) -> str:
        return self.revisions[-1] if self.revisions else self.objection_text

    @property
    def is_closed(self) -> bool:
        return self.status in ("resolved", "deadlocked", "overruled")


# ─── Root State Object ───────────────────────────────────────


class CouncilState(BaseModel):
    """
    The living document — single source of truth for the entire session.

    Persisted after every meaningful mutation so a crashed session can be
    resumed from the last checkpoint.
    """

    # Identity
    idea_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Input
    original_premise: str = ""
    context_summary: str = ""

    # Council
    council: list[ExpertMember] = Field(default_factory=list)
    domain_states: dict[str, DomainState] = Field(default_factory=dict)

    # Draft phase
    initial_perspectives: list[InitialPerspective] = Field(default_factory=list)

    # Proposal (mutated throughout the debate)
    current_proposal: str = ""
    proposal_executive_summary: str = ""

    # Objection tracking
    objection_queue: list[Objection] = Field(default_factory=list)
    resolved_objections: list[Objection] = Field(default_factory=list)
    decision_log: list[str] = Field(default_factory=list)

    # Control
    global_status: GlobalStatus = "intake"
    turn_count: int = 0
    max_turns: int = 15
    max_resolution_turns: int = 5

    # LLM config — LiteLLM model strings.
    model: str = ""
    moderator_model: str = ""

    # ── Helpers ──────────────────────────────────────────────

    def expert(self, role: str) -> ExpertMember:
        for member in self.council:
            if member.role == role:
                return member
        raise KeyError(f"No council member with role {role!r}")

    def model_for(self, expert: ExpertMember | str) -> str:
        """Model string for an expert, falling back to the session default."""
        member = self.expert(expert) if isinstance(expert, str) else expert
        return member.model or self.model

    @property
    def is_terminal(self) -> bool:
        return self.global_status in TERMINAL_STATUSES

    def stats(self) -> dict[str, int]:
        closed = self.resolved_objections
        return {
            "rounds": self.turn_count,
            "objections": len(closed),
            "resolved": sum(1 for o in closed if o.status == "resolved"),
            "deadlocked": sum(1 for o in closed if o.status == "deadlocked"),
            "overruled": sum(1 for o in closed if o.status == "overruled"),
        }
