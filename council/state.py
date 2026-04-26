"""
State persistence — filesystem-based, human-readable layout.

Each session is a structured folder under ./sessions/<idea_id>/:

    sessions/<idea_id>/
    ├── idea.txt                        # Original premise (plain text)
    ├── council.json                    # Council members (role + system_prompt)
    ├── context_summary.md              # Reference-file summary (if any)
    ├── file_references.json            # Raw file references with content (if any)
    ├── state.json                      # Thin checkpoint: status, counters, log
    ├── council.log                     # Debug log file
    ├── round_1/
    │   ├── draft_v1.md                 # First compiled proposal (drafting phase)
    │   ├── perspective_<slug>.json     # One file per expert perspective
    │   ├── objection_<id>.json         # Objections raised/resolved this round
    │   └── proposal.md                 # Proposal at the end of this round
    ├── round_2/
    │   ├── objection_<id>.json
    │   └── proposal.md
    └── final_report.md                 # Final Markdown report
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from .models import (
    CouncilState,
    DomainState,
    ExpertMember,
    FileReference,
    InitialPerspective,
    Objection,
)

logger = logging.getLogger("council")

SESSIONS_DIR = Path("sessions")


# ─── Helpers ─────────────────────────────────────────────────


def _slug(text: str) -> str:
    """Convert a role name to a safe, lowercase filename slug."""
    return re.sub(r"[^\w]+", "_", text).strip("_").lower()


def _round_dir(session_dir: Path, turn: int) -> Path:
    """Return (and lazily create) the directory for a given round number."""
    rd = session_dir / f"round_{turn}"
    rd.mkdir(exist_ok=True)
    return rd


# ─── Public API ──────────────────────────────────────────────


def get_session_dir(idea_id: str) -> Path:
    """Return the session directory, creating it if needed."""
    session_dir = SESSIONS_DIR / idea_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def save_state(state: CouncilState) -> Path:
    """
    Checkpoint the current state to a structured folder on disk.

    Fans out into multiple targeted writes so each artifact is a
    standalone, human-readable file. Called after every meaningful
    state change for crash recovery.

    Returns the path to the thin state.json checkpoint file.
    """
    state.updated_at = datetime.now()
    session_dir = get_session_dir(state.idea_id)

    # ── Thin checkpoint (control fields + decision log) ───────
    checkpoint = {
        "idea_id": state.idea_id,
        "global_status": state.global_status,
        "turn_count": state.turn_count,
        "max_turns": state.max_turns,
        "max_resolution_turns": state.max_resolution_turns,
        "model": state.model,
        "created_at": state.created_at.isoformat(),
        "updated_at": state.updated_at.isoformat(),
        "decision_log": state.decision_log,
        "domain_states": {
            role: ds.model_dump()
            for role, ds in state.domain_states.items()
        },
    }
    state_file = session_dir / "state.json"
    state_file.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")

    # ── idea.txt ─────────────────────────────────────────────
    (session_dir / "idea.txt").write_text(state.original_premise, encoding="utf-8")

    # ── council.json ─────────────────────────────────────────
    (session_dir / "council.json").write_text(
        json.dumps(
            {"council": [m.model_dump() for m in state.council]},
            indent=2,
        ),
        encoding="utf-8",
    )

    # ── context_summary.md ───────────────────────────────────
    if state.context_summary:
        (session_dir / "context_summary.md").write_text(
            state.context_summary, encoding="utf-8"
        )

    # ── file_references.json ─────────────────────────────────
    if state.file_references:
        (session_dir / "file_references.json").write_text(
            json.dumps([r.model_dump() for r in state.file_references], indent=2),
            encoding="utf-8",
        )

    # ── round_1/: perspectives + draft ───────────────────────
    if state.initial_perspectives:
        rd1 = _round_dir(session_dir, 1)

        for p in state.initial_perspectives:
            pf = rd1 / f"perspective_{_slug(p.expert_role)}.json"
            pf.write_text(p.model_dump_json(indent=2), encoding="utf-8")

        # draft_v1.md: written once the first compiled proposal is available
        # (turn_count is still 0 at that point — before debate begins)
        if state.current_proposal and not (rd1 / "draft_v1.md").exists():
            (rd1 / "draft_v1.md").write_text(state.current_proposal, encoding="utf-8")

    # ── round_<n>/proposal.md: current proposal per debate turn ──
    if state.current_proposal and state.turn_count > 0:
        rd = _round_dir(session_dir, state.turn_count)
        (rd / "proposal.md").write_text(state.current_proposal, encoding="utf-8")

    # ── Objections: queue + resolved ─────────────────────────
    # Deduplicate by id (an objection may live in both lists briefly during
    # resolution). Writing the same file twice is harmless — last write wins.
    seen: set[str] = set()
    all_objections = list(state.objection_queue) + list(state.resolved_objections)
    for obj in all_objections:
        if obj.id in seen:
            continue
        seen.add(obj.id)
        turn = obj.turn_raised or max(state.turn_count, 1)
        rd = _round_dir(session_dir, turn)
        (rd / f"objection_{obj.id}.json").write_text(
            obj.model_dump_json(indent=2), encoding="utf-8"
        )

    logger.debug("State checkpointed → %s", session_dir)
    return state_file


def load_state(idea_id: str) -> CouncilState:
    """
    Assemble a CouncilState from the filesystem layout.

    Reads the thin checkpoint first, then reconstructs all artifact
    fields by scanning the session directory tree.
    """
    session_dir = SESSIONS_DIR / idea_id
    if not session_dir.exists():
        raise FileNotFoundError(f"No session found: {session_dir}")

    state_file = session_dir / "state.json"
    if not state_file.exists():
        raise FileNotFoundError(f"No checkpoint found: {state_file}")

    # ── Thin checkpoint ───────────────────────────────────────
    checkpoint = json.loads(state_file.read_text(encoding="utf-8"))

    # ── idea.txt ─────────────────────────────────────────────
    idea_file = session_dir / "idea.txt"
    original_premise = idea_file.read_text(encoding="utf-8") if idea_file.exists() else ""

    # ── council.json ─────────────────────────────────────────
    council: list[ExpertMember] = []
    council_file = session_dir / "council.json"
    if council_file.exists():
        data = json.loads(council_file.read_text(encoding="utf-8"))
        council = [ExpertMember.model_validate(m) for m in data.get("council", [])]

    # ── context_summary.md ───────────────────────────────────
    context_summary = ""
    cs_file = session_dir / "context_summary.md"
    if cs_file.exists():
        context_summary = cs_file.read_text(encoding="utf-8")

    # ── file_references.json ─────────────────────────────────
    file_references: list[FileReference] = []
    fr_file = session_dir / "file_references.json"
    if fr_file.exists():
        fr_data = json.loads(fr_file.read_text(encoding="utf-8"))
        file_references = [FileReference.model_validate(r) for r in fr_data]

    # ── Perspectives from round_1/perspective_*.json ──────────
    initial_perspectives: list[InitialPerspective] = []
    rd1 = session_dir / "round_1"
    if rd1.exists():
        for pf in sorted(rd1.glob("perspective_*.json")):
            data = json.loads(pf.read_text(encoding="utf-8"))
            initial_perspectives.append(InitialPerspective.model_validate(data))

    # ── Current proposal: latest round_<n>/proposal.md ────────
    current_proposal = ""
    round_dirs = sorted(
        session_dir.glob("round_*/"),
        key=lambda p: int(p.name.split("_")[1]),
    )
    for rd in reversed(round_dirs):
        pm = rd / "proposal.md"
        if pm.exists():
            current_proposal = pm.read_text(encoding="utf-8")
            break
    # Fall back to draft_v1.md if debate hasn't started yet
    if not current_proposal and rd1.exists():
        dv1 = rd1 / "draft_v1.md"
        if dv1.exists():
            current_proposal = dv1.read_text(encoding="utf-8")

    # ── Objections from all round dirs ────────────────────────
    resolved_objections: list[Objection] = []
    objection_queue: list[Objection] = []
    for rd in round_dirs:
        for of in sorted(rd.glob("objection_*.json")):
            data = json.loads(of.read_text(encoding="utf-8"))
            obj = Objection.model_validate(data)
            if obj.status in ("resolved", "deadlocked", "overruled"):
                resolved_objections.append(obj)
            else:
                objection_queue.append(obj)

    # ── Domain states (from checkpoint) ───────────────────────
    domain_states: dict[str, DomainState] = {
        role: DomainState.model_validate(ds_data)
        for role, ds_data in checkpoint.get("domain_states", {}).items()
    }

    state = CouncilState(
        idea_id=checkpoint["idea_id"],
        created_at=datetime.fromisoformat(checkpoint["created_at"]),
        updated_at=datetime.fromisoformat(checkpoint["updated_at"]),
        original_premise=original_premise,
        file_references=file_references,
        context_summary=context_summary,
        council=council,
        domain_states=domain_states,
        initial_perspectives=initial_perspectives,
        current_proposal=current_proposal,
        objection_queue=objection_queue,
        resolved_objections=resolved_objections,
        decision_log=checkpoint.get("decision_log", []),
        global_status=checkpoint["global_status"],
        turn_count=checkpoint["turn_count"],
        max_turns=checkpoint["max_turns"],
        max_resolution_turns=checkpoint.get("max_resolution_turns", 5),
        model=checkpoint["model"],
    )

    logger.info(
        "State loaded ← %s (status: %s, turn: %d)",
        session_dir,
        state.global_status,
        state.turn_count,
    )
    return state


def list_sessions() -> list[dict]:
    """
    Return metadata for all saved sessions.

    Reads only the thin state.json checkpoint and council.json from each
    session directory — never loads the full state tree.
    """
    sessions = []
    if not SESSIONS_DIR.exists():
        return sessions

    for session_dir in sorted(SESSIONS_DIR.iterdir()):
        if not session_dir.is_dir():
            continue
        state_file = session_dir / "state.json"
        if not state_file.exists():
            continue
        try:
            checkpoint = json.loads(state_file.read_text(encoding="utf-8"))

            idea_file = session_dir / "idea.txt"
            premise = idea_file.read_text(encoding="utf-8") if idea_file.exists() else ""

            council_size = 0
            council_file = session_dir / "council.json"
            if council_file.exists():
                cd = json.loads(council_file.read_text(encoding="utf-8"))
                council_size = len(cd.get("council", []))

            sessions.append({
                "idea_id": checkpoint.get("idea_id", session_dir.name),
                "premise": (premise[:80] + "...") if len(premise) > 80 else premise,
                "status": checkpoint.get("global_status", "unknown"),
                "turn_count": checkpoint.get("turn_count", 0),
                "max_turns": checkpoint.get("max_turns", 15),
                "council_size": council_size,
                "created_at": checkpoint.get("created_at", ""),
                "updated_at": checkpoint.get("updated_at", ""),
            })
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Skipping corrupt session %s: %s", session_dir.name, exc)

    return sessions


def setup_logging(idea_id: str, verbose: bool = False) -> None:
    """
    Configure logging for a session.

    - File handler: always DEBUG level, writes to sessions/<id>/council.log
    - Console: handled by Rich, not configured here.
    """
    log = logging.getLogger("council")
    log.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on resume
    log.handlers = [h for h in log.handlers if not isinstance(h, logging.FileHandler)]

    session_dir = get_session_dir(idea_id)
    fh = logging.FileHandler(session_dir / "council.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    log.addHandler(fh)
