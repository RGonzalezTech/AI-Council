"""
The debate engine — a pure state machine.

`DebateEngine` advances a `CouncilState` through drafting and debate. It
depends only on three protocols (LLM operations, a session store, an event
sink) and never touches the console or the filesystem directly. That makes
it runnable headless, embeddable, and testable with fakes.

    intake → drafting → debating → approved | stalemate
                                 ↑                 ↓ (caller extends max_turns)
                                 └─────────────────┘
"""

from __future__ import annotations

import difflib
import logging
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from functools import partial
from typing import TypeVar

from .events import (
    DebateFinished,
    DraftReady,
    EventSink,
    Message,
    NullSink,
    ObjectionDeadlocked,
    ObjectionResolved,
    ObjectionSelected,
    ParallelFinished,
    ParallelItemDone,
    ParallelStarted,
    PhaseStarted,
    ReviewRoundFinished,
    ReviewRoundStarted,
    VoteCompleted,
)
from .llm import CouncilLLM
from .models import (
    CouncilState,
    DomainState,
    ExpertMember,
    InitialPerspective,
    Objection,
    ProposedSolution,
)
from .settings import Settings
from .store import SessionStore

logger = logging.getLogger("aicouncil")

T = TypeVar("T")


class DebateEngine:
    def __init__(
        self,
        llm: CouncilLLM,
        store: SessionStore,
        sink: EventSink | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._llm = llm
        self._store = store
        self._sink = sink or NullSink()
        self._settings = settings or Settings()

    # ── Public API ───────────────────────────────────────────

    def run(self, state: CouncilState) -> CouncilState:
        """Advance the session as far as possible from its current status."""
        if state.global_status in ("intake", "drafting"):
            self._draft(state)
        if state.global_status == "debating":
            self._debate(state)
        return state

    def summarize(self, state: CouncilState) -> CouncilState:
        """Populate the executive summary (idempotent)."""
        if not state.proposal_executive_summary and state.current_proposal:
            self._say("Moderator", "Writing executive summary...")
            state.proposal_executive_summary = self._llm.summarize_proposal(
                state.current_proposal, state.original_premise, model=state.moderator_model
            )
            self._checkpoint(state)
        return state

    # ── Internals: helpers ───────────────────────────────────

    def _say(self, actor: str, text: str, level: str = "info") -> None:
        logger.info("[%s] %s", actor, text)
        self._sink.emit(Message(actor=actor, text=text, level=level))

    def _checkpoint(self, state: CouncilState) -> None:
        self._store.save(state)

    def _parallel(
        self,
        title: str,
        items: Iterable[tuple[str, Callable[[], T]]],
        on_done: Callable[[str, T], None],
    ) -> None:
        """
        Run `(label, thunk)` pairs concurrently, emitting progress events.

        `on_done` runs on the calling thread as each result arrives, so it may
        mutate state safely. Any exception propagates after the batch is
        cancelled — the caller's last checkpoint remains valid.
        """
        items = list(items)
        if not items:
            return
        batch_id = uuid.uuid4().hex[:8]
        labels = tuple(label for label, _ in items)
        self._sink.emit(ParallelStarted(title=title, labels=labels, batch_id=batch_id))
        workers = min(len(items), self._settings.max_workers)
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures: dict[Future[T], str] = {
                    pool.submit(thunk): label for label, thunk in items
                }
                for fut in as_completed(futures):
                    label = futures[fut]
                    result = fut.result()
                    self._sink.emit(ParallelItemDone(batch_id=batch_id, label=label))
                    on_done(label, result)
        finally:
            self._sink.emit(ParallelFinished(batch_id=batch_id))

    # ── Phase: drafting ──────────────────────────────────────

    def _draft(self, state: CouncilState) -> None:
        state.global_status = "drafting"
        self._sink.emit(PhaseStarted(phase="drafting", state=state))
        self._checkpoint(state)

        collected = {p.expert_role for p in state.initial_perspectives}
        pending = [e for e in state.council if e.role not in collected]
        for e in state.council:
            if e.role in collected:
                self._say(e.role, "Perspective already collected", "dim")

        def _collect(role: str, resp) -> None:
            state.initial_perspectives.append(
                InitialPerspective(
                    expert_role=role,
                    perspective=resp.perspective,
                    key_concerns=resp.key_concerns,
                    suggested_approach=resp.suggested_approach,
                )
            )
            self._say(role, "Perspective submitted")
            self._checkpoint(state)

        self._parallel(
            "Gathering Expert Perspectives",
            [
                (
                    e.role,
                    partial(
                        self._llm.expert_perspective,
                        e,
                        state.original_premise,
                        state.context_summary,
                        model=state.model_for(e),
                    ),
                )
                for e in pending
            ],
            _collect,
        )

        self._say("Moderator", "Compiling all perspectives into Draft v1...")
        draft = self._llm.compile_first_draft(state, model=state.moderator_model)

        state.current_proposal = draft.proposal
        state.decision_log.extend(draft.key_decisions)
        state.domain_states = {e.role: DomainState() for e in state.council}
        state.global_status = "debating"
        self._checkpoint(state)

        self._sink.emit(DraftReady(state=state, points_of_debate=tuple(draft.points_of_debate)))

    # ── Phase: debating ──────────────────────────────────────

    def _debate(self, state: CouncilState) -> None:
        self._sink.emit(PhaseStarted(phase="debating", state=state))

        while state.global_status == "debating":
            if state.turn_count >= state.max_turns:
                state.global_status = "stalemate"
                self._checkpoint(state)
                self._say("Moderator", f"No consensus after {state.turn_count} rounds", "warning")
                break

            state.turn_count += 1
            self._review_round(state)

            if not state.objection_queue:
                state.global_status = "approved"
                self._checkpoint(state)
                self._say("Moderator", "All experts approve — consensus reached", "success")
                break

            selected = self._select_objection(state)
            self._sink.emit(ObjectionSelected(objection=selected))
            selected.status = "in_resolution"
            self._checkpoint(state)

            self._resolve(state, selected)

            state.objection_queue.clear()
            for ds in state.domain_states.values():
                ds.status = "review_pending"
            self._checkpoint(state)

        self.summarize(state)
        self._sink.emit(DebateFinished(state=state))

    def _review_round(self, state: CouncilState) -> None:
        self._say("Moderator", f"Review round {state.turn_count}/{state.max_turns}")
        self._sink.emit(ReviewRoundStarted(state=state))

        state.objection_queue.clear()
        for e in state.council:
            state.domain_states[e.role].status = "reviewing"

        def _record(role: str, verdict) -> None:
            if verdict.approved:
                state.domain_states[role].status = "approved"
                self._say(role, "Approved", "success")
            else:
                state.domain_states[role].status = "objecting"
                objection = Objection(
                    raised_by=role,
                    objection_text=verdict.objection or verdict.reasoning,
                    turn_raised=state.turn_count,
                )
                state.objection_queue.append(objection)
                self._say(role, f"Objected: {_short(objection.objection_text)}", "warning")

        self._parallel(
            f"Review Round {state.turn_count}",
            [
                (e.role, partial(self._llm.expert_review, e, state, model=state.model_for(e)))
                for e in state.council
            ],
            _record,
        )
        self._checkpoint(state)
        self._sink.emit(ReviewRoundFinished(state=state))

    def _select_objection(self, state: CouncilState) -> Objection:
        if len(state.objection_queue) == 1:
            return state.objection_queue[0]
        return self._vote(state, list(state.objection_queue))

    def _vote(self, state: CouncilState, objections: list[Objection]) -> Objection:
        self._say("Moderator", f"{len(objections)} objections raised — voting on priority")
        tallies: dict[str, int] = {o.id: 0 for o in objections}

        def _tally(role: str, vote) -> None:
            valid = [v for v in vote.votes if v.objection_id in tallies and v.points > 0]
            total = sum(v.points for v in valid)
            if total > 0:
                for v in valid:
                    tallies[v.objection_id] += round(v.points * 100 / total)
            self._say(role, "Vote cast")

        self._parallel(
            "Voting on Objections",
            [
                (
                    e.role,
                    partial(self._llm.expert_vote, e, objections, state, model=state.model_for(e)),
                )
                for e in state.council
            ],
            _tally,
        )

        # Deterministic tie-break: earliest in queue wins.
        winner = max(objections, key=lambda o: (tallies[o.id], -objections.index(o)))
        self._sink.emit(VoteCompleted(objections=tuple(objections), tallies=tallies, winner=winner))
        return winner

    # ── Objection resolution ─────────────────────────────────

    def _resolve(self, state: CouncilState, objection: Objection) -> None:
        objector = state.expert(objection.raised_by)
        consulted = self._triage(state, objection)
        objection.consulted_experts = consulted
        self._say("Moderator", f"Consulting: {', '.join(consulted)}")

        for attempt in range(1, state.max_resolution_turns + 1):
            objection.resolution_turns = attempt
            solutions = self._collect_solutions(state, objection, consulted, attempt)
            solutions_block = "\n\n".join(
                f"--- {s.expert_role} ---\n{s.solution}" for s in solutions
            )

            self._say(objection.raised_by, "Evaluating proposed solutions...")
            evaluation = self._llm.expert_evaluate(
                objector, objection, solutions_block, model=state.model_for(objector)
            )

            if evaluation.satisfied:
                self._apply_resolution(
                    state, objection, evaluation.accepted_solution or solutions_block
                )
                return

            remaining = evaluation.remaining_concerns or evaluation.reasoning
            objection.revisions.append(remaining)
            self._say(objection.raised_by, f"Still unsatisfied: {_short(remaining)}", "warning")
            self._checkpoint(state)

        objection.status = "deadlocked"
        objection.turn_resolved = state.turn_count
        state.resolved_objections.append(objection)
        self._checkpoint(state)
        self._say("Moderator", f"Deadlock on objection from {objection.raised_by}", "warning")
        self._sink.emit(ObjectionDeadlocked(objection=objection))

    def _triage(self, state: CouncilState, objection: Objection) -> list[str]:
        self._say("Moderator", f"Triaging objection from {objection.raised_by}...")
        triage = self._llm.moderator_triage(objection, state, model=state.moderator_model)
        valid = {m.role for m in state.council} - {objection.raised_by}
        chosen = [r for r in triage.relevant_experts if r in valid]
        return chosen or sorted(valid)

    def _collect_solutions(
        self, state: CouncilState, objection: Objection, roles: list[str], attempt: int
    ) -> list[ProposedSolution]:
        title = "Proposing Solutions" if attempt == 1 else f"Revising Solutions (attempt {attempt})"
        batch: list[ProposedSolution] = []

        def _keep(role: str, resp) -> None:
            ps = ProposedSolution(expert_role=role, solution=resp.solution, attempt=attempt)
            batch.append(ps)
            objection.proposed_solutions.append(ps)
            self._say(role, "Solution proposed")
            self._checkpoint(state)

        self._parallel(
            title,
            [
                (
                    role,
                    partial(
                        self._llm.expert_solution,
                        state.expert(role),
                        objection,
                        state,
                        model=state.model_for(role),
                    ),
                )
                for role in roles
            ],
            _keep,
        )
        return batch

    def _apply_resolution(self, state: CouncilState, objection: Objection, solution: str) -> None:
        self._say("Moderator", "Agreement reached — updating proposal...")
        judgment = self._llm.moderator_judge(
            objection, solution, state, model=state.moderator_model
        )

        diff = "".join(
            difflib.unified_diff(
                state.current_proposal.splitlines(keepends=True),
                judgment.updated_proposal.splitlines(keepends=True),
                fromfile="Proposal (before)",
                tofile="Proposal (after)",
            )
        )

        objection.status = "resolved"
        objection.resolution_summary = judgment.decision_log_entry
        objection.proposal_diff = diff
        objection.turn_resolved = state.turn_count
        state.current_proposal = judgment.updated_proposal
        state.decision_log.append(judgment.decision_log_entry)
        state.resolved_objections.append(objection)
        self._checkpoint(state)

        self._say("Moderator", f"Resolved: {judgment.decision_log_entry}", "success")
        self._sink.emit(
            ObjectionResolved(objection=objection, decision=judgment.decision_log_entry, diff=diff)
        )


def _short(text: str, n: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 3] + "..."


__all__ = ["DebateEngine", "ExpertMember"]
