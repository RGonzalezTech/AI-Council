"""
CLI entry point — Typer application with all council commands.

Commands:
  council init <prompt>    Full pipeline: intake → CRUD → draft → debate → report
  council resume [id]      Resume a crashed or stalemate session
  council list             Show all saved sessions
  council show <id>        Display current state of a session
  council report <id>      Regenerate the Markdown report
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv
from InquirerPy import inquirer
from rich.console import Console

from . import display, llm
from .config import DEFAULT_MODEL, MODELS, resolve_model
from .models import (
    CouncilState,
    ExpertMember,
    FileReference,
    MAX_FILE_SIZE,
    MAX_TOTAL_SIZE,
    SUPPORTED_EXTENSIONS,
)
from .orchestrator import run_council
from .report import generate_executive_report, save_report
from .state import (
    list_sessions,
    load_state,
    save_state,
    setup_logging,
)

logger = logging.getLogger("council")

load_dotenv()

app = typer.Typer(
    name="council",
    help="AI Council -- Multi-agent LLM debate for stress-testing ideas.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

con = Console()


# ─── Init Command ────────────────────────────────────────────


@app.command()
def init(
    premise: Annotated[str, typer.Argument(help="The idea or prompt to evaluate")],
    files: Annotated[
        Optional[list[Path]],
        typer.Option("--file", "-f", help="Reference file(s) to include as context"),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="LLM model to use (alias or LiteLLM string)"),
    ] = DEFAULT_MODEL,
    max_turns: Annotated[
        int,
        typer.Option("--max-turns", help="Maximum debate rounds before stalemate"),
    ] = 15,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose logging"),
    ] = False,
):
    """
    Start a new council session.

    Takes your idea, assembles an expert council, generates a first-draft
    proposal, and runs a structured debate until consensus is reached.
    """
    # ── Create initial state ─────────────────────────────────
    state = CouncilState(
        original_premise=premise,
        model=resolve_model(model),
        max_turns=max_turns,
    )

    setup_logging(state.idea_id, verbose)
    logger.info("New session: %s", state.idea_id)
    logger.info("Premise: %s", premise)
    logger.info("Model: %s", model)

    display.show_banner()
    display.show_idea(premise)

    # ── Load file references ─────────────────────────────────
    if files:
        state.file_references = _load_files(files)
        if state.file_references:
            display.log_event(
                "System",
                f"Loaded {len(state.file_references)} file(s) as reference context",
            )
            # Summarize files to save tokens
            display.log_event("Moderator", "Summarizing reference materials...")
            with con.status("[bold cyan]Analyzing reference files...[/]"):
                summary = llm.summarize_files(
                    files=state.file_references,
                    model=model,
                )
            state.context_summary = summary.summary
            display.log_event("Moderator", "📚 Context summary ready")

    save_state(state)

    # ── Phase 1: Intake — generate council ───────────────────
    display.show_phase("Phase 1: Council Assembly")
    display.log_event("Moderator", "Analyzing idea and assembling council...")

    with con.status("[bold cyan]Generating council recommendations...[/]"):
        intake = llm.generate_council(
            premise=premise,
            context_summary=state.context_summary,
            model=model,
        )

    state.council = [
        ExpertMember(
            role=s.role,
            system_prompt=s.system_prompt,
            model=state.model,
        )
        for s in intake.council
    ]
    save_state(state)

    # ── Council CRUD ─────────────────────────────────────────
    state.council = _council_crud(state.council, premise, model)
    save_state(state)

    display.log_event("Moderator", f"Council locked: {len(state.council)} members")

    # ── Run the pipeline ─────────────────────────────────────
    state = run_council(state, con)

    # ── Generate report ──────────────────────────────────────
    _finalize(state)


# ─── Resume Command ──────────────────────────────────────────


@app.command()
def resume(
    session_id: Annotated[
        Optional[str],
        typer.Argument(help="Session ID to resume (omit to pick from list)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose logging"),
    ] = False,
):
    """
    Resume a crashed or stalemate session.

    If no session ID is provided, displays a list to choose from.
    """
    if session_id is None:
        session_id = _pick_session("Select a session to resume:")
        if session_id is None:
            return

    try:
        state = load_state(session_id)
    except FileNotFoundError:
        display.show_error(f"No session found with ID: {session_id}")
        raise typer.Exit(1)

    setup_logging(state.idea_id, verbose)
    logger.info("Resuming session: %s (status: %s)", state.idea_id, state.global_status)

    display.show_banner()
    display.show_idea(state.original_premise)
    display.log_event("System", f"Resuming from: {state.global_status} (turn {state.turn_count})")

    if state.global_status in ("approved", "rejected"):
        display.show_success(f"This session is already {state.global_status}.")
        raise typer.Exit(0)

    if state.global_status == "stalemate":
        # Let user decide how to handle stalemate
        action = _handle_stalemate(state)
        if action == "force_approve":
            state.global_status = "approved"
            save_state(state)
            _finalize(state)
            return
        elif action == "extend":
            state.max_turns += 10
            state.global_status = "debating"
            save_state(state)
        elif action == "reject":
            state.global_status = "rejected"
            save_state(state)
            _finalize(state)
            return

    state = run_council(state, con)
    _finalize(state)


# ─── List Command ────────────────────────────────────────────


@app.command(name="list")
def list_cmd():
    """List all saved council sessions."""
    sessions = list_sessions()

    if not sessions:
        display.show_error("No sessions found. Run 'council init' to start one.")
        raise typer.Exit(0)

    from rich.table import Table
    from rich import box

    table = Table(
        title="[bold bright_cyan]Council Sessions[/]",
        box=box.ROUNDED,
        border_style="cyan",
    )
    table.add_column("Session ID", style="dim", max_width=12)
    table.add_column("Premise", style="white", max_width=50)
    table.add_column("Status", justify="center")
    table.add_column("Turns", justify="center")
    table.add_column("Council", justify="center")
    table.add_column("Updated", style="dim")

    status_styles = {
        "intake": "[dim yellow]intake[/]",
        "drafting": "[yellow]drafting[/]",
        "debating": "[cyan]debating[/]",
        "approved": "[green]✅ approved[/]",
        "rejected": "[red]❌ rejected[/]",
        "stalemate": "[yellow]⚠️ stalemate[/]",
    }

    for s in sessions:
        sid = s["idea_id"][:8] + "..."
        status = status_styles.get(s["status"], s["status"])
        turns = f"{s['turn_count']}/{s['max_turns']}"
        table.add_row(
            sid,
            s["premise"],
            status,
            turns,
            str(s["council_size"]),
            s.get("updated_at", "")[:19],
        )

    con.print(table)


# ─── Show Command ────────────────────────────────────────────


@app.command()
def show(
    session_id: Annotated[str, typer.Argument(help="Session ID to display")],
):
    """Show the current state of a session."""
    try:
        state = load_state(session_id)
    except FileNotFoundError:
        display.show_error(f"No session found with ID: {session_id}")
        raise typer.Exit(1)

    display.show_banner()
    display.show_idea(state.original_premise)
    con.print(f"\n  [dim]Session:[/] {state.idea_id}")
    con.print(f"  [dim]Status:[/]  {state.global_status}")
    con.print(f"  [dim]Turn:[/]    {state.turn_count}/{state.max_turns}")
    con.print(f"  [dim]Model:[/]   {state.model}")
    con.print()

    if state.council:
        display.show_council_table(state.council)

    if state.domain_states:
        display.show_status_board(state)

    if state.current_proposal:
        display.show_proposal(state.current_proposal)

    if state.decision_log:
        con.print("\n[bold bright_cyan]Decision Log:[/]")
        for i, d in enumerate(state.decision_log, 1):
            con.print(f"  {i}. {d}")
        con.print()


# ─── Report Command ──────────────────────────────────────────


@app.command()
def report(
    session_id: Annotated[str, typer.Argument(help="Session ID to generate report for")],
):
    """Regenerate the Markdown report for a session."""
    try:
        state = load_state(session_id)
    except FileNotFoundError:
        display.show_error(f"No session found with ID: {session_id}")
        raise typer.Exit(1)

    report_path, log_path = save_report(state)
    display.show_report_path([str(report_path), str(log_path)])


# ═══════════════════════════════════════════════════════════════
#  Private helpers
# ═══════════════════════════════════════════════════════════════


def _load_files(paths: list[Path]) -> list[FileReference]:
    """Read file references from disk, respecting size limits."""
    refs: list[FileReference] = []
    total_size = 0

    for path in paths:
        if not path.exists():
            display.show_error(f"File not found: {path}")
            continue

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            display.show_error(
                f"Unsupported file type: {path.suffix} ({path.name})"
            )
            continue

        size = path.stat().st_size
        if size > MAX_FILE_SIZE:
            display.show_error(
                f"File too large ({size // 1024}KB > {MAX_FILE_SIZE // 1024}KB): {path.name}"
            )
            continue

        if total_size + size > MAX_TOTAL_SIZE:
            display.show_error(
                f"Total file size limit reached ({MAX_TOTAL_SIZE // 1024}KB). "
                f"Skipping: {path.name}"
            )
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            display.show_error(f"Cannot read file (not UTF-8): {path.name}")
            continue

        refs.append(FileReference(
            path=str(path),
            alias=path.name,
            content=content,
            size_bytes=size,
        ))
        total_size += size
        logger.info("Loaded file: %s (%d bytes)", path.name, size)

    return refs


def _council_crud(
    council: list[ExpertMember],
    premise: str,
    model: str,
) -> list[ExpertMember]:
    """Interactive CRUD loop for editing the council composition."""
    while True:
        display.show_council_table(council)
        con.print()

        action = inquirer.select(
            message="What would you like to do?",
            choices=[
                {"name": "✅ Accept council and begin debate", "value": "accept"},
                {"name": "✏️  Edit a member", "value": "edit"},
                {"name": "🗑️  Remove a member", "value": "delete"},
                {"name": "➕ Add a new member", "value": "add"},
            ],
            default="accept",
        ).execute()

        if action == "accept":
            if not council:
                display.show_error("Council must have at least one member!")
                continue
            break

        elif action == "edit":
            if not council:
                display.show_error("No members to edit.")
                continue

            choices = [
                {"name": f"{m.role}", "value": i}
                for i, m in enumerate(council)
            ]
            idx = inquirer.select(
                message="Select a member to edit:",
                choices=choices,
            ).execute()

            member = council[idx]
            con.print(f"\n  [dim]Current role:[/] {member.role}")
            new_role = inquirer.text(
                message="New role (enter to keep):",
                default=member.role,
            ).execute()

            con.print(f"\n  [dim]Current system prompt:[/]")
            con.print(f"  {member.system_prompt}\n")
            new_prompt = inquirer.text(
                message="New system prompt (enter to keep):",
                default=member.system_prompt,
            ).execute()

            con.print(f"\n  [dim]Current model override:[/]")
            con.print(f"  {member.model or 'None (uses session default)'}\n")
            model_choices = [{"name": "Session Default", "value": ""}]
            for name, val in MODELS.items():
                model_choices.append({"name": name.title(), "value": val})

            new_model = inquirer.select(
                message="New model override:",
                choices=model_choices,
                default=member.model or "",
            ).execute()

            council[idx] = ExpertMember(
                role=new_role.strip() or member.role,
                system_prompt=new_prompt.strip() or member.system_prompt,
                model=new_model or None,
            )
            display.show_success(f"Updated: {council[idx].role}")

        elif action == "delete":
            if not council:
                display.show_error("No members to remove.")
                continue

            choices = [
                {"name": f"{m.role}", "value": i}
                for i, m in enumerate(council)
            ]
            idx = inquirer.select(
                message="Select a member to remove:",
                choices=choices,
            ).execute()

            removed = council.pop(idx)
            display.show_success(f"Removed: {removed.role}")

        elif action == "add":
            intent = inquirer.text(
                message="What kind of expert do you want? (e.g., 'a paranoid security expert'):",
            ).execute()

            if intent.strip():
                with con.status("[bold cyan]Generating member...[/]"):
                    suggestion = llm.generate_vibe_member(
                        intent=intent.strip(),
                        premise=premise,
                        current_council=council,
                        model=model,
                    )
                
                council.append(ExpertMember(
                    role=suggestion.role,
                    system_prompt=suggestion.system_prompt,
                    model=model,
                ))
                display.show_success(f"Added: {suggestion.role}")
            else:
                display.show_error("Intent is required.")

    return council


def _handle_stalemate(state: CouncilState) -> str:
    """Ask the user how to handle a stalemate."""
    display.show_stalemate_info(state)

    action = inquirer.select(
        message="How would you like to proceed?",
        choices=[
            {"name": "🔄 Extend debate (+10 turns)", "value": "extend"},
            {"name": "✅ Force approve current proposal", "value": "force_approve"},
            {"name": "❌ Reject and close session", "value": "reject"},
        ],
    ).execute()

    return action


def _pick_session(message: str) -> str | None:
    """Display a session picker and return the selected ID."""
    sessions = list_sessions()

    if not sessions:
        display.show_error("No sessions found.")
        return None

    choices = [
        {
            "name": f"[{s['status']}] {s['premise'][:50]}... ({s['idea_id'][:8]})",
            "value": s["idea_id"],
        }
        for s in sessions
    ]

    return inquirer.select(
        message=message,
        choices=choices,
    ).execute()


def _finalize(state: CouncilState) -> None:
    """Display verdict and save the reports."""
    display.show_verdict(state)

    if state.global_status in ("approved", "rejected", "stalemate"):
        report_path, log_path = save_report(state)
        display.show_report_path([str(report_path), str(log_path)])
