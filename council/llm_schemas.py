"""
Pydantic response schemas enforced on LLM outputs via Instructor.

Each schema corresponds to a specific LLM call type and guarantees
that the model returns structured, validated data.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ─── Intake Phase ────────────────────────────────────────────


class ExpertSuggestion(BaseModel):
    """A single council member recommendation from the Intake Router."""

    role: str = Field(description="Concise role title, e.g. 'Security Architect'")
    system_prompt: str = Field(
        description="Detailed personality, expertise, priorities, and focus areas"
    )
    rationale: str = Field(description="Why this role is essential for this idea")


class IntakeResponse(BaseModel):
    """The full council recommendation from the Intake Router."""

    council: list[ExpertSuggestion] = Field(
        description="Exactly 5 recommended council members"
    )


class ContextSummaryResponse(BaseModel):
    """Condensed summary of user-provided file references."""

    summary: str = Field(
        description="Comprehensive summary of the reference materials"
    )
    key_details: list[str] = Field(
        description="Critical details extracted from the files"
    )


# ─── Draft Phase (Perspectives) ─────────────────────────────


class PerspectiveResponse(BaseModel):
    """An expert's initial, isolated perspective on the raw idea."""

    perspective: str = Field(
        description="Detailed domain-specific analysis and recommendations"
    )
    key_concerns: list[str] = Field(
        description="Top 3-5 concerns from this expert's domain"
    )
    suggested_approach: str = Field(
        description="High-level recommended approach for implementation"
    )


class FirstDraftResponse(BaseModel):
    """The Moderator's compiled first draft from all perspectives."""

    proposal: str = Field(
        description="Comprehensive, well-structured first draft proposal"
    )
    key_decisions: list[str] = Field(
        description="Decisions made while synthesizing (for the decision log)"
    )
    points_of_debate: list[str] = Field(
        default_factory=list,
        description=(
            "Unresolved contradictions or conflicts between expert perspectives "
            "that should be surfaced for the council to debate, not decided by the Moderator"
        ),
    )


# ─── Debate Phase (Review) ──────────────────────────────────


class ExpertVerdict(BaseModel):
    """An expert's review of the current proposal."""

    approved: bool = Field(description="True if the proposal is acceptable")
    objection: str | None = Field(
        default=None,
        description="If not approved, a clear and specific objection",
    )
    reasoning: str = Field(description="Brief explanation of the decision")


# ─── Objection Resolution ───────────────────────────────────


class TriageResponse(BaseModel):
    """The Moderator's decision on which experts to consult for an objection."""

    relevant_experts: list[str] = Field(
        description="1-3 expert roles best suited to address this objection"
    )
    reasoning: str = Field(description="Why these experts were selected")


class SolutionResponse(BaseModel):
    """An expert's proposed solution to an objection."""

    solution: str = Field(
        description="Specific, actionable solution from this expert's domain"
    )
    trade_offs: str = Field(
        default="",
        description="Any trade-offs or caveats with this solution",
    )


class EvaluationResponse(BaseModel):
    """The objecting expert's evaluation of the concatenated proposed solutions."""

    satisfied: bool = Field(
        description="True if at least one proposed solution adequately addresses the objection"
    )
    reasoning: str = Field(description="Why they are or aren't satisfied")
    accepted_solution: str | None = Field(
        default=None,
        description=(
            "If satisfied, the specific solution text to incorporate — either verbatim from "
            "one of the proposals or a brief synthesis of the best elements across them. "
            "Required when satisfied=True."
        ),
    )
    remaining_concerns: str | None = Field(
        default=None,
        description="If not satisfied, what specifically is still wrong",
    )


class ResolutionJudgment(BaseModel):
    """The Moderator's final judgment after an objection is resolved."""

    updated_proposal: str = Field(
        description="The full proposal rewritten to incorporate the agreed solution"
    )
    decision_log_entry: str = Field(
        description="Concise rule established, e.g. 'Auth: Must use mTLS (per Security)'"
    )
    reasoning: str = Field(description="Why this resolution was adopted")


# ─── Debate Phase (Voting) ───────────────────────────────────


class ObjectionVote(BaseModel):
    """A single point allocation in an expert's vote."""

    objection_id: str = Field(description="ID of the objection receiving these points")
    points: int = Field(description="Points allocated to this objection (must be positive)")


class VoteResponse(BaseModel):
    """An expert's 100-point allocation vote across raised objections."""

    votes: list[ObjectionVote] = Field(
        description="Point allocations across objections. Must be positive integers summing to 100."
    )
    reasoning: str = Field(description="Why these objections were prioritized this way")


# ─── Report Phase ────────────────────────────────────────────


class ProposalSummaryResponse(BaseModel):
    """A concise executive summary of the final council proposal."""

    executive_summary: str = Field(
        description=(
            "A 3-5 sentence executive summary of the final proposal. "
            "Should answer: what was decided, why, and what the key trade-offs or approach are. "
            "Written for a reader who has not seen the full proposal. Plain prose, no bullet points."
        )
    )

