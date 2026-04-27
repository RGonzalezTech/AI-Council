"""
Rich terminal display utilities for the AI Council CLI.

Provides styled output for every phase of the debate: council tables,
live status boards, event logging with timestamps, and verdict panels.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from rich import box
from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from .models import CouncilState, ExpertMember, Objection

logger = logging.getLogger("council")

# ─── Theme ───────────────────────────────────────────────────

COUNCIL_THEME = Theme({
    "header": "bold bright_white",
    "moderator": "bold cyan",
    "expert": "bold magenta",
    "approved": "bold green",
    "objecting": "bold red",
    "pending": "dim yellow",
    "info": "dim white",
    "phase": "bold bright_yellow on grey23",
    "success": "bold bright_green",
    "warning": "bold bright_yellow",
    "danger": "bold bright_red",
})

STATUS_ICONS: dict[str, str] = {
    "review_pending": "⏳",
    "reviewing": "🔄",
    "approved": "✅",
    "objecting": "🔴",
}

console = Console(theme=COUNCIL_THEME)


# ─── Header ─────────────────────────────────────────────────


def show_banner() -> None:
    """Display the AI Council banner."""
    banner = Text()
    banner.append("🏛️  AI COUNCIL", style="bold bright_white")
    console.print(Panel(banner, border_style="bright_cyan", padding=(0, 2)))


def show_idea(premise: str) -> None:
    """Display the idea being evaluated."""
    console.print(
        Panel(
            f"[bold]{escape(premise)}[/]",
            title="[bright_cyan]Idea[/]",
            border_style="dim cyan",
            padding=(0, 2),
        )
    )


# ─── Phase Headers ───────────────────────────────────────────


def show_phase(title: str) -> None:
    """Display a phase separator."""
    console.print()
    console.rule(f"[phase] {title} [/]", style="bright_yellow")
    console.print()


# ─── Council Table ───────────────────────────────────────────


def show_council_table(council: list[ExpertMember]) -> None:
    """Render the council composition as a styled table."""
    table = Table(
        title="[bold bright_cyan]Council Members[/]",
        box=box.ROUNDED,
        border_style="cyan",
        show_lines=True,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=3, justify="center")
    table.add_column("Role", style="bold magenta", min_width=20)
    table.add_column("System Prompt", style="white", max_width=70)

    for i, member in enumerate(council, 1):
        # Truncate long system prompts for display
        prompt_preview = member.system_prompt
        if len(prompt_preview) > 120:
            prompt_preview = prompt_preview[:117] + "..."
        table.add_row(str(i), member.role, prompt_preview)

    console.print(table)


# ─── Event Logging ───────────────────────────────────────────


def log_event(role: str, message: str, style: str = "") -> None:
    """
    Print a timestamped event line during the debate.

    Example output:
      14:32:01  Moderator      ✍️ Compiling Draft v1...
    """
    now = datetime.now().strftime("%H:%M:%S")
    role_display = f"{role:<18}"

    if role == "Moderator":
        role_style = "moderator"
    else:
        role_style = "expert"

    styled = style or "white"
    console.print(
        f"  [dim]{now}[/]  [{role_style}]{escape(role_display)}[/]  [{styled}]{escape(message)}[/]"
    )
    logger.info("[%s] %s", role, message)


# ─── Parallel Spinners ───────────────────────────────────────


_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


@contextmanager
def parallel_spinners(
    labels: list[str],
    futures: list[Future[Any]],
    title: str = "",
    refresh_per_second: float = 10,
) -> Iterator[None]:
    """
    Context manager that shows a live per-agent spinner table.

    The Rich Live render loop runs in a background daemon thread so the
    caller's main thread can freely iterate ``as_completed()`` without any
    cooperative yield.  Each future marks itself done via a callback and the
    corresponding row flips to a checkmark (✅) immediately.

    Usage::

        futures = [executor.submit(fn, arg) for arg in args]
        with parallel_spinners(labels, futures, title="Gathering perspectives"):
            for fut in as_completed(futures):
                result = fut.result()   # re-raises any exception
                # ... collect result ...
    """
    done: set[int] = set()
    frame_cycle: Iterator[str] = itertools.cycle(_SPINNER_FRAMES)
    lock = threading.Lock()

    def _build_table(frame: str) -> Table:
        table = Table(
            box=box.SIMPLE,
            show_header=False,
            padding=(0, 1),
            expand=False,
        )
        table.add_column("icon", width=3, justify="center")
        table.add_column("label", style="bold magenta", min_width=22)
        table.add_column("status", style="dim white")

        for idx, label in enumerate(labels):
            with lock:
                is_done = idx in done
            if is_done:
                table.add_row("✅", label, "[dim green]done[/]")
            else:
                table.add_row(
                    f"[bold magenta]{frame}[/]",
                    label,
                    "[dim]thinking...[/]",
                )
        return table

    def _mark_done(idx: int) -> None:
        with lock:
            done.add(idx)

    # Attach a callback to each future so its row flips immediately on completion
    for i, fut in enumerate(futures):
        fut.add_done_callback(lambda _f, _i=i: _mark_done(_i))

    panel_title = f"[bold bright_cyan]{escape(title)}[/]" if title else ""
    stop_event = threading.Event()

    def _render_loop() -> None:
        with Live(
            console=console,
            refresh_per_second=refresh_per_second,
            transient=True,
        ) as live:
            while not stop_event.is_set():
                frame = next(frame_cycle)
                renderable = _build_table(frame)
                if panel_title:
                    renderable = Panel(renderable, title=panel_title, border_style="dim cyan")
                live.update(renderable)
                time.sleep(1 / refresh_per_second)

            # Final render: all checkmarks before Live tears down
            renderable = _build_table("✅")
            if panel_title:
                renderable = Panel(renderable, title=panel_title, border_style="dim cyan")
            live.update(renderable)

    render_thread = threading.Thread(target=_render_loop, daemon=True)
    render_thread.start()
    try:
        yield
    finally:
        stop_event.set()
        render_thread.join()


# ─── Status Board ────────────────────────────────────────────


def show_status_board(state: CouncilState) -> None:
    """Render the current expert status board."""
    table = Table(
        box=box.ROUNDED,
        border_style="cyan",
        show_header=False,
        padding=(0, 1),
    )
    table.add_column("Icon", width=3, justify="center")
    table.add_column("Expert", min_width=20, style="bold")
    table.add_column("Status", min_width=30)

    for role, ds in state.domain_states.items():
        icon = STATUS_ICONS.get(ds.status, "❓")
        status_text = ds.status.replace("_", " ").title()

        if ds.status == "approved":
            style = "approved"
        elif ds.status == "objecting":
            style = "objecting"
            # Find the objection text
            obj = next(
                (o for o in state.objection_queue if o.raised_by == role),
                None,
            )
            if obj:
                status_text = f"Objection: {obj.objection_text[:50]}..."
        else:
            style = "pending"

        table.add_row(icon, role, Text(status_text, style=style))

    title = f"[bold bright_cyan]Review Round {state.turn_count}[/]"
    console.print(Panel(table, title=title, border_style="cyan"))


# ─── Vote Results ────────────────────────────────────────────


def show_vote_results(
    objections: list[Objection],
    vote_tallies: dict[str, int],
    winner: Objection,
) -> None:
    """Display the vote tally for objection prioritization."""
    table = Table(
        box=box.ROUNDED,
        border_style="cyan",
        show_lines=True,
        padding=(0, 1),
    )
    table.add_column("Raised By", style="bold magenta", min_width=20)
    table.add_column("Objection", min_width=50)
    table.add_column("Points", style="bold", justify="right", min_width=8)

    for obj in sorted(objections, key=lambda o: vote_tallies.get(o.id, 0), reverse=True):
        points = vote_tallies.get(obj.id, 0)
        text = obj.objection_text
        if len(text) > 60:
            text = text[:57] + "..."
        is_winner = obj.id == winner.id
        prefix = "🏆 " if is_winner else "   "
        row_style = "bold green" if is_winner else ""
        table.add_row(
            f"{prefix}{escape(obj.raised_by)}",
            escape(text),
            str(points),
            style=row_style,
        )

    console.print(Panel(table, title="[bold bright_cyan]🗳️  Objection Vote Results[/]", border_style="cyan"))


# ─── Proposal Display ───────────────────────────────────────


def show_proposal(proposal: str, version: str = "v1") -> None:
    """Display the current proposal in a panel."""
    console.print(
        Panel(
            escape(proposal),
            title=f"[bold bright_cyan]Proposal {version}[/]",
            border_style="dim cyan",
            padding=(1, 2),
        )
    )


# ─── Objection Detail ───────────────────────────────────────


def show_objection_detail(objection: Objection) -> None:
    """Display detailed info about an objection being resolved."""
    console.print(
        Panel(
            f"[bold]{escape(objection.objection_text)}[/]",
            title=f"[danger]Objection from {escape(objection.raised_by)}[/]",
            border_style="red",
            padding=(0, 2),
        )
    )


# ─── Verdict ─────────────────────────────────────────────────


def show_verdict(state: CouncilState) -> None:
    """Display the final verdict panel."""
    total_objections = len(state.resolved_objections)
    resolved = sum(1 for o in state.resolved_objections if o.status == "resolved")
    deadlocked = sum(1 for o in state.resolved_objections if o.status == "deadlocked")

    if state.global_status == "approved":
        icon = "🎉"
        title = "CONSENSUS REACHED"
        border = "bright_green"
        style = "success"
    elif state.global_status == "stalemate":
        icon = "⚠️"
        title = "STALEMATE"
        border = "bright_yellow"
        style = "warning"
    else:
        icon = "❌"
        title = "REJECTED"
        border = "bright_red"
        style = "danger"

    body = (
        f"[{style}]{icon} {title}[/]\n\n"
        f"  Turns: {state.turn_count}  │  "
        f"Objections: {total_objections}  │  "
        f"Resolved: {resolved}  │  "
        f"Deadlocked: {deadlocked}"
    )

    console.print()
    console.print(Panel(body, border_style=border, padding=(1, 3)))


def show_report_path(path: str) -> None:
    """Display where the report was saved."""
    console.print(f"\n  📄 Report saved to: [bold bright_cyan]{path}[/]\n")


# ─── Stalemate Prompt ────────────────────────────────────────


def show_stalemate_info(state: CouncilState) -> None:
    """Display stalemate information before asking the user what to do."""
    console.print()
    console.print(
        Panel(
            f"[warning]⚠️  The council has not reached consensus after "
            f"{state.turn_count} turns.[/]\n\n"
            f"Remaining objections in queue: {len(state.objection_queue)}",
            title="[warning]Stalemate Detected[/]",
            border_style="bright_yellow",
            padding=(1, 2),
        )
    )


# ─── Error Display ───────────────────────────────────────────


def show_error(message: str) -> None:
    """Display an error message."""
    console.print(f"\n  [danger]✖ {escape(message)}[/]\n")


def show_success(message: str) -> None:
    """Display a success message."""
    console.print(f"\n  [success]✔ {escape(message)}[/]\n")
