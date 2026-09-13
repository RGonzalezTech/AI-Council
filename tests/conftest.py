"""Shared fixtures: a fake gateway with sensible default responders."""

from __future__ import annotations

import pytest

from aicouncil import (
    CouncilLLM,
    CouncilState,
    DebateEngine,
    ExpertMember,
    FakeGateway,
    MemorySessionStore,
    RecordingSink,
    Settings,
)
from aicouncil.schemas import (
    EvaluationResponse,
    ExpertVerdict,
    FirstDraftResponse,
    PerspectiveResponse,
    ProposalSummaryResponse,
    ResolutionJudgment,
    SolutionResponse,
    TriageResponse,
)

ROLES = ["Security Architect", "Database Architect", "Product Manager"]


@pytest.fixture
def settings() -> Settings:
    return Settings(model="test/model", max_workers=2, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def council_state() -> CouncilState:
    return CouncilState(
        original_premise="Build a thing",
        model="test/model",
        moderator_model="test/moderator",
        max_turns=5,
        max_resolution_turns=2,
        council=[ExpertMember(role=r, system_prompt=f"You are the {r}.") for r in ROLES],
    )


@pytest.fixture
def gateway() -> FakeGateway:
    """A gateway where everyone approves everything."""
    gw = FakeGateway()
    gw.on(
        PerspectiveResponse,
        PerspectiveResponse(perspective="p", key_concerns=["c1"], suggested_approach="a"),
    )
    gw.on(
        FirstDraftResponse,
        FirstDraftResponse(proposal="# Draft v1\n\nline one\n", key_decisions=["D0"]),
    )
    gw.on(ExpertVerdict, ExpertVerdict(approved=True, reasoning="fine"))
    gw.on(TriageResponse, TriageResponse(relevant_experts=[ROLES[1]], reasoning="r"))
    gw.on(SolutionResponse, SolutionResponse(solution="do X"))
    gw.on(
        EvaluationResponse,
        EvaluationResponse(satisfied=True, reasoning="ok", accepted_solution="do X"),
    )
    gw.on(
        ResolutionJudgment,
        ResolutionJudgment(
            updated_proposal="# Draft v1\n\nline one\nline two (X)\n",
            decision_log_entry="Do X",
            reasoning="r",
        ),
    )
    gw.on(ProposalSummaryResponse, ProposalSummaryResponse(executive_summary="Summary."))
    return gw


@pytest.fixture
def store() -> MemorySessionStore:
    return MemorySessionStore()


@pytest.fixture
def sink() -> RecordingSink:
    return RecordingSink()


@pytest.fixture
def engine(gateway, store, sink, settings) -> DebateEngine:
    return DebateEngine(CouncilLLM(gateway), store, sink, settings)