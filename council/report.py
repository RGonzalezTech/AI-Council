"""
Report generation — produces two Markdown documents per session.

final_report.md  — Clean, executive-friendly summary. Lead with the answer,
                   key decisions, and a debate summary table. Full proposal
                   and council composition are collapsible via <details> tags.

debate_log.md    — Full verbose transcript: every objection, every proposed
                   solution, every diff, every initial perspective. This is
                   the raw record for anyone who wants to trace the reasoning.

Both files are saved inside sessions/<id>/ alongside all other session artifacts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .models import CouncilState
from .state import get_session_dir

logger = logging.getLogger("council")


# ─── Public API ──────────────────────────────────────────────


def save_report(state: CouncilState) -> tuple[Path, Path]:
    """Generate and save both reports inside the session directory."""
    session_dir = get_session_dir(state.idea_id)

    executive_report = generate_executive_report(state)
    debate_log = generate_debate_log(state)

    report_path = session_dir / "final_report.md"
    log_path = session_dir / "debate_log.md"

    report_path.write_text(executive_report, encoding="utf-8")
    log_path.write_text(debate_log, encoding="utf-8")

    logger.info("Report saved → %s", report_path)
    logger.info("Debate log saved → %s", log_path)

    return report_path, log_path


# ─── Executive Report ─────────────────────────────────────────


def generate_executive_report(state: CouncilState) -> str:
    """
    Build a concise, executive-friendly Markdown report.

    Structure:
      - Header with status badge and key stats
      - The Question (original premise)
      - The Answer (LLM executive summary)
      - Key Decisions (decision_log)
      - What Changed During Debate (summary table of objections)
      - The Council (collapsible)
      - Full Proposal (collapsible)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_objections = len(state.resolved_objections)
    resolved = sum(1 for o in state.resolved_objections if o.status == "resolved")
    deadlocked = sum(1 for o in state.resolved_objections if o.status == "deadlocked")
    overruled = sum(1 for o in state.resolved_objections if o.status == "overruled")

    lines: list[str] = []

    # ── Header ───────────────────────────────────────────────
    lines += [
        f"# 🏛️ AI Council Report",
        f"",
        f"**Status:** {_status_badge(state.global_status)} &nbsp;|&nbsp; "
        f"**Rounds:** {state.turn_count} &nbsp;|&nbsp; "
        f"**Objections:** {total_objections} resolved",
        f"",
        f"<sub>Generated: {now} &nbsp;·&nbsp; "
        f"Session: `{state.idea_id[:8]}` &nbsp;·&nbsp; "
        f"Model: `{state.model}`</sub>",
        f"",
        f"---",
        f"",
    ]

    # ── The Question ─────────────────────────────────────────
    lines += [
        f"## 📌 The Question",
        f"",
        f"> {state.original_premise}",
        f"",
    ]

    # ── The Answer (executive summary) ───────────────────────
    lines += [
        f"## 🎯 The Answer",
        f"",
    ]
    if state.proposal_executive_summary:
        lines += [
            state.proposal_executive_summary,
            f"",
        ]
    else:
        # Fallback: pull first 2 sentences of first decision log entry
        fallback = state.decision_log[0] if state.decision_log else state.current_proposal[:300]
        lines += [
            f"_{fallback}_",
            f"",
        ]

    # ── Key Decisions ────────────────────────────────────────
    if state.decision_log:
        lines += [
            f"## ⚖️ Key Decisions",
            f"",
            f"These are the binding rules and choices the council established:",
            f"",
        ]
        for i, decision in enumerate(state.decision_log, 1):
            lines.append(f"{i}. {decision}")
        lines += ["", ""]

    # ── What Changed During Debate ───────────────────────────
    if state.resolved_objections:
        lines += [
            f"## 🔄 What Changed During Debate",
            f"",
            f"| # | Raised By | Issue | Outcome |",
            f"|---|-----------|-------|---------|",
        ]
        for i, obj in enumerate(state.resolved_objections, 1):
            status_icon = {
                "resolved": "✅",
                "deadlocked": "🔒",
                "overruled": "⏭️",
            }.get(obj.status, "❓")

            # Truncate objection text for table
            issue = obj.objection_text
            if len(issue) > 70:
                issue = issue[:67] + "..."
            issue = issue.replace("\n", " ").replace("|", "\\|")

            resolution = obj.resolution_summary or obj.status.title()
            if len(resolution) > 70:
                resolution = resolution[:67] + "..."
            resolution = resolution.replace("\n", " ").replace("|", "\\|")

            lines.append(
                f"| {i} | **{obj.raised_by}** | {issue} | {status_icon} {resolution} |"
            )
        lines += ["", ""]

    # ── The Council (collapsible) ────────────────────────────
    lines += [
        f"## 👥 The Council",
        f"",
        f"<details>",
        f"<summary>{len(state.council)} expert members — click to expand</summary>",
        f"",
        f"| # | Expert | Lens |",
        f"|---|--------|------|",
    ]
    for i, member in enumerate(state.council, 1):
        # Use key_concerns from initial perspectives if available, else first sentence of prompt
        perspective = next(
            (p for p in state.initial_perspectives if p.expert_role == member.role),
            None,
        )
        if perspective and perspective.key_concerns:
            lens = "; ".join(perspective.key_concerns[:2])
        else:
            # First sentence of system prompt, up to 80 chars
            lens = member.system_prompt.split(".")[0]
            if len(lens) > 80:
                lens = lens[:77] + "..."
        lines.append(f"| {i} | **{member.role}** | {lens} |")

    lines += [
        f"",
        f"</details>",
        f"",
    ]

    # ── Full Proposal (collapsible) ──────────────────────────
    lines += [
        f"## 📋 Full Proposal",
        f"",
        f"<details>",
        f"<summary>Read the complete battle-tested proposal</summary>",
        f"",
        state.current_proposal,
        f"",
        f"</details>",
        f"",
    ]

    # ── Context (collapsible, if present) ────────────────────
    if state.context_summary:
        lines += [
            f"<details>",
            f"<summary>📚 Reference Context</summary>",
            f"",
            f"{state.context_summary}",
            f"",
            f"</details>",
            f"",
        ]

    # ── Footer ───────────────────────────────────────────────
    lines += [
        f"---",
        f"",
        f"<sub>📎 Full debate transcript: [debate_log.md](debate_log.md)</sub>  ",
        f"<sub>*Generated by [AI Council](https://github.com/RGonzalezTech/council)*</sub>",
    ]

    return "\n".join(lines)


# ─── Debate Log ──────────────────────────────────────────────


def generate_debate_log(state: CouncilState) -> str:
    """
    Build the verbose debate transcript Markdown file.

    Contains the full text of every objection, every proposed solution,
    every proposal diff, every initial perspective, and all statistics.
    This is the complete record — nothing is trimmed.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_objections = len(state.resolved_objections)
    resolved = sum(1 for o in state.resolved_objections if o.status == "resolved")
    deadlocked = sum(1 for o in state.resolved_objections if o.status == "deadlocked")
    overruled = sum(1 for o in state.resolved_objections if o.status == "overruled")

    lines: list[str] = []

    # ── Header ───────────────────────────────────────────────
    lines += [
        f"# 📜 AI Council — Debate Log",
        f"",
        f"Full transcript for session `{state.idea_id}`.",
        f"",
        f"**Original Question:** {state.original_premise}  ",
        f"**Generated:** {now}  ",
        f"**Status:** {_status_badge(state.global_status)}  ",
        f"**Model:** `{state.model}`",
        f"",
        f"↩ [Back to Report](final_report.md)",
        f"",
        f"---",
        f"",
    ]

    # ── Debate Statistics ────────────────────────────────────
    lines += [
        f"## 📊 Session Statistics",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Review Rounds | {state.turn_count} |",
        f"| Total Objections | {total_objections} |",
        f"| Resolved | {resolved} |",
        f"| Deadlocked | {deadlocked} |",
        f"| Overruled | {overruled} |",
        f"| Council Size | {len(state.council)} |",
        f"",
    ]

    # ── Full Debate Journey ───────────────────────────────────
    if state.resolved_objections:
        lines += [
            f"---",
            f"",
            f"## ⚔️ Debate Journey",
            f"",
        ]

        for i, obj in enumerate(state.resolved_objections, 1):
            status_icon = {
                "resolved": "✅",
                "deadlocked": "🔒",
                "overruled": "⏭️",
            }.get(obj.status, "❓")

            lines += [
                f"### {status_icon} Objection #{i} — {obj.raised_by}",
                f"",
                f"**Raised in Round:** {obj.turn_raised}  ",
                f"**Status:** {obj.status.title()}  ",
                f"**Resolution Rounds:** {obj.resolution_turns}",
                f"",
                f"**Objection:**",
                f"> {obj.objection_text}",
                f"",
            ]

            if obj.consulted_experts:
                lines += [
                    f"**Consulted:** {', '.join(obj.consulted_experts)}",
                    f"",
                ]

            if obj.proposed_solutions:
                lines.append(f"**Proposed Solutions:**")
                lines.append(f"")
                for ps in obj.proposed_solutions:
                    lines.append(f"<details>")
                    lines.append(f"<summary>{ps.expert_role}</summary>")
                    lines.append(f"")
                    lines.append(ps.solution)
                    lines.append(f"")
                    lines.append(f"</details>")
                    lines.append(f"")

            if obj.resolution_summary:
                lines += [
                    f"**Resolution:** {obj.resolution_summary}",
                    f"",
                ]

            if getattr(obj, "proposal_diff", None):
                lines += [
                    f"**Proposal Changes:**",
                    f"```diff",
                    obj.proposal_diff.strip(),
                    f"```",
                    f"",
                ]

            lines.append("---")
            lines.append("")

    # ── Initial Perspectives ─────────────────────────────────
    if state.initial_perspectives:
        lines += [
            f"## 💭 Initial Expert Perspectives",
            f"",
            f"First-impression takes from each expert before the debate began.",
            f"",
        ]
        for p in state.initial_perspectives:
            lines += [
                f"<details>",
                f"<summary>{p.expert_role}</summary>",
                f"",
                f"{p.perspective}",
                f"",
            ]
            if p.key_concerns:
                lines.append(f"**Key Concerns:** {', '.join(p.key_concerns)}")
                lines.append("")
            if p.suggested_approach:
                lines.append(f"**Suggested Approach:** {p.suggested_approach}")
                lines.append("")
            lines.append(f"</details>")
            lines.append("")

    # ── Footer ───────────────────────────────────────────────
    lines += [
        f"---",
        f"",
        f"<sub>*Generated by [AI Council](https://github.com/RGonzalezTech/council)*</sub>",
    ]

    return "\n".join(lines)


# ─── Helpers ─────────────────────────────────────────────────


def _status_badge(status: str) -> str:
    """Return a styled status badge."""
    badges = {
        "approved": "✅ **APPROVED**",
        "stalemate": "⚠️ **STALEMATE**",
        "rejected": "❌ **REJECTED**",
        "debating": "🔄 **IN PROGRESS**",
        "drafting": "📝 **DRAFTING**",
        "intake": "📥 **INTAKE**",
    }
    return badges.get(status, f"❓ **{status.upper()}**")


# ─── Legacy shim ─────────────────────────────────────────────
# Kept so any code importing generate_report doesn't break.


def generate_report(state: CouncilState) -> str:
    """Legacy alias — returns the executive report."""
    return generate_executive_report(state)
