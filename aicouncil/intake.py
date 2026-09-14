"""
Intake service — everything that happens before the debate engine runs.

Builds a `CouncilState` from a premise and settings; generates or extends the
council roster. No UI here: the CLI's interactive editing loop calls these
methods between prompts.
"""

from __future__ import annotations

import logging

from .llm import CouncilLLM
from .models import CouncilState, ExpertMember
from .settings import Settings

logger = logging.getLogger("aicouncil")


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
    ) -> CouncilState:
        s = self._settings
        expert_model = model or s.model
        return CouncilState(
            original_premise=premise,
            model=expert_model,
            moderator_model=moderator_model or s.moderator_model or expert_model,
            max_turns=max_turns or s.max_turns,
            max_resolution_turns=s.max_resolution_turns,
        )

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
