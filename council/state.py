"""
State persistence — checkpoint save/load for crash recovery.

Sessions are stored as JSON in ./sessions/<idea_id>/state.json.
The state is saved after every meaningful mutation so that a crashed
session can be resumed from the last checkpoint.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .models import CouncilState

logger = logging.getLogger("council")

SESSIONS_DIR = Path("sessions")


def get_session_dir(idea_id: str) -> Path:
    """Return the directory for a given session, creating it if needed."""
    session_dir = SESSIONS_DIR / idea_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def save_state(state: CouncilState) -> Path:
    """
    Checkpoint the current state to disk.

    Called after every meaningful state change so we can resume on crash.
    Returns the path to the saved file.
    """
    state.updated_at = datetime.now()
    session_dir = get_session_dir(state.idea_id)
    state_file = session_dir / "state.json"

    state_file.write_text(
        state.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.debug("State checkpointed → %s", state_file)
    return state_file


def load_state(idea_id: str) -> CouncilState:
    """Load a session state from disk."""
    session_dir = get_session_dir(idea_id)
    state_file = session_dir / "state.json"

    if not state_file.exists():
        raise FileNotFoundError(f"No session found: {state_file}")

    data = json.loads(state_file.read_text(encoding="utf-8"))
    state = CouncilState.model_validate(data)
    logger.info("State loaded ← %s (status: %s, turn: %d)", state_file, state.global_status, state.turn_count)
    return state


def list_sessions() -> list[dict]:
    """
    Return metadata for all saved sessions.

    Each entry contains: idea_id, premise (truncated), status, turn_count, created_at.
    """
    sessions = []
    if not SESSIONS_DIR.exists():
        return sessions

    for session_dir in sorted(SESSIONS_DIR.iterdir()):
        state_file = session_dir / "state.json"
        if not state_file.exists():
            continue
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            sessions.append({
                "idea_id": data.get("idea_id", session_dir.name),
                "premise": (data.get("original_premise", "")[:80] + "...")
                    if len(data.get("original_premise", "")) > 80
                    else data.get("original_premise", ""),
                "status": data.get("global_status", "unknown"),
                "turn_count": data.get("turn_count", 0),
                "max_turns": data.get("max_turns", 15),
                "council_size": len(data.get("council", [])),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
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
    fh.setLevel(logging.DEBUG if verbose else logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    log.addHandler(fh)
