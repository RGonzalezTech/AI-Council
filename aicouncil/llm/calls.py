"""
Typed LLM operations.

`CouncilLLM` turns domain objects into prompts, sends them through an
`LLMGateway`, and returns validated schema instances. It knows nothing about
the console or the filesystem.
"""

from __future__ import annotations

from ..models import CouncilState, ExpertMember, FileReference, Objection
from ..schemas import (
    ContextSummaryResponse,
    EvaluationResponse,
    ExpertSuggestion,
    ExpertVerdict,
    FirstDraftResponse,
    IntakeResponse,
    PerspectiveResponse,
    ProposalSummaryResponse,
    ResolutionJudgment,
    SolutionResponse,
    TriageResponse,
    VoteResponse,
)
from .gateway import LLMGateway
from .prompts import PromptLibrary


def _context_block(summary: str) -> str:
    return f"\n\nReference Context:\n{summary}" if summary else ""


def _decision_log_block(log: list[str], header: str) -> str:
    if not log:
        return ""
    return f"\n\n{header}\n" + "\n".join(f"  • {d}" for d in log)


class CouncilLLM:
    def __init__(self, gateway: LLMGateway, prompts: PromptLibrary | None = None) -> None:
        self._gw = gateway
        self._prompts = prompts or PromptLibrary()

    def _call(self, name: str, model: str, response_model, **fields):
        system, user = self._prompts.render(name, **fields)
        return self._gw.complete(
            model=model, response_model=response_model, system=system, user=user
        )

    # ── Intake ────────────────────────────────────────────────

    def summarize_files(self, files: list[FileReference], *, model: str) -> ContextSummaryResponse:
        file_block = "".join(f"\n--- {f.alias or f.path} ---\n{f.content}\n" for f in files)
        return self._call("summarize_files", model, ContextSummaryResponse, file_block=file_block)

    def generate_council(
        self, premise: str, context_summary: str, *, council_size: int, model: str
    ) -> IntakeResponse:
        return self._call(
            "generate_council",
            model,
            IntakeResponse,
            premise=premise,
            context_block=_context_block(context_summary),
            council_size=council_size,
        )

    def generate_member(
        self, intent: str, premise: str, current: list[ExpertMember], *, model: str
    ) -> ExpertSuggestion:
        council_block = ""
        if current:
            council_block = "\n\nCurrent Council Members:\n" + "\n".join(
                f"- {m.role}" for m in current
            )
        return self._call(
            "generate_member",
            model,
            ExpertSuggestion,
            intent=intent,
            premise=premise,
            council_block=council_block,
        )

    # ── Drafting ──────────────────────────────────────────────

    def expert_perspective(
        self, expert: ExpertMember, premise: str, context_summary: str, *, model: str
    ) -> PerspectiveResponse:
        return self._call(
            "expert_perspective",
            model,
            PerspectiveResponse,
            role=expert.role,
            system_prompt=expert.system_prompt,
            premise=premise,
            context_block=_context_block(context_summary),
        )

    def compile_first_draft(self, state: CouncilState, *, model: str) -> FirstDraftResponse:
        perspectives_block = "".join(
            f"\n--- {p.expert_role} ---\n"
            f"Perspective: {p.perspective}\n"
            f"Key Concerns: {', '.join(p.key_concerns)}\n"
            f"Suggested Approach: {p.suggested_approach}\n"
            for p in state.initial_perspectives
        )
        return self._call(
            "compile_first_draft",
            model,
            FirstDraftResponse,
            premise=state.original_premise,
            context_block=_context_block(state.context_summary),
            perspectives_block=perspectives_block,
        )

    # ── Review ────────────────────────────────────────────────

    def expert_review(
        self, expert: ExpertMember, state: CouncilState, *, model: str
    ) -> ExpertVerdict:
        return self._call(
            "expert_review",
            model,
            ExpertVerdict,
            role=expert.role,
            system_prompt=expert.system_prompt,
            proposal=state.current_proposal,
            decision_log_block=_decision_log_block(
                state.decision_log,
                "DECISION LOG (previous agreements — DO NOT contradict these):",
            ),
        )

    def expert_vote(
        self, expert: ExpertMember, objections: list[Objection], state: CouncilState, *, model: str
    ) -> VoteResponse:
        objections_block = "\n\n".join(
            f"ID: {o.id}\nRaised by: {o.raised_by}\nObjection: {o.current_concern}"
            for o in objections
        )
        return self._call(
            "expert_vote",
            model,
            VoteResponse,
            role=expert.role,
            system_prompt=expert.system_prompt,
            proposal=state.current_proposal,
            objections_block=objections_block,
        )

    # ── Resolution ────────────────────────────────────────────

    def moderator_triage(
        self, objection: Objection, state: CouncilState, *, model: str
    ) -> TriageResponse:
        council_block = "\n".join(
            f"  • {m.role}: {m.system_prompt[:100]}..."
            for m in state.council
            if m.role != objection.raised_by
        )
        return self._call(
            "moderator_triage",
            model,
            TriageResponse,
            objector=objection.raised_by,
            objection=objection.current_concern,
            council_block=council_block,
        )

    def expert_solution(
        self, expert: ExpertMember, objection: Objection, state: CouncilState, *, model: str
    ) -> SolutionResponse:
        return self._call(
            "expert_solution",
            model,
            SolutionResponse,
            role=expert.role,
            system_prompt=expert.system_prompt,
            objector=objection.raised_by,
            objection=objection.current_concern,
            proposal=state.current_proposal,
        )

    def expert_evaluate(
        self, expert: ExpertMember, objection: Objection, solutions_block: str, *, model: str
    ) -> EvaluationResponse:
        return self._call(
            "expert_evaluate",
            model,
            EvaluationResponse,
            role=expert.role,
            system_prompt=expert.system_prompt,
            objection=objection.current_concern,
            solutions_block=solutions_block,
        )

    def moderator_judge(
        self, objection: Objection, solution: str, state: CouncilState, *, model: str
    ) -> ResolutionJudgment:
        return self._call(
            "moderator_judge",
            model,
            ResolutionJudgment,
            objector=objection.raised_by,
            objection=objection.current_concern,
            solution=solution,
            proposal=state.current_proposal,
            decision_log_block=_decision_log_block(
                state.decision_log, "EXISTING DECISION LOG (preserve these):"
            ),
        )

    # ── Report ────────────────────────────────────────────────

    def summarize_proposal(self, proposal: str, premise: str, *, model: str) -> str:
        result = self._call(
            "summarize_proposal",
            model,
            ProposalSummaryResponse,
            premise=premise,
            proposal=proposal,
        )
        return result.executive_summary
