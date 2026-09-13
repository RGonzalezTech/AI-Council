from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from aicouncil import Council, MemorySessionStore, NullSink, Settings
from aicouncil.intake import load_reference_files
from aicouncil.schemas import ContextSummaryResponse, ExpertSuggestion, IntakeResponse

runner = CliRunner()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        model="test/model", sessions_dir=tmp_path / "sessions", max_file_size=100, _env_file=None
    )  # type: ignore[call-arg]


@pytest.fixture
def council(gateway, settings) -> Council:
    gateway.on(
        IntakeResponse,
        IntakeResponse(
            council=[
                ExpertSuggestion(role=f"R{i}", system_prompt="p", rationale="r") for i in range(3)
            ]
        ),
    )
    gateway.on(ExpertSuggestion, ExpertSuggestion(role="Added", system_prompt="p", rationale="r"))
    gateway.on(ContextSummaryResponse, ContextSummaryResponse(summary="ctx", key_details=[]))
    return Council(settings, gateway=gateway, store=MemorySessionStore(), sink=NullSink())


# ─── load_reference_files ────────────────────────────────────


def test_load_reference_files_filters(tmp_path, settings):
    ok = tmp_path / "ok.md"
    ok.write_text("hello", encoding="utf-8")
    big = tmp_path / "big.py"
    big.write_text("x" * 200, encoding="utf-8")
    binary = tmp_path / "bin.txt"
    binary.write_bytes(b"\xff\xfe\x00")
    unsupported = tmp_path / "img.png"
    unsupported.write_bytes(b"")

    result = load_reference_files([ok, big, binary, unsupported, tmp_path / "missing.md"], settings)

    assert [r.alias for r in result.accepted] == ["ok.md"]
    reasons = dict((p.name, r) for p, r in result.skipped)
    assert "per-file limit" in reasons["big.py"]
    assert reasons["bin.txt"] == "not UTF-8"
    assert "unsupported" in reasons["img.png"]
    assert reasons["missing.md"] == "not found"


# ─── Council façade ──────────────────────────────────────────


def test_new_session_sets_models_and_summarizes_files(council, tmp_path, gateway):
    f = tmp_path / "spec.md"
    f.write_text("spec", encoding="utf-8")
    state = council.new_session("Idea", model="a/b", moderator_model="c/d", files=[f])

    assert state.model == "a/b"
    assert state.moderator_model == "c/d"
    assert state.context_summary == "ctx"
    assert council.load(state.idea_id[:8]).idea_id == state.idea_id
    summarize_call = next(c for c in gateway.calls if c["schema"] == "ContextSummaryResponse")
    assert summarize_call["model"] == "c/d"


def test_moderator_defaults_to_expert_model(council):
    state = council.new_session("Idea", model="x/y")
    assert state.moderator_model == "x/y"


def test_generate_council_members_have_no_model_override(council, gateway):
    state = council.new_session("Idea")
    members = council.intake.generate_council(state, size=3)
    assert [m.role for m in members] == ["R0", "R1", "R2"]
    assert all(m.model is None for m in members)
    call = next(c for c in gateway.calls if c["schema"] == "IntakeResponse")
    assert "exactly 3 council members" in call["system"]
    assert council.intake.generate_member(state, "someone").role == "Added"


def test_full_run_and_render(council):
    state = council.new_session("Idea")
    state.council = council.intake.generate_council(state)
    state = council.run(state)
    assert state.global_status == "approved"
    docs = council.render_reports(state)
    assert {d.filename for d in docs} == {"final_report.md", "debate_log.md"}
    with pytest.raises(TypeError):
        council.write_reports(state)  # memory store has no directory


def test_stalemate_controls(council):
    state = council.new_session("Idea")
    state.global_status = "stalemate"
    state.max_turns = 2

    council.extend(state, 3)
    assert (state.global_status, state.max_turns) == ("debating", 5)

    council.accept(state)
    assert state.global_status == "approved"
    assert state.proposal_executive_summary == ""  # no proposal → nothing to summarize

    council.reject(state)
    assert council.load(state.idea_id).global_status == "rejected"


# ─── CLI smoke ───────────────────────────────────────────────


def test_cli_list_empty(tmp_path: Path):
    from aicouncil.cli import app

    result = runner.invoke(app, ["list", "--sessions-dir", str(tmp_path / "none")])
    assert result.exit_code == 0
    assert "No sessions found" in result.output


def test_cli_version():
    from aicouncil.cli import app

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "aicouncil" in result.output
