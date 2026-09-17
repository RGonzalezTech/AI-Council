"""
Markdown renderer — produces two documents per session.

final_report.md  Executive summary: the answer, key decisions, what changed,
                 collapsible council and full proposal.
debate_log.md    Verbose transcript: every objection, solution, diff, and
                 initial perspective.
"""

from __future__ import annotations

from datetime import datetime

from ..models import CouncilState, Objection
from .base import RenderedReport

_STATUS_BADGE = {
    "approved": "✅ **APPROVED**",
    "stalemate": "⚠️ **STALEMATE**",
    "rejected": "❌ **REJECTED**",
    "debating": "🔄 **IN PROGRESS**",
    "drafting": "📝 **DRAFTING**",
    "intake": "📥 **INTAKE**",
}
_OBJ_ICON = {"resolved": "✅", "deadlocked": "🔒", "overruled": "⏭️"}
REPO_URL = "https://github.com/RGonzalezTech/AI-Council"


def _badge(status: str) -> str:
    return _STATUS_BADGE.get(status, f"❓ **{status.upper()}**")


def _cell(text: str, n: int = 70) -> str:
    text = " ".join(text.split()).replace("|", "\\|")
    return text if len(text) <= n else text[: n - 3] + "..."


class MarkdownRenderer:
    def __init__(self, *, now: datetime | None = None) -> None:
        self._now = now  # injectable for deterministic tests

    def render(self, state: CouncilState) -> list[RenderedReport]:
        return [
            RenderedReport("final_report.md", self.executive_report(state)),
            RenderedReport("debate_log.md", self.debate_log(state)),
        ]

    # ── Executive report ─────────────────────────────────────

    def executive_report(self, state: CouncilState) -> str:
        now = (self._now or datetime.now()).strftime("%Y-%m-%d %H:%M")
        st = state.stats()
        out: list[str] = [
            "# 🏛️ AI Council Report",
            "",
            f"**Status:** {_badge(state.global_status)} &nbsp;|&nbsp; "
            f"**Rounds:** {st['rounds']} &nbsp;|&nbsp; "
            f"**Objections:** {st['objections']} ({st['resolved']} resolved, "
            f"{st['deadlocked']} deadlocked)",
            "",
            f"<sub>Generated: {now} &nbsp;·&nbsp; Session: `{state.idea_id[:8]}` &nbsp;·&nbsp; "
            f"Model: `{state.model}`</sub>",
            "",
            "---",
            "",
            "## 📌 The Question",
            "",
            f"> {state.original_premise}",
            "",
            "## 🎯 The Answer",
            "",
        ]
        if state.proposal_executive_summary:
            out += [state.proposal_executive_summary, ""]
        else:
            fallback = state.decision_log[0] if state.decision_log else state.current_proposal[:300]
            out += [f"_{fallback}_", ""]

        if state.decision_log:
            out += [
                "## ⚖️ Key Decisions",
                "",
                "Binding rules and choices the council established:",
                "",
            ]
            out += [f"{i}. {d}" for i, d in enumerate(state.decision_log, 1)]
            out += [""]

        if state.resolved_objections:
            out += [
                "## 🔄 What Changed During Debate",
                "",
                "| # | Raised By | Issue | Outcome |",
                "|---|-----------|-------|---------|",
            ]
            for i, o in enumerate(state.resolved_objections, 1):
                icon = _OBJ_ICON.get(o.status, "❓")
                outcome = o.resolution_summary or o.status.title()
                out.append(
                    f"| {i} | **{o.raised_by}** | {_cell(o.objection_text)} | {icon} {_cell(outcome)} |"
                )
            out += [""]

        out += [
            "## 👥 The Council",
            "",
            "<details>",
            f"<summary>{len(state.council)} expert members — click to expand</summary>",
            "",
            "| # | Expert | Lens |",
            "|---|--------|------|",
        ]
        for i, m in enumerate(state.council, 1):
            p = next((p for p in state.initial_perspectives if p.expert_role == m.role), None)
            lens = (
                "; ".join(p.key_concerns[:2])
                if p and p.key_concerns
                else _cell(m.system_prompt.split(".")[0], 80)
            )
            out.append(f"| {i} | **{m.role}** | {lens} |")
        out += ["", "</details>", ""]

        out += [
            "## 📋 Full Proposal",
            "",
            "<details>",
            "<summary>Read the complete proposal</summary>",
            "",
            state.current_proposal,
            "",
            "</details>",
            "",
        ]
        if state.context_summary:
            out += [
                "<details>",
                "<summary>📚 Reference Context</summary>",
                "",
                state.context_summary,
                "",
                "</details>",
                "",
            ]
        out += [
            "---",
            "",
            "<sub>📎 Full debate transcript: [debate_log.md](debate_log.md)</sub>  ",
            f"<sub>*Generated by [AI Council]({REPO_URL})*</sub>",
        ]
        return "\n".join(out)

    # ── Debate log ───────────────────────────────────────────

    def debate_log(self, state: CouncilState) -> str:
        now = (self._now or datetime.now()).strftime("%Y-%m-%d %H:%M")
        st = state.stats()
        out: list[str] = [
            "# 📜 AI Council — Debate Log",
            "",
            f"Full transcript for session `{state.idea_id}`.",
            "",
            f"**Original Question:** {state.original_premise}  ",
            f"**Generated:** {now}  ",
            f"**Status:** {_badge(state.global_status)}  ",
            f"**Model:** `{state.model}`",
            "",
            "↩ [Back to Report](final_report.md)",
            "",
            "---",
            "",
            "## 📊 Session Statistics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Review Rounds | {st['rounds']} |",
            f"| Total Objections | {st['objections']} |",
            f"| Resolved | {st['resolved']} |",
            f"| Deadlocked | {st['deadlocked']} |",
            f"| Overruled | {st['overruled']} |",
            f"| Council Size | {len(state.council)} |",
            "",
        ]

        if state.resolved_objections:
            out += ["---", "", "## ⚔️ Debate Journey", ""]
            for i, o in enumerate(state.resolved_objections, 1):
                out += self._objection_section(i, o)

        if state.initial_perspectives:
            out += [
                "## 💭 Initial Expert Perspectives",
                "",
                "First-impression takes from each expert before the debate began.",
                "",
            ]
            for p in state.initial_perspectives:
                out += ["<details>", f"<summary>{p.expert_role}</summary>", "", p.perspective, ""]
                if p.key_concerns:
                    out += [f"**Key Concerns:** {', '.join(p.key_concerns)}", ""]
                if p.suggested_approach:
                    out += [f"**Suggested Approach:** {p.suggested_approach}", ""]
                out += ["</details>", ""]

        out += ["---", "", f"<sub>*Generated by [AI Council]({REPO_URL})*</sub>"]
        return "\n".join(out)

    def _objection_section(self, i: int, o: Objection) -> list[str]:
        out = [
            f"### {_OBJ_ICON.get(o.status, '❓')} Objection #{i} — {o.raised_by}",
            "",
            f"**Raised in Round:** {o.turn_raised}  ",
            f"**Status:** {o.status.title()}  ",
            f"**Resolution Attempts:** {o.resolution_turns}",
            "",
            "**Objection:**",
            f"> {o.objection_text}",
            "",
        ]
        if o.revisions:
            out += ["**Narrowed to:**"]
            out += [f"{n}. {r}" for n, r in enumerate(o.revisions, 1)]
            out += [""]
        if o.consulted_experts:
            out += [f"**Consulted:** {', '.join(o.consulted_experts)}", ""]
        if o.proposed_solutions:
            out += ["**Proposed Solutions:**", ""]
            for ps in o.proposed_solutions:
                label = (
                    ps.expert_role
                    if ps.attempt == 1
                    else f"{ps.expert_role} (attempt {ps.attempt})"
                )
                out += [
                    "<details>",
                    f"<summary>{label}</summary>",
                    "",
                    ps.solution,
                    "",
                    "</details>",
                    "",
                ]
        if o.resolution_summary:
            out += [f"**Resolution:** {o.resolution_summary}", ""]
        if o.proposal_diff:
            out += ["**Proposal Changes:**", "```diff", o.proposal_diff.strip(), "```", ""]
        out += ["---", ""]
        return out
