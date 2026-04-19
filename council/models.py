"""
Pydantic v2 models for the AI Council state machine.

These models define the "Living Document" — the strictly-typed state object
that is the single source of truth throughout the entire debate lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ─── Council Members ────────────────────────────────────────


class ExpertMember(BaseModel):
    """A single expert on the council."""

    role: str = Field(description="Concise title, e.g. 'Security Architect'")
    system_prompt: str = Field(description="Personality, expertise, and priorities")


# ─── Domain State ────────────────────────────────────────────


class DomainState(BaseModel):
    """Tracks an individual expert's current review status."""

    status: Literal[
        "review_pending",
        "reviewing",
        "approved",
        "objecting",
    ] = "review_pending"


# ─── Perspectives (Draft Phase) ─────────────────────────────


class InitialPerspective(BaseModel):
    """An expert's first-impression take on the raw idea."""

    expert_role: str
    perspective: str = Field(description="Domain-specific analysis and recommendations")
    key_concerns: list[str] = Field(
        default_factory=list,
        description="Top concerns from this expert's perspective",
    )
    suggested_approach: str = Field(
        default="",
        description="High-level approach recommendation",
    )


# ─── Objections & Resolution ────────────────────────────────


class ProposedSolution(BaseModel):
    """A solution offered by an expert during objection resolution."""

    expert_role: str
    solution: str


class Objection(BaseModel):
    """
    A first-class entity representing a single objection raised during debate.
    Has its own lifecycle: pending → in_resolution → resolved/deadlocked/overruled.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raised_by: str
    objection_text: str
    status: Literal[
        "pending",
        "in_resolution",
        "resolved",
        "overruled",
        "deadlocked",
    ] = "pending"
    consulted_experts: list[str] = Field(default_factory=list)
    proposed_solutions: list[ProposedSolution] = Field(default_factory=list)
    resolution_turns: int = 0
    resolution_summary: str | None = None
    turn_raised: int = 0
    turn_resolved: int | None = None


# ─── File References ─────────────────────────────────────────


SUPPORTED_EXTENSIONS: set[str] = {
    ".md", ".txt", ".rst",
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".csv",
    ".html", ".css", ".scss",
    ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
    ".sh", ".bash", ".sql", ".xml",
    ".env", ".cfg", ".ini", ".conf",
    ".rb", ".php", ".swift", ".kt",
    ".gdscript", ".gd",
}

MAX_FILE_SIZE: int = 250 * 1024       # 250 KB per file
MAX_TOTAL_SIZE: int = 1000 * 1024     # 1 MB total


class FileReference(BaseModel):
    """A user-provided file included as context for the council."""

    path: str
    alias: str | None = None
    content: str = ""
    size_bytes: int = 0


# ─── Root State Object ───────────────────────────────────────


class CouncilState(BaseModel):
    """
    The Living Document — single source of truth for the entire session.

    Checkpointed to disk after every meaningful state change so that
    a crashed session can be resumed from the last checkpoint.
    """

    # Identity
    idea_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Input
    original_premise: str = ""
    file_references: list[FileReference] = Field(default_factory=list)
    context_summary: str = ""

    # Council
    council: list[ExpertMember] = Field(default_factory=list)
    domain_states: dict[str, DomainState] = Field(default_factory=dict)

    # Draft phase
    initial_perspectives: list[InitialPerspective] = Field(default_factory=list)

    # Proposal (mutated throughout the debate)
    current_proposal: str = ""

    # Objection tracking
    objection_queue: list[Objection] = Field(default_factory=list)
    resolved_objections: list[Objection] = Field(default_factory=list)
    decision_log: list[str] = Field(default_factory=list)

    # Control
    global_status: Literal[
        "intake",
        "drafting",
        "debating",
        "approved",
        "rejected",
        "stalemate",
    ] = "intake"
    turn_count: int = 0
    max_turns: int = 15
    max_resolution_turns: int = 5

    # LLM config
    model: str = "gemini/gemini-2.5-pro"
