"""
Report generation — produces the final Markdown document.

The Moderator writes a comprehensive multi-page report covering:
- The original idea and context
- Council composition
- The final battle-tested proposal
- The debate journey (objections, resolutions, decisions)
- Statistics and outcomes

The report is saved as sessions/<id>/final_report.md alongside all
other session artifacts rather than in a separate reports/ directory.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .models import CouncilState
from .state import get_session_dir

logger = logging.getLogger("council")


def generate_report(state: CouncilState) -> str:
    """
    Build a comprehensive Markdown report from the final council state.

    This is a deterministic template-based report (no LLM call needed)
    since we have all the structured data.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_objections = len(state.resolved_objections)
    resolved = sum(1 for o in state.resolved_objections if o.status == "resolved")
    deadlocked = sum(1 for o in state.resolved_objections if o.status == "deadlocked")
    overruled = sum(1 for o in state.resolved_objections if o.status == "overruled")

    # ── Header ───────────────────────────────────────────────
    lines = [
        f"# 🏛️ AI Council Report",
        f"",
        f"**Generated:** {now}  ",
        f"**Session:** `{state.idea_id}`  ",
        f"**Model:** `{state.model}`  ",
        f"**Status:** {_status_badge(state.global_status)}",
        f"",
        f"---",
        f"",
    ]

    # ── Original Idea ────────────────────────────────────────
    lines += [
        f"## 📌 Original Idea",
        f"",
        f"> {state.original_premise}",
        f"",
    ]

    # ── Context (if any) ─────────────────────────────────────
    if state.context_summary:
        lines += [
            f"### Reference Context",
            f"",
            f"{state.context_summary}",
            f"",
        ]

    # ── Council Composition ──────────────────────────────────
    lines += [
        f"---",
        f"",
        f"## 👥 Council Composition",
        f"",
        f"| # | Role | Focus Area |",
        f"|---|------|------------|",
    ]
    for i, member in enumerate(state.council, 1):
        # First sentence of system prompt as summary
        focus = member.system_prompt.split(".")[0] + "."
        if len(focus) > 80:
            focus = focus[:77] + "..."
        lines.append(f"| {i} | **{member.role}** | {focus} |")

    lines += ["", ""]

    # ── Final Proposal ───────────────────────────────────────
    lines += [
        f"---",
        f"",
        f"## 📋 Final Proposal",
        f"",
        state.current_proposal,
        f"",
    ]

    # ── Debate Statistics ────────────────────────────────────
    lines += [
        f"---",
        f"",
        f"## 📊 Debate Statistics",
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

    # ── Decision Log ─────────────────────────────────────────
    if state.decision_log:
        lines += [
            f"---",
            f"",
            f"## 📜 Decision Log",
            f"",
            f"Key decisions and rules established during the debate:",
            f"",
        ]
        for i, decision in enumerate(state.decision_log, 1):
            lines.append(f"{i}. {decision}")
        lines += ["", ""]

    # ── Debate Journey ───────────────────────────────────────
    if state.resolved_objections:
        lines += [
            f"---",
            f"",
            f"## ⚔️ The Debate Journey",
            f"",
        ]

        for i, obj in enumerate(state.resolved_objections, 1):
            status_icon = {
                "resolved": "✅",
                "deadlocked": "🔒",
                "overruled": "⏭️",
            }.get(obj.status, "❓")

            lines += [
                f"### {status_icon} Objection #{i}: {obj.raised_by}",
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
                    lines.append(f"- **{ps.expert_role}:** {ps.solution}")
                lines.append(f"")

            if obj.resolution_summary:
                lines += [
                    f"**Resolution:** {obj.resolution_summary}",
                    f"",
                ]

            lines.append("")

    # ── Initial Perspectives ─────────────────────────────────
    if state.initial_perspectives:
        lines += [
            f"---",
            f"",
            f"## 💭 Initial Expert Perspectives",
            f"",
        ]
        for p in state.initial_perspectives:
            lines += [
                f"### {p.expert_role}",
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

    # ── Footer ───────────────────────────────────────────────
    lines += [
        f"---",
        f"",
        f"*Generated by [AI Council](https://github.com/council) v0.1.0*",
    ]

    return "\n".join(lines)


def save_report(state: CouncilState) -> Path:
    """Generate and save the report inside the session directory."""
    report = generate_report(state)

    session_dir = get_session_dir(state.idea_id)
    report_path = session_dir / "final_report.md"
    report_path.write_text(report, encoding="utf-8")

    logger.info("Report saved → %s", report_path)
    return report_path


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
