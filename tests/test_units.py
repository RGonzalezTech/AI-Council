from __future__ import annotations

from datetime import datetime

import pytest

from aicouncil import CouncilState, ExpertMember, MarkdownRenderer, Settings
from aicouncil.llm.prompts import DEFAULT_PROMPTS, Prompt, PromptLibrary
from aicouncil.models import InitialPerspective, Objection, ProposedSolution
from aicouncil.schemas import EvaluationResponse, ExpertVerdict

# ─── Schemas ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected", [("true", True), ("False", False), (" yes ", True), (False, False)]
)
def test_bool_coercion(raw, expected):
    assert ExpertVerdict(approved=raw, reasoning="r").approved is expected
    assert EvaluationResponse(satisfied=raw, reasoning="r").satisfied is expected


# ─── Settings ────────────────────────────────────────────────


def test_settings_resolve_alias_and_passthrough():
    s = Settings(model="gemini-pro", _env_file=None)  # type: ignore[call-arg]
    assert s.resolved_model == "gemini/gemini-2.5-pro"
    assert s.resolve_model("openrouter/x/y") == "openrouter/x/y"
    assert s.resolve_model("unknown-alias") == "unknown-alias"
    assert s.resolved_moderator_model == s.resolved_model


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("COUNCIL_MODEL", "deepseek-flash")
    monkeypatch.setenv("COUNCIL_MODERATOR_MODEL", "gemini-flash")
    monkeypatch.setenv("COUNCIL_MAX_TURNS", "3")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.resolved_model == "openrouter/deepseek/deepseek-v4-flash"
    assert s.resolved_moderator_model == "gemini/gemini-2.5-flash"
    assert s.max_turns == 3


# ─── Prompts ─────────────────────────────────────────────────


def test_every_default_prompt_renders_with_declared_fields():
    """Each prompt's format fields must be satisfiable — catches typos in field names."""
    import string

    fmt = string.Formatter()
    for _name, prompt in DEFAULT_PROMPTS.items():
        fields = {f for _, f, _, _ in fmt.parse(prompt.system + prompt.user) if f}
        prompt.render(**{f: "x" for f in fields})  # must not raise


def test_prompt_override():
    lib = PromptLibrary(overrides={"expert_review": Prompt(system="S {role}", user="U {proposal}")})
    assert lib.render(
        "expert_review", role="R", proposal="P", system_prompt="", decision_log_block=""
    ) == ("S R", "U P")
    assert lib.get("expert_vote") is DEFAULT_PROMPTS["expert_vote"]
    with pytest.raises(KeyError):
        lib.get("nope")


# ─── Reports ─────────────────────────────────────────────────


def _finished_state() -> CouncilState:
    o = Objection(
        raised_by="Sec",
        objection_text="Bad | pipes\nand newlines",
        revisions=["narrower"],
        status="resolved",
        consulted_experts=["DB"],
        proposed_solutions=[ProposedSolution(expert_role="DB", solution="fix", attempt=1)],
        resolution_turns=1,
        resolution_summary="Fixed",
        proposal_diff="--- a\n+++ b\n+fix\n",
        turn_raised=1,
        turn_resolved=1,
    )
    return CouncilState(
        idea_id="abcdef12-0000",
        original_premise="Q?",
        model="m",
        moderator_model="m",
        council=[
            ExpertMember(role="Sec", system_prompt="Security. More."),
            ExpertMember(role="DB", system_prompt="Data."),
        ],
        initial_perspectives=[
            InitialPerspective(expert_role="Sec", perspective="p", key_concerns=["k1", "k2", "k3"])
        ],
        current_proposal="# Final",
        proposal_executive_summary="We decided.",
        decision_log=["D1"],
        resolved_objections=[o],
        global_status="approved",
        turn_count=2,
    )


def test_markdown_reports():
    docs = MarkdownRenderer(now=datetime(2026, 1, 1, 12, 0)).render(_finished_state())
    names = [d.filename for d in docs]
    assert names == ["final_report.md", "debate_log.md"]
    report, log = (d.content for d in docs)

    assert "✅ **APPROVED**" in report
    assert "We decided." in report
    assert "1. D1" in report
    assert "| 1 | **Sec** | Bad \\| pipes and newlines | ✅ Fixed |" in report
    assert "| 1 | **Sec** | k1; k2 |" in report  # lens from key concerns
    assert "| 2 | **DB** | Data |" in report  # lens from first sentence
    assert "Generated: 2026-01-01 12:00" in report

    assert "### ✅ Objection #1 — Sec" in log
    assert "**Narrowed to:**\n1. narrower" in log
    assert "```diff\n--- a\n+++ b\n+fix\n```" in log
    assert "| Review Rounds | 2 |" in log


def test_report_fallback_without_summary():
    s = _finished_state()
    s.proposal_executive_summary = ""
    assert "_D1_" in MarkdownRenderer().executive_report(s)
