"""
LLM integration layer — LiteLLM + Instructor.

Provides typed, structured LLM calls for every phase of the council debate.
All calls return validated Pydantic models guaranteed by Instructor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import instructor
import litellm
from litellm import completion

from .llm_schemas import (
    ContextSummaryResponse,
    EvaluationResponse,
    ExpertVerdict,
    FirstDraftResponse,
    IntakeResponse,
    ExpertSuggestion,
    PerspectiveResponse,
    ResolutionJudgment,
    SolutionResponse,
    SynthesisResponse,
    TriageResponse,
)

if TYPE_CHECKING:
    from .models import CouncilState, ExpertMember, FileReference, Objection

logger = logging.getLogger("council")

# Suppress verbose litellm logging
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

MAX_RETRIES = 3


def _client() -> instructor.Instructor:
    """Create an Instructor-patched LiteLLM client."""
    return instructor.from_litellm(completion)


# ─── Helper ──────────────────────────────────────────────────


def _call(
    model: str,
    response_model: type,
    system: str,
    user: str,
):
    """
    Generic structured LLM call.

    Uses Instructor to guarantee the response conforms to response_model.
    """
    client = _client()
    logger.debug("LLM call → model=%s, schema=%s", model, response_model.__name__)
    result = client.chat.completions.create(
        model=model,
        response_model=response_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_retries=MAX_RETRIES,
    )
    logger.debug("LLM response ← %s", response_model.__name__)
    return result


# ─── Intake Phase ────────────────────────────────────────────


def summarize_files(
    files: list[FileReference],
    model: str,
) -> ContextSummaryResponse:
    """Condense raw file contents into a context summary to save tokens."""
    file_block = ""
    for f in files:
        label = f.alias or f.path
        file_block += f"\n--- {label} ---\n{f.content}\n"

    return _call(
        model=model,
        response_model=ContextSummaryResponse,
        system=(
            "You are a technical analyst. Read the provided reference materials "
            "and produce a comprehensive but concise summary. Extract all "
            "critical details — architecture decisions, constraints, APIs, "
            "data models, dependencies — that would be needed to evaluate or "
            "build upon this project. Discard boilerplate and focus on substance."
        ),
        user=f"Reference Materials:\n{file_block}",
    )


def generate_council(
    premise: str,
    context_summary: str,
    model: str,
) -> IntakeResponse:
    """Generate council composition from the idea and context."""
    context_block = ""
    if context_summary:
        context_block = f"\n\nReference Context:\n{context_summary}"

    return _call(
        model=model,
        response_model=IntakeResponse,
        system=(
            "You are an expert organizational strategist tasked with assembling "
            "the ideal council of domain experts to rigorously evaluate and "
            "stress-test an idea.\n\n"
            "Your goal is to select experts who will:\n"
            "1. Cover ALL critical dimensions of the idea (technical, business, "
            "legal, operational, etc.)\n"
            "2. Represent DISTINCT perspectives with minimal overlap\n"
            "3. Be adversarial and thorough — they should be hard to impress\n"
            "4. Create productive tension that leads to a stronger final proposal\n\n"
            "IMPORTANT: Choose roles that are SPECIFIC to this idea, not generic. "
            "For example, if the idea involves healthcare, include a 'Healthcare "
            "Compliance Specialist' not just a 'Legal Expert'.\n\n"
            "Recommend exactly 5 council members."
        ),
        user=f"Idea: {premise}{context_block}",
    )


def generate_vibe_member(
    intent: str,
    premise: str,
    current_council: list[ExpertMember],
    model: str,
) -> ExpertSuggestion:
    """Generate a single council member based on a user's intent."""
    council_block = ""
    if current_council:
        council_block = "\n\nCurrent Council Members:\n" + "\n".join(
            f"- {m.role}" for m in current_council
        )

    return _call(
        model=model,
        response_model=ExpertSuggestion,
        system=(
            "You are an expert organizational strategist. The user is assembling "
            "a council of domain experts to evaluate an idea. They want to add "
            "a new member to the council based on a specific intent.\n\n"
            "Your goal is to interpret the user's intent and generate a single, "
            "highly specific council member that fulfills that intent. "
            "Ensure the new role does not heavily overlap with existing members. "
            "The system prompt should detail their personality, expertise, and priorities."
        ),
        user=f"Idea: {premise}{council_block}\n\nUser Intent for new member: {intent}",
    )


# ─── Draft Phase ─────────────────────────────────────────────


def expert_perspective(
    expert: ExpertMember,
    premise: str,
    context_summary: str,
    model: str,
) -> PerspectiveResponse:
    """Get an expert's initial, isolated perspective on the raw idea."""
    context_block = ""
    if context_summary:
        context_block = f"\n\nReference Context:\n{context_summary}"

    return _call(
        model=model,
        response_model=PerspectiveResponse,
        system=(
            f"You are {expert.role}.\n\n{expert.system_prompt}\n\n"
            "You are being presented with an idea for the first time. "
            "Provide your initial, unfiltered perspective:\n"
            "1. What are the key considerations from your domain?\n"
            "2. What approach would you recommend?\n"
            "3. What are the biggest risks or concerns you see?\n"
            "4. What are the non-negotiable requirements from your perspective?\n\n"
            "Be thorough and specific. This is your chance to shape the initial "
            "direction before group debate begins."
        ),
        user=f"Idea: {premise}{context_block}",
    )


def compile_first_draft(
    state: CouncilState,
    model: str,
) -> FirstDraftResponse:
    """Have the Moderator synthesize all expert perspectives into Draft v1."""
    perspectives_block = ""
    for p in state.initial_perspectives:
        perspectives_block += (
            f"\n--- {p.expert_role} ---\n"
            f"Perspective: {p.perspective}\n"
            f"Key Concerns: {', '.join(p.key_concerns)}\n"
            f"Suggested Approach: {p.suggested_approach}\n"
        )

    context_block = ""
    if state.context_summary:
        context_block = f"\n\nReference Context:\n{state.context_summary}"

    return _call(
        model=model,
        response_model=FirstDraftResponse,
        system=(
            "You are the Moderator of an AI Council. You have collected initial "
            "perspectives from all domain experts on the user's idea.\n\n"
            "Your job is to synthesize these into a comprehensive FIRST DRAFT "
            "proposal that:\n"
            "1. Addresses the core idea with a clear, actionable plan\n"
            "2. Incorporates key insights from ALL expert perspectives\n"
            "3. Resolves any obvious contradictions between expert opinions\n"
            "4. Identifies decisions that were made during synthesis\n\n"
            "Write the proposal as a detailed, well-structured document with "
            "clear sections and headers. This will be the document the council "
            "debates, so make it thorough and specific enough to critique.\n\n"
            "For each decision you make while synthesizing (e.g., choosing one "
            "approach over another), add a concise entry to key_decisions."
        ),
        user=(
            f"Original Idea: {state.original_premise}"
            f"{context_block}\n\n"
            f"Expert Perspectives:\n{perspectives_block}"
        ),
    )


# ─── Debate Phase: Expert Review ─────────────────────────────


def expert_review(
    expert: ExpertMember,
    state: CouncilState,
    model: str,
) -> ExpertVerdict:
    """Have an expert review the current proposal and APPROVE or OBJECT."""
    decision_log_block = ""
    if state.decision_log:
        decision_log_block = (
            "\n\nDECISION LOG (previous agreements — DO NOT contradict these):\n"
            + "\n".join(f"  • {d}" for d in state.decision_log)
        )

    return _call(
        model=model,
        response_model=ExpertVerdict,
        system=(
            f"You are {expert.role}.\n\n{expert.system_prompt}\n\n"
            "You are reviewing a proposal. Evaluate it STRICTLY from your "
            "domain of expertise.\n\n"
            "Rules:\n"
            "- If the proposal is acceptable from YOUR domain's perspective, "
            "APPROVE it.\n"
            "- If you have a SERIOUS, SPECIFIC concern within your expertise, "
            "OBJECT with a clear description of the problem.\n"
            "- Do NOT object to things outside your domain.\n"
            "- Do NOT re-raise issues that appear in the Decision Log as "
            "already resolved.\n"
            "- Be specific: explain exactly what's wrong and why it matters."
        ),
        user=(
            f"CURRENT PROPOSAL:\n{state.current_proposal}"
            f"{decision_log_block}"
        ),
    )


# ─── Objection Resolution: Triage ───────────────────────────


def moderator_triage(
    objection: Objection,
    state: CouncilState,
    model: str,
) -> TriageResponse:
    """Have the Moderator decide which experts to consult for an objection."""
    council_block = "\n".join(
        f"  • {m.role}: {m.system_prompt[:100]}..."
        for m in state.council
        if m.role != objection.raised_by
    )

    return _call(
        model=model,
        response_model=TriageResponse,
        system=(
            "You are the Moderator of an AI Council. An expert has raised an "
            "objection during the council review. Your job is to decide which "
            "OTHER council members (1-3) have the domain expertise to propose "
            "solutions to this specific objection.\n\n"
            "Select only the most relevant experts. Do NOT include the objector."
        ),
        user=(
            f"OBJECTION from {objection.raised_by}: \"{objection.objection_text}\"\n\n"
            f"COUNCIL MEMBERS (excluding objector):\n{council_block}"
        ),
    )


# ─── Objection Resolution: Expert Solution ──────────────────


def expert_solution(
    expert: ExpertMember,
    objection: Objection,
    state: CouncilState,
    model: str,
) -> SolutionResponse:
    """Have an expert propose a solution to an objection."""
    return _call(
        model=model,
        response_model=SolutionResponse,
        system=(
            f"You are {expert.role}.\n\n{expert.system_prompt}\n\n"
            "A fellow council member has raised an objection to the current "
            "proposal. From your domain expertise, propose a specific, "
            "actionable solution that addresses this objection while "
            "maintaining the integrity of the overall proposal.\n\n"
            "Be concrete: suggest exact changes, not vague principles."
        ),
        user=(
            f"OBJECTION from {objection.raised_by}: "
            f"\"{objection.objection_text}\"\n\n"
            f"CURRENT PROPOSAL:\n{state.current_proposal}"
        ),
    )


# ─── Objection Resolution: Synthesis ────────────────────────


def moderator_synthesize(
    objection: Objection,
    state: CouncilState,
    model: str,
) -> SynthesisResponse:
    """Have the Moderator compile expert solutions into a unified brief."""
    solutions_block = ""
    for ps in objection.proposed_solutions:
        solutions_block += f"\n  • {ps.expert_role}: {ps.solution}\n"

    return _call(
        model=model,
        response_model=SynthesisResponse,
        system=(
            "You are the Moderator. You've collected proposed solutions from "
            "domain experts to address an objection.\n\n"
            "Compile these into a clear, unified recommendation. If solutions "
            "conflict, choose the most robust approach and explain why. "
            "Present this as a concise brief for the objecting expert to review."
        ),
        user=(
            f"ORIGINAL OBJECTION from {objection.raised_by}: "
            f"\"{objection.objection_text}\"\n\n"
            f"PROPOSED SOLUTIONS:\n{solutions_block}\n\n"
            f"CURRENT PROPOSAL:\n{state.current_proposal}"
        ),
    )


# ─── Objection Resolution: Evaluation ───────────────────────


def expert_evaluate(
    expert: ExpertMember,
    objection: Objection,
    synthesis: SynthesisResponse,
    model: str,
) -> EvaluationResponse:
    """Have the objecting expert evaluate the compiled solution."""
    return _call(
        model=model,
        response_model=EvaluationResponse,
        system=(
            f"You are {expert.role}.\n\n{expert.system_prompt}\n\n"
            "You raised an objection to the proposal. The council has worked "
            "on a solution. Evaluate it honestly:\n"
            "- Does it adequately address your concern?\n"
            "- Are there remaining issues from YOUR domain perspective?\n"
            "- Be fair but rigorous. Don't nitpick, but don't accept "
            "half-measures either."
        ),
        user=(
            f"YOUR ORIGINAL OBJECTION: \"{objection.objection_text}\"\n\n"
            f"PROPOSED SOLUTION:\n{synthesis.compiled_solution}\n\n"
            f"CHANGES SUMMARY: {synthesis.changes_summary}"
        ),
    )


# ─── Objection Resolution: Judgment ─────────────────────────


def moderator_judge(
    objection: Objection,
    synthesis: SynthesisResponse,
    state: CouncilState,
    model: str,
) -> ResolutionJudgment:
    """
    Have the Moderator finalize the resolution.

    The Moderator rewrites the proposal to incorporate the agreed solution
    and adds a decision log entry to prevent future regressions.
    """
    decision_log_block = ""
    if state.decision_log:
        decision_log_block = (
            "\n\nEXISTING DECISION LOG (preserve these):\n"
            + "\n".join(f"  • {d}" for d in state.decision_log)
        )

    return _call(
        model=model,
        response_model=ResolutionJudgment,
        system=(
            "You are the Moderator. An objection has been resolved through "
            "council discussion. Your tasks:\n\n"
            "1. REWRITE the full proposal to incorporate the agreed solution. "
            "Preserve all existing content and only modify/add what's needed "
            "to address the objection.\n"
            "2. Write a concise decision_log_entry summarizing the rule "
            "established (e.g., 'Auth: Must use mTLS, not plaintext "
            "(per Security Expert)').\n\n"
            "The updated_proposal must be the COMPLETE proposal text, not "
            "just the changed sections."
        ),
        user=(
            f"OBJECTION from {objection.raised_by}: "
            f"\"{objection.objection_text}\"\n\n"
            f"AGREED SOLUTION:\n{synthesis.compiled_solution}\n\n"
            f"CURRENT PROPOSAL:\n{state.current_proposal}"
            f"{decision_log_block}"
        ),
    )
