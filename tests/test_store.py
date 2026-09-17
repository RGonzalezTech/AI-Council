from __future__ import annotations

import pytest

from aicouncil import CouncilState, ExpertMember, FileSessionStore, MemorySessionStore
from aicouncil.models import Objection
from aicouncil.store import SessionNotFound


@pytest.fixture(params=["memory", "file"])
def store(request, tmp_path):
    if request.param == "memory":
        return MemorySessionStore()
    return FileSessionStore(tmp_path / "sessions")


def _state(**kw) -> CouncilState:
    return CouncilState(
        original_premise="Q?",
        model="m",
        moderator_model="mm",
        council=[ExpertMember(role="A", system_prompt="a")],
        **kw,
    )


def test_round_trip(store):
    s = _state(current_proposal="P", decision_log=["d"], turn_count=3)
    s.resolved_objections.append(
        Objection(raised_by="A", objection_text="o", status="resolved", turn_raised=1)
    )
    store.save(s)
    loaded = store.load(s.idea_id)
    assert loaded == s


def test_list_and_prefix(store):
    a, b = _state(), _state()
    store.save(a)
    store.save(b)
    ids = {r.idea_id for r in store.list()}
    assert ids == {a.idea_id, b.idea_id}
    assert store.resolve_id(a.idea_id[:8]) == a.idea_id


def test_missing_and_ambiguous(store):
    with pytest.raises(SessionNotFound):
        store.load("nope")
    with pytest.raises(SessionNotFound):
        store.resolve_id("nope")
    a, b = _state(idea_id="aaaa-1"), _state(idea_id="aaaa-2")
    store.save(a)
    store.save(b)
    with pytest.raises(SessionNotFound, match="Ambiguous"):
        store.resolve_id("aaaa")


def test_file_store_layout(tmp_path):
    store = FileSessionStore(tmp_path)
    s = _state(current_proposal="draft")
    store.save(s)
    s.turn_count = 1
    s.current_proposal = "round one"
    store.save(s)
    d = tmp_path / s.idea_id
    assert (d / "state.json").exists()
    assert (d / "idea.txt").read_text(encoding="utf-8") == "Q?"
    assert (d / "proposals" / "draft_v1.md").read_text(encoding="utf-8") == "draft"
    assert (d / "proposals" / "round_1.md").read_text(encoding="utf-8") == "round one"
    assert (d / "proposal.md").read_text(encoding="utf-8") == "round one"
    assert not list(d.glob("*.tmp"))


def test_file_store_skips_corrupt_session(tmp_path):
    store = FileSessionStore(tmp_path)
    store.save(_state())
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "state.json").write_text("{not json", encoding="utf-8")
    assert len(store.list()) == 1
