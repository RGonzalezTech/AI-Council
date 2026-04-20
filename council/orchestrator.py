"""
Orchestrator — The state-machine debate engine.

Executes the phased flow:
  Phase 2 (Drafting):  Collect perspectives → Compile first draft
  Phase 3 (Debating):  Review rounds → Objection resolution → Consensus

State is checkpointed after every meaningful mutation for crash recovery.
"""

from __future__ import annotations

import logging
import random
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

from rich.console import Console

from . import display
from . import llm
from .models import (
    CouncilState,
    DomainState,
    InitialPerspective,
    Objection,
    ProposedSolution,
)
from .state import save_state

logger = logging.getLogger("council")


def run_council(state: CouncilState, con: Console) -> CouncilState:
    """
    Main entry point: run the full council pipeline from current state.

    Handles crash recovery by checking global_status and resuming from
    the correct phase.
    """
    if state.global_status in ("intake", "drafting"):
        state = _run_drafting_phase(state, con)

    if state.global_status == "debating":
        state = _run_debate_phase(state, con)

    return state


# ─── Phase 2: Drafting ───────────────────────────────────────


def _run_drafting_phase(state: CouncilState, con: Console) -> CouncilState:
    """Collect expert perspectives and compile the first draft."""
    display.show_phase("Phase 2: Generating First Draft")
    state.global_status = "drafting"
    save_state(state)

    # Collect perspectives — skip already-collected ones for crash recovery
    collected_roles = {p.expert_role for p in state.initial_perspectives}
    pending = [e for e in state.council if e.role not in collected_roles]

    # Log any already-cached roles immediately
    for expert in state.council:
        if expert.role in collected_roles:
            display.log_event(expert.role, "Perspective already collected ✓", "dim")

    if pending:
        display.log_event("Moderator", f"Gathering {len(pending)} perspectives in parallel...")
        labels = [e.role for e in pending]

        with ThreadPoolExecutor(max_workers=len(pending)) as executor:
            future_to_expert: dict[Future, object] = {
                executor.submit(
                    llm.expert_perspective,
                    expert=expert,
                    premise=state.original_premise,
                    context_summary=state.context_summary,
                    model=state.model,
                ): expert
                for expert in pending
            }
            futures = list(future_to_expert.keys())

            with display.parallel_spinners(
                labels=labels,
                futures=futures,
                title="Gathering Expert Perspectives",
            ):
                for fut in as_completed(futures):
                    expert = future_to_expert[fut]
                    resp = fut.result()  # re-raises any LLM exception
                    state.initial_perspectives.append(
                        InitialPerspective(
                            expert_role=expert.role,
                            perspective=resp.perspective,
                            key_concerns=resp.key_concerns,
                            suggested_approach=resp.suggested_approach,
                        )
                    )
                    display.log_event(expert.role, "📝 Perspective submitted")
                    save_state(state)

    # Compile first draft
    display.log_event("Moderator", "✍️  Compiling all perspectives into Draft v1...")
    with con.status("[bold cyan]Moderator is writing the first draft...[/]"):
        draft = llm.compile_first_draft(state=state, model=state.model)

    state.current_proposal = draft.proposal
    state.decision_log.extend(draft.key_decisions)
    state.global_status = "debating"

    # Initialize domain states for all experts
    for expert in state.council:
        state.domain_states[expert.role] = DomainState(status="review_pending")

    save_state(state)

    display.log_event("Moderator", "📄 Draft v1 ready")
    display.show_proposal(state.current_proposal, version="v1")

    return state


# ─── Phase 3: Debate ─────────────────────────────────────────


def _run_debate_phase(state: CouncilState, con: Console) -> CouncilState:
    """Run the debate loop until consensus, stalemate, or rejection."""
    display.show_phase("Phase 3: Council Debate")

    while state.global_status == "debating":
        state.turn_count += 1

        # ── Circuit breaker ──────────────────────────────────
        if state.turn_count > state.max_turns:
            state.global_status = "stalemate"
            save_state(state)
            display.show_stalemate_info(state)
            break

        display.log_event(
            "Moderator",
            f"Starting review round {state.turn_count}/{state.max_turns}...",
        )

        # ── Review round — stop at first objection ────────────
        state.objection_queue.clear()
        first_objection: Objection | None = None

        # Shuffle council members to vary the review order in each round
        reviewers = list(state.council)
        random.shuffle(reviewers)

        for expert in reviewers:
            state.domain_states[expert.role].status = "reviewing"
            display.log_event(expert.role, "Reviewing proposal...")

            with con.status(f"[bold magenta]{expert.role} is reviewing...[/]"):
                verdict = llm.expert_review(
                    expert=expert,
                    state=state,
                    model=state.model,
                )

            if verdict.approved:
                state.domain_states[expert.role].status = "approved"
                display.log_event(expert.role, "✅ Approved", "approved")
            else:
                state.domain_states[expert.role].status = "objecting"
                objection = Objection(
                    raised_by=expert.role,
                    objection_text=verdict.objection or verdict.reasoning,
                    turn_raised=state.turn_count,
                )
                state.objection_queue.append(objection)
                text = objection.objection_text
                if len(text) > 80:
                    text = text[:77] + "..."
                display.log_event(expert.role, f"🔴 Objected: {text}", "objecting")
                first_objection = objection
                # ── Resolve immediately — no need to poll the rest ──
                break

        save_state(state)
        display.show_status_board(state)

        # ── Check for consensus ──────────────────────────────
        if first_objection is None:
            state.global_status = "approved"
            save_state(state)
            display.log_event("Moderator", "🎉 All experts approve! Consensus reached.", "success")
            break

        display.log_event(
            "Moderator",
            "Objection raised — resolving immediately...",
        )

        # ── Resolve the objection ────────────────────────────
        first_objection.status = "in_resolution"
        save_state(state)

        state = _resolve_objection(state, first_objection, con)

        # ── Clear queue & reset all statuses for next round ──
        state.objection_queue.clear()
        for role in state.domain_states:
            state.domain_states[role].status = "review_pending"

        save_state(state)

    return state


# ─── Objection Resolution ───────────────────────────────────


def _resolve_objection(
    state: CouncilState,
    objection: Objection,
    con: Console,
) -> CouncilState:
    """
    Resolve a single objection through the full flow:
    Triage → Expert solutions → Synthesis → Evaluation → Judgment.
    """
    display.show_objection_detail(objection)

    # ── Triage: pick relevant experts ────────────────────────
    display.log_event("Moderator", f"🔍 Triaging objection from {objection.raised_by}...")
    with con.status("[bold cyan]Moderator is triaging...[/]"):
        triage = llm.moderator_triage(
            objection=objection,
            state=state,
            model=state.model,
        )

    # Filter to experts that actually exist and aren't the objector
    valid_roles = {m.role for m in state.council}
    relevant = [r for r in triage.relevant_experts if r in valid_roles and r != objection.raised_by]

    # Fallback: if triage returned nothing useful, pick all except objector
    if not relevant:
        relevant = [m.role for m in state.council if m.role != objection.raised_by]

    objection.consulted_experts = relevant
    display.log_event("Moderator", f"Consulting: {', '.join(relevant)}")

    # ── Collect solutions from relevant experts (in parallel) ─
    display.log_event("Moderator", f"Collecting solutions from: {', '.join(relevant)}")

    with ThreadPoolExecutor(max_workers=len(relevant)) as executor:
        future_to_role: dict[Future, str] = {
            executor.submit(
                llm.expert_solution,
                expert=next(e for e in state.council if e.role == role),
                objection=objection,
                state=state,
                model=state.model,
            ): role
            for role in relevant
        }
        futures = list(future_to_role.keys())

        with display.parallel_spinners(
            labels=relevant,
            futures=futures,
            title="Proposing Solutions",
        ):
            for fut in as_completed(futures):
                role = future_to_role[fut]
                resp = fut.result()  # re-raises any LLM exception
                objection.proposed_solutions.append(ProposedSolution(
                    expert_role=role,
                    solution=resp.solution,
                ))
                display.log_event(role, "💡 Solution proposed")
                save_state(state)

    # ── Resolution back-and-forth ────────────────────────────
    objector_expert = next(e for e in state.council if e.role == objection.raised_by)
    resolved = False

    for attempt in range(state.max_resolution_turns):
        objection.resolution_turns = attempt + 1

        # Moderator synthesizes
        display.log_event("Moderator", "📋 Synthesizing solutions...")
        with con.status("[bold cyan]Moderator synthesizing...[/]"):
            synthesis = llm.moderator_synthesize(
                objection=objection,
                state=state,
                model=state.model,
            )

        # Objector evaluates
        display.log_event(objection.raised_by, "Evaluating proposed solutions...")
        with con.status(f"[bold magenta]{objection.raised_by} is evaluating...[/]"):
            evaluation = llm.expert_evaluate(
                expert=objector_expert,
                objection=objection,
                synthesis=synthesis,
                model=state.model,
            )

        if evaluation.satisfied:
            # Moderator finalizes
            display.log_event("Moderator", "Agreement reached! Updating proposal...")
            with con.status("[bold cyan]Moderator is updating the proposal...[/]"):
                judgment = llm.moderator_judge(
                    objection=objection,
                    synthesis=synthesis,
                    state=state,
                    model=state.model,
                )

            objection.status = "resolved"
            objection.resolution_summary = judgment.decision_log_entry
            objection.turn_resolved = state.turn_count
            state.current_proposal = judgment.updated_proposal
            state.decision_log.append(judgment.decision_log_entry)
            state.resolved_objections.append(objection)
            resolved = True

            display.log_event(
                "Moderator",
                f"✅ Resolved: {judgment.decision_log_entry}",
                "success",
            )
            save_state(state)
            break
        else:
            remaining = evaluation.remaining_concerns or "unspecified concerns"
            display.log_event(
                objection.raised_by,
                f"Still unsatisfied: {remaining}",
                "warning",
            )
            # Update objection context for next round
            objection.objection_text = remaining
            logger.info(
                "Resolution attempt %d/%d failed for %s",
                attempt + 1,
                state.max_resolution_turns,
                objection.raised_by,
            )

    if not resolved:
        objection.status = "deadlocked"
        objection.turn_resolved = state.turn_count
        state.resolved_objections.append(objection)
        display.log_event(
            "Moderator",
            f"⚠️  Deadlock on objection from {objection.raised_by}",
            "warning",
        )
        save_state(state)

    return state
