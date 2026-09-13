"""
Prompt templates.

Every prompt the council sends is defined here as a named `Prompt` with
`system` and `user` templates using `str.format` fields. A `PromptLibrary`
maps names to prompts; callers may pass a customised library to override
any prompt without touching engine code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Prompt:
    system: str
    user: str

    def render(self, **kwargs: object) -> tuple[str, str]:
        return self.system.format(**kwargs), self.user.format(**kwargs)


EXPERT_HEADER = "You are {role}.\n\n{system_prompt}\n\n"

DEFAULT_PROMPTS: dict[str, Prompt] = {
    # ── Intake ────────────────────────────────────────────────
    "generate_council": Prompt(
        system=(
            "You are an expert organizational strategist tasked with assembling the ideal "
            "council of domain experts to rigorously evaluate and stress-test an idea.\n\n"
            "Your goal is to select experts who will:\n"
            "1. Cover ALL critical dimensions of the idea (technical, business, legal, "
            "operational, etc.)\n"
            "2. Represent DISTINCT perspectives with minimal overlap\n"
            "3. Be adversarial and thorough — they should be hard to impress\n"
            "4. Create productive tension that leads to a stronger final proposal\n\n"
            "IMPORTANT: Choose roles that are SPECIFIC to this idea, not generic. For "
            "example, if the idea involves healthcare, include a 'Healthcare Compliance "
            "Specialist' not just a 'Legal Expert'.\n\n"
            "Recommend exactly {council_size} council members."
        ),
        user="Idea: {premise}{context_block}",
    ),
    "generate_member": Prompt(
        system=(
            "You are an expert organizational strategist. The user is assembling a council "
            "of domain experts to evaluate an idea and wants to add a new member based on a "
            "specific intent.\n\n"
            "Interpret the intent and generate a single, highly specific council member. "
            "Ensure the new role does not heavily overlap with existing members. The system "
            "prompt should detail their personality, expertise, and priorities."
        ),
        user="Idea: {premise}{council_block}\n\nUser intent for new member: {intent}",
    ),
    # ── Drafting ──────────────────────────────────────────────
    "expert_perspective": Prompt(
        system=EXPERT_HEADER
        + (
            "You are being presented with an idea for the first time. Provide your "
            "initial, unfiltered perspective:\n"
            "1. What are the key considerations from your domain?\n"
            "2. What approach would you recommend?\n"
            "3. What are the biggest risks or concerns you see?\n"
            "4. What are the non-negotiable requirements from your perspective?\n\n"
            "Be thorough and specific. This is your chance to shape the initial direction "
            "before group debate begins."
        ),
        user="Idea: {premise}{context_block}",
    ),
    "compile_first_draft": Prompt(
        system=(
            "You are the Moderator of an AI Council. You have collected initial perspectives "
            "from all domain experts on the user's idea.\n\n"
            "Synthesize these into a comprehensive FIRST DRAFT proposal that:\n"
            "1. Addresses the core idea with a clear, actionable plan\n"
            "2. Incorporates key insights from ALL expert perspectives\n"
            "3. Resolves any MINOR, non-controversial contradictions between experts\n"
            "4. Identifies decisions that were made during synthesis\n\n"
            "CRITICAL: For any SIGNIFICANT disagreement between experts — especially where "
            "they recommend fundamentally different approaches — do NOT resolve it yourself. "
            "Surface it as a point_of_debate and annotate the relevant section with "
            "[OPEN DEBATE] so reviewers focus there.\n\n"
            "Write the proposal as a detailed, well-structured document with clear sections "
            "and headers. For each synthesis decision add a concise entry to key_decisions; "
            "for each unresolved conflict add a concise description to points_of_debate."
        ),
        user=(
            "Original Idea: {premise}{context_block}\n\nExpert Perspectives:\n{perspectives_block}"
        ),
    ),
    # ── Review ────────────────────────────────────────────────
    "expert_review": Prompt(
        system=EXPERT_HEADER
        + (
            "You are reviewing a proposal. Evaluate it STRICTLY from your domain of "
            "expertise.\n\n"
            "Rules:\n"
            "- If the proposal is acceptable from YOUR domain's perspective, APPROVE it.\n"
            "- If you have a SERIOUS, SPECIFIC concern within your expertise, OBJECT with a "
            "clear description of the problem.\n"
            "- Do NOT object to things outside your domain.\n"
            "- Do NOT re-raise issues that appear in the Decision Log as already resolved.\n"
            "- Be specific: explain exactly what's wrong and why it matters."
        ),
        user="CURRENT PROPOSAL:\n{proposal}{decision_log_block}",
    ),
    "expert_vote": Prompt(
        system=EXPERT_HEADER
        + (
            "Multiple objections have been raised against the current proposal. The council "
            "will resolve one objection this round, so you must vote on which should be "
            "discussed first.\n\n"
            "You have 100 points to allocate across the listed objections. Concentrate "
            "points on objections you consider most urgent or impactful from your domain's "
            "perspective. All allocations must be positive integers summing to 100."
        ),
        user="CURRENT PROPOSAL:\n{proposal}\n\nOBJECTIONS (vote on these):\n{objections_block}",
    ),
    # ── Resolution ────────────────────────────────────────────
    "moderator_triage": Prompt(
        system=(
            "You are the Moderator of an AI Council. An expert has raised an objection. "
            "Decide which OTHER council members (1-3) have the domain expertise to propose "
            "solutions to this specific objection.\n\n"
            "Select only the most relevant experts. Do NOT include the objector."
        ),
        user=(
            'OBJECTION from {objector}: "{objection}"\n\n'
            "COUNCIL MEMBERS (excluding objector):\n{council_block}"
        ),
    ),
    "expert_solution": Prompt(
        system=EXPERT_HEADER
        + (
            "A fellow council member has raised an objection to the current proposal. From "
            "your domain expertise, propose a specific, actionable solution that addresses "
            "this objection while maintaining the integrity of the overall proposal.\n\n"
            "Be concrete: suggest exact changes, not vague principles."
        ),
        user='OBJECTION from {objector}: "{objection}"\n\nCURRENT PROPOSAL:\n{proposal}',
    ),
    "expert_evaluate": Prompt(
        system=EXPERT_HEADER
        + (
            "You raised an objection to the proposal. The council has responded with one or "
            "more proposed solutions.\n\n"
            "Review ALL proposals from your domain perspective:\n"
            "- If ANY proposal (or combination of elements across proposals) adequately "
            "addresses your concern, set satisfied=True and provide accepted_solution with "
            "the specific text you endorse — verbatim or a concise synthesis.\n"
            "- If NONE adequately address your concern, set satisfied=False and clearly "
            "articulate remaining_concerns so the council can make another attempt.\n"
            "Be fair but rigorous. Don't nitpick, but don't accept half-measures either."
        ),
        user='YOUR OBJECTION: "{objection}"\n\nPROPOSED SOLUTIONS:\n{solutions_block}',
    ),
    "moderator_judge": Prompt(
        system=(
            "You are the Moderator. An objection has been resolved through council "
            "discussion. Your tasks:\n\n"
            "1. REWRITE the full proposal to incorporate the agreed solution. Preserve all "
            "existing content and only modify/add what's needed to address the objection.\n"
            "2. Write a concise decision_log_entry summarizing the rule established (e.g. "
            "'Auth: Must use mTLS, not plaintext (per Security Expert)').\n\n"
            "The updated_proposal must be the COMPLETE proposal text, not just the changed "
            "sections."
        ),
        user=(
            'OBJECTION from {objector}: "{objection}"\n\n'
            "AGREED SOLUTION:\n{solution}\n\n"
            "CURRENT PROPOSAL:\n{proposal}{decision_log_block}"
        ),
    ),
    # ── Report ────────────────────────────────────────────────
    "summarize_proposal": Prompt(
        system=(
            "You are a senior analyst writing the executive summary of a council report. "
            "Summarize the final proposal in 3-5 sentences of plain prose. Answer: what was "
            "decided, what approach was chosen, and what the key trade-offs are. No bullet "
            "points. Write for a reader who has not seen the full proposal. Lead with the "
            "conclusion."
        ),
        user="Original Question: {premise}\n\nFinal Proposal:\n{proposal}",
    ),
}


@dataclass
class PromptLibrary:
    """Named prompt lookup with optional overrides layered over the defaults."""

    overrides: dict[str, Prompt] = field(default_factory=dict)

    def get(self, name: str) -> Prompt:
        if name in self.overrides:
            return self.overrides[name]
        try:
            return DEFAULT_PROMPTS[name]
        except KeyError:
            raise KeyError(f"Unknown prompt {name!r}") from None

    def render(self, name: str, **kwargs: object) -> tuple[str, str]:
        return self.get(name).render(**kwargs)
