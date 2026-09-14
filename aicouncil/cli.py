"""
CLI entry point.

  council init <premise>    Start a session: intake → edit council → draft → debate → report
  council resume [id]       Resume a crashed or stalemated session
  council list              Show saved sessions
  council show <id>         Display a session's current state
  council report <id>       Regenerate reports for a session
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from . import __version__
from .app import Council
from .models import CouncilState
from .settings import Settings
from .store import FileSessionStore, SessionNotFound
from .ui import RichSink, make_console
from .ui import prompts as ask
from .ui import rich_ui as ui

app = typer.Typer(
    name="council",
    help="AI Council — multi-agent LLM debate for stress-testing ideas.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)
con = make_console()

SessionsDirOpt = Annotated[
    Path | None,
    typer.Option("--sessions-dir", help="Where to store sessions (env: COUNCIL_SESSIONS_DIR)."),
]
VerboseOpt = Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging to council.log.")]


def _version(value: bool) -> None:
    if value:
        con.print(f"aicouncil {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    # Provider API keys (OPENROUTER_API_KEY etc.) must be in the process env for LiteLLM.
    # Settings handles COUNCIL_* itself; this covers everything else in .env.
    load_dotenv()


# ─── Wiring ──────────────────────────────────────────────────


def _settings(sessions_dir: Path | None) -> Settings:
    if sessions_dir is not None:
        return Settings(sessions_dir=sessions_dir)
    return Settings()


def _council(settings: Settings, quiet: bool = False) -> Council:
    return Council(settings, sink=None if quiet else RichSink(con))


def _setup_logging(council: Council, idea_id: str, verbose: bool) -> None:
    log = logging.getLogger("aicouncil")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.handlers = [h for h in log.handlers if not isinstance(h, logging.FileHandler)]
    assert isinstance(council.store, FileSessionStore)
    fh = logging.FileHandler(council.store.session_dir(idea_id) / "council.log", encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    log.addHandler(fh)


def _load(council: Council, idea_id: str) -> CouncilState:
    try:
        return council.load(idea_id)
    except SessionNotFound as exc:
        ui.error(con, f"No session found: {exc}")
        raise typer.Exit(1) from None


# ─── Commands ────────────────────────────────────────────────


@app.command()
def init(
    premise: Annotated[str, typer.Argument(help="The idea or question to evaluate.")],
    model: Annotated[
        str | None, typer.Option("--model", "-m", help="LiteLLM model string for experts.")
    ] = None,
    moderator_model: Annotated[
        str | None, typer.Option("--moderator-model", help="Moderator model. Defaults to --model.")
    ] = None,
    max_turns: Annotated[
        int | None, typer.Option("--max-turns", help="Review rounds before stalemate.")
    ] = None,
    council_size: Annotated[
        int | None, typer.Option("--size", help="Number of experts to generate.")
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Accept the generated council without editing.")
    ] = False,
    sessions_dir: SessionsDirOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Start a new council session."""
    settings = _settings(sessions_dir)
    council = _council(settings)

    ui.banner(con)
    ui.idea(con, premise)

    with _guard(None), con.status("[bold cyan]Preparing session...[/]"):
        state = council.new_session(
            premise,
            model=model,
            moderator_model=moderator_model,
            max_turns=max_turns,
        )
    _setup_logging(council, state.idea_id, verbose)

    ui.phase(con, "Phase 1: Council Assembly")
    with _guard(state), con.status("[bold cyan]Assembling council...[/]"):
        state.council = council.intake.generate_council(state, council_size)
    council.store.save(state)

    if yes:
        ui.council_table(con, state.council)
    else:
        state.council = ask.edit_council(
            con,
            state.council,
            generate_member=lambda intent: council.intake.generate_member(state, intent),
            default_model=state.model,
        )
        council.store.save(state)

    _run_and_finish(council, state)


@app.command()
def resume(
    session_id: Annotated[str | None, typer.Argument(help="Session id or unique prefix.")] = None,
    sessions_dir: SessionsDirOpt = None,
    verbose: VerboseOpt = False,
) -> None:
    """Resume a crashed or stalemated session."""
    council = _council(_settings(sessions_dir))
    if session_id is None:
        session_id = ask.pick_session(council.store.list(), "Select a session to resume:")
        if session_id is None:
            ui.error(con, "No sessions found.")
            raise typer.Exit(1)

    state = _load(council, session_id)
    _setup_logging(council, state.idea_id, verbose)

    ui.banner(con)
    ui.idea(con, state.original_premise)
    con.print(f"  [dim]Resuming from {state.global_status} (round {state.turn_count})[/]")

    if state.is_terminal:
        ui.success(con, f"This session is already {state.global_status}.")
        raise typer.Exit()

    if state.global_status == "stalemate" and not _handle_stalemate(council, state):
        return

    _run_and_finish(council, state)


@app.command(name="list")
def list_cmd(sessions_dir: SessionsDirOpt = None) -> None:
    """List saved sessions."""
    council = _council(_settings(sessions_dir), quiet=True)
    rows = council.store.list()
    if not rows:
        ui.error(con, "No sessions found. Run 'council init \"<idea>\"' to start one.")
        raise typer.Exit()
    ui.sessions_table(con, rows)


@app.command()
def show(
    session_id: Annotated[str, typer.Argument(help="Session id or unique prefix.")],
    sessions_dir: SessionsDirOpt = None,
) -> None:
    """Show a session's current state."""
    council = _council(_settings(sessions_dir), quiet=True)
    state = _load(council, session_id)

    ui.banner(con)
    ui.idea(con, state.original_premise)
    con.print(f"\n  [dim]Session:[/]   {state.idea_id}")
    con.print(f"  [dim]Status:[/]    {state.global_status}")
    con.print(f"  [dim]Round:[/]     {state.turn_count}/{state.max_turns}")
    con.print(f"  [dim]Model:[/]     {state.model}")
    con.print(f"  [dim]Moderator:[/] {state.moderator_model}\n")
    if state.council:
        ui.council_table(con, state.council)
    if state.domain_states:
        ui.status_board(con, state)
    if state.decision_log:
        con.print("\n[bold bright_cyan]Decision Log:[/]")
        for i, d in enumerate(state.decision_log, 1):
            con.print(f"  {i}. {d}")
    if state.current_proposal:
        ui.proposal(con, state.current_proposal, f"round {state.turn_count}")


@app.command()
def report(
    session_id: Annotated[str, typer.Argument(help="Session id or unique prefix.")],
    sessions_dir: SessionsDirOpt = None,
) -> None:
    """Regenerate the Markdown reports for a session."""
    council = _council(_settings(sessions_dir), quiet=True)
    state = _load(council, session_id)
    _write_reports(council, state)


# ─── Shared flows ────────────────────────────────────────────


@contextmanager
def _guard(state: CouncilState | None) -> Iterator[None]:
    """Turn provider failures and Ctrl-C into a short message plus a resume hint."""
    hint = f"Resume with: council resume {state.idea_id[:8]}" if state else ""
    try:
        yield
    except KeyboardInterrupt:
        con.print()
        ui.error(con, f"Interrupted. {hint}".strip())
        raise typer.Exit(130) from None
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 — any provider/network failure
        logging.getLogger("aicouncil").exception("Run failed")
        ui.error(con, f"{type(exc).__name__}: {exc}")
        if hint:
            ui.error(con, f"Progress was saved. {hint}")
        raise typer.Exit(1) from None


def _run_and_finish(council: Council, state: CouncilState) -> None:
    with _guard(state):
        state = council.run(state)

    if state.global_status == "stalemate":
        if not _handle_stalemate(council, state):
            return
        _run_and_finish(council, state)
        return

    ui.verdict(con, state)
    _write_reports(council, state)


def _handle_stalemate(council: Council, state: CouncilState) -> bool:
    """Ask the user what to do. Returns True if the engine should run again."""
    ui.stalemate_info(con, state)
    action = ask.stalemate_action()
    if action == "extend":
        council.extend(state)
        return True
    if action == "approve":
        council.accept(state)
    elif action == "reject":
        council.reject(state)
    ui.verdict(con, state)
    _write_reports(council, state)
    return False


def _write_reports(council: Council, state: CouncilState) -> None:
    paths = council.write_reports(state)
    ui.paths(
        con,
        [(label, str(p)) for label, p in zip(["📄 Report", "📜 Debate log"], paths, strict=False)],
    )


if __name__ == "__main__":
    app()
