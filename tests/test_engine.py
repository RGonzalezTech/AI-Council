from __future__ import annotations

from aicouncil import events
from aicouncil.models import DomainState
from aicouncil.schemas import EvaluationResponse, ExpertVerdict, ObjectionVote, VoteResponse

from .conftest import ROLES


def test_consensus_on_first_round(engine, council_state, store, sink):
    state = engine.run(council_state)

    assert state.global_status == "approved"
    assert state.turn_count == 1
    assert state.current_proposal.startswith("# Draft v1")
    assert state.decision_log == ["D0"]
    assert state.proposal_executive_summary == "Summary."
    assert {p.expert_role for p in state.initial_perspectives} == set(ROLES)
    assert all(ds.status == "approved" for ds in state.domain_states.values())

    # persisted
    assert store.load(state.idea_id).global_status == "approved"
    # events
    assert [e.phase for e in sink.of_type(events.PhaseStarted)] == ["drafting", "debating"]
    assert len(sink.of_type(events.DraftReady)) == 1
    assert len(sink.of_type(events.DebateFinished)) == 1


def test_single_objection_is_resolved(engine, gateway, council_state):
    calls = {"n": 0}

    def verdict(model, system, user):
        # Security objects once (first round only), everyone else approves.
        if "Security Architect" in system and calls["n"] == 0:
            calls["n"] += 1
            return ExpertVerdict(approved=False, objection="No TLS", reasoning="bad")
        return ExpertVerdict(approved=True, reasoning="ok")

    gateway.on(ExpertVerdict, verdict)
    state = engine.run(council_state)

    assert state.global_status == "approved"
    assert state.turn_count == 2
    assert len(state.resolved_objections) == 1
    o = state.resolved_objections[0]
    assert o.status == "resolved"
    assert o.raised_by == "Security Architect"
    assert o.objection_text == "No TLS"
    assert o.consulted_experts == [ROLES[1]]
    assert o.turn_raised == 1 and o.turn_resolved == 1
    assert o.proposal_diff and "+line two (X)" in o.proposal_diff
    assert state.decision_log == ["D0", "Do X"]
    assert "line two (X)" in state.current_proposal


def test_objection_text_preserved_across_revisions(engine, gateway, council_state):
    """Original objection stays intact; narrowed concerns go to `revisions`."""
    rounds = {"n": 0}

    def verdict(model, system, user):
        if "Security Architect" in system and rounds["n"] == 0:
            rounds["n"] += 1
            return ExpertVerdict(approved=False, objection="Original concern", reasoning="")
        return ExpertVerdict(approved=True, reasoning="ok")

    evals = iter(
        [
            EvaluationResponse(
                satisfied=False, reasoning="", remaining_concerns="Narrower concern"
            ),
            EvaluationResponse(satisfied=True, reasoning="", accepted_solution="do X"),
        ]
    )
    gateway.on(ExpertVerdict, verdict)
    gateway.on(EvaluationResponse, lambda *_: next(evals))

    state = engine.run(council_state)
    o = state.resolved_objections[0]
    assert o.status == "resolved"
    assert o.objection_text == "Original concern"
    assert o.revisions == ["Narrower concern"]
    assert o.resolution_turns == 2
    assert [s.attempt for s in o.proposed_solutions] == [1, 2]


def test_deadlock_after_max_resolution_turns(engine, gateway, council_state, sink):
    rounds = {"n": 0}

    def verdict(model, system, user):
        if "Security Architect" in system and rounds["n"] == 0:
            rounds["n"] += 1
            return ExpertVerdict(approved=False, objection="Never happy", reasoning="")
        return ExpertVerdict(approved=True, reasoning="ok")

    gateway.on(ExpertVerdict, verdict)
    gateway.on(
        EvaluationResponse,
        EvaluationResponse(satisfied=False, reasoning="", remaining_concerns="still no"),
    )

    state = engine.run(council_state)  # max_resolution_turns=2 in fixture

    o = state.resolved_objections[0]
    assert o.status == "deadlocked"
    assert o.resolution_turns == 2
    assert len(sink.of_type(events.ObjectionDeadlocked)) == 1
    # Proposal unchanged; debate continued and reached consensus next round.
    assert state.current_proposal.startswith("# Draft v1\n\nline one\n")
    assert state.global_status == "approved"
    assert state.turn_count == 2


def test_stalemate_when_max_turns_exhausted(engine, gateway, council_state):
    council_state.max_turns = 2
    council_state.council = council_state.council[:1]  # one expert → no vote needed
    gateway.on(ExpertVerdict, ExpertVerdict(approved=False, objection="Nope", reasoning=""))
    gateway.on(
        EvaluationResponse,
        EvaluationResponse(satisfied=False, reasoning="", remaining_concerns="x"),
    )

    state = engine.run(council_state)

    assert state.global_status == "stalemate"
    assert state.turn_count == 2
    assert state.proposal_executive_summary == "Summary."  # summary still written


def test_vote_selects_highest_scoring_objection(engine, gateway, council_state, sink):
    rounds = {"n": 0}

    def verdict(model, system, user):
        if rounds["n"] < 3:  # first round: everyone objects
            rounds["n"] += 1
            role = next(r for r in ROLES if r in system)
            return ExpertVerdict(approved=False, objection=f"{role} objection", reasoning="")
        return ExpertVerdict(approved=True, reasoning="ok")

    def vote(model, system, user):
        # Everyone puts all points on the Product Manager's objection.
        ids = [line.split("ID: ")[1] for line in user.splitlines() if line.startswith("ID: ")]
        raised = [
            line.split("Raised by: ")[1]
            for line in user.splitlines()
            if line.startswith("Raised by: ")
        ]
        target = ids[raised.index("Product Manager")]
        return VoteResponse(votes=[ObjectionVote(objection_id=target, points=100)], reasoning="")

    gateway.on(ExpertVerdict, verdict)
    gateway.on(VoteResponse, vote)

    state = engine.run(council_state)

    (vote_event,) = sink.of_type(events.VoteCompleted)
    assert vote_event.winner.raised_by == "Product Manager"
    assert vote_event.tallies[vote_event.winner.id] == 300
    assert state.resolved_objections[0].raised_by == "Product Manager"
    assert state.global_status == "approved"


def test_resume_skips_collected_perspectives(engine, gateway, council_state, store):
    """Simulate a crash after two perspectives: only the third is re-requested."""
    from aicouncil.models import InitialPerspective

    council_state.global_status = "drafting"
    council_state.initial_perspectives = [
        InitialPerspective(expert_role=r, perspective="cached") for r in ROLES[:2]
    ]
    engine.run(council_state)

    perspective_calls = [c for c in gateway.calls if c["schema"] == "PerspectiveResponse"]
    assert len(perspective_calls) == 1
    assert ROLES[2] in perspective_calls[0]["system"]


def test_resume_from_debating_skips_drafting(engine, gateway, council_state):
    council_state.global_status = "debating"
    council_state.current_proposal = "existing"
    council_state.domain_states = {r: DomainState() for r in ROLES}
    engine.run(council_state)

    assert not any(
        c["schema"] in ("PerspectiveResponse", "FirstDraftResponse") for c in gateway.calls
    )
    assert council_state.current_proposal == "existing"


def test_models_are_routed_per_role(engine, gateway, council_state):
    council_state.council[0].model = "special/model"
    engine.run(council_state)

    by_schema = {}
    for c in gateway.calls:
        by_schema.setdefault(c["schema"], set()).add(c["model"])
    assert by_schema["FirstDraftResponse"] == {"test/moderator"}
    assert by_schema["ProposalSummaryResponse"] == {"test/moderator"}
    assert by_schema["PerspectiveResponse"] == {"special/model", "test/model"}
