"""
Rich terminal front-end.

`RichSink` implements `EventSink`: it renders engine events to the terminal.
The rest of this module holds static widgets (banner, tables, verdict) used
by the CLI outside the engine loop.
"""

from __future__ import annotations

import itertools
import threading
import time
from datetime import datetime

from rich import box
from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from ..events import (
    DebateFinished,
    DraftReady,
    Event,
    Message,
    ObjectionResolved,
    ObjectionSelected,
    ParallelFinished,
    ParallelItemDone,
    ParallelStarted,
    PhaseStarted,
    ReviewRoundFinished,
    VoteCompleted,
)
from ..models import CouncilState, ExpertMember, Objection
from ..store import SessionSummary

THEME = Theme(
    {
        "moderator": "bold cyan",
        "expert": "bold magenta",
        "success": "bold bright_green",
        "warning": "bold bright_yellow",
        "error": "bold bright_red",
        "dim": "dim",
        "info": "white",
        "phase": "bold bright_yellow on grey23",
    }
)

STATUS_ICONS = {"review_pending": "⏳", "reviewing": "🔄", "approved": "✅", "objecting": "🔴"}
PHASE_TITLES = {
    "drafting": "Phase 2: Generating First Draft",
    "debating": "Phase 3: Council Debate",
}
_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def make_console() -> Console:
    return Console(theme=THEME)


# ─── Static widgets ─────────────────────────────────────────


def banner(con: Console) -> None:
    con.print(
        Panel(
            Text("🏛️  AI COUNCIL", style="bold bright_white"),
            border_style="bright_cyan",
            padding=(0, 2),
        )
    )


def idea(con: Console, premise: str) -> None:
    con.print(
        Panel(
            f"[bold]{escape(premise)}[/]",
            title="[bright_cyan]Idea[/]",
            border_style="dim cyan",
            padding=(0, 2),
        )
    )


def phase(con: Console, title: str) -> None:
    con.print()
    con.rule(f"[phase] {title} [/]", style="bright_yellow")
    con.print()


def council_table(con: Console, council: list[ExpertMember]) -> None:
    t = Table(
        title="[bold bright_cyan]Council Members[/]",
        box=box.ROUNDED,
        border_style="cyan",
        show_lines=True,
    )
    t.add_column("#", style="dim", width=3, justify="center")
    t.add_column("Role", style="bold magenta", min_width=20)
    t.add_column("System Prompt", style="white", max_width=70)
    t.add_column("Model", style="dim", max_width=30)
    for i, m in enumerate(council, 1):
        prompt = m.system_prompt if len(m.system_prompt) <= 120 else m.system_prompt[:117] + "..."
        t.add_row(str(i), m.role, prompt, m.model or "[dim]default[/]")
    con.print(t)


def sessions_table(con: Console, rows: list[SessionSummary]) -> None:
    styles = {
        "intake": "[dim yellow]intake[/]",
        "drafting": "[yellow]drafting[/]",
        "debating": "[cyan]debating[/]",
        "approved": "[green]✅ approved[/]",
        "rejected": "[red]❌ rejected[/]",
        "stalemate": "[yellow]⚠️ stalemate[/]",
    }
    t = Table(title="[bold bright_cyan]Council Sessions[/]", box=box.ROUNDED, border_style="cyan")
    t.add_column("Session", style="dim")
    t.add_column("Premise", max_width=50)
    t.add_column("Status", justify="center")
    t.add_column("Turns", justify="center")
    t.add_column("Council", justify="center")
    t.add_column("Updated", style="dim")
    for r in rows:
        premise = r.premise if len(r.premise) <= 80 else r.premise[:77] + "..."
        t.add_row(
            r.idea_id[:8],
            escape(premise),
            styles.get(r.status, r.status),
            f"{r.turn_count}/{r.max_turns}",
            str(r.council_size),
            r.updated_at.strftime("%Y-%m-%d %H:%M"),
        )
    con.print(t)


def proposal(con: Console, text: str, version: str) -> None:
    con.print(
        Panel(
            escape(text),
            title=f"[bold bright_cyan]Proposal {version}[/]",
            border_style="dim cyan",
            padding=(1, 2),
        )
    )


def status_board(con: Console, state: CouncilState) -> None:
    t = Table(box=box.ROUNDED, border_style="cyan", show_header=False)
    t.add_column("Icon", width=3, justify="center")
    t.add_column("Expert", min_width=20, style="bold")
    t.add_column("Status", min_width=30)
    for role, ds in state.domain_states.items():
        label = ds.status.replace("_", " ").title()
        style = {"approved": "success", "objecting": "error"}.get(ds.status, "dim")
        if ds.status == "objecting":
            o = next((o for o in state.objection_queue if o.raised_by == role), None)
            if o:
                label = f"Objection: {o.objection_text[:50]}..."
        t.add_row(STATUS_ICONS.get(ds.status, "❓"), role, Text(label, style=style))
    con.print(
        Panel(t, title=f"[bold bright_cyan]Review Round {state.turn_count}[/]", border_style="cyan")
    )


def objection_detail(con: Console, o: Objection) -> None:
    con.print(
        Panel(
            f"[bold]{escape(o.objection_text)}[/]",
            title=f"[error]Objection from {escape(o.raised_by)}[/]",
            border_style="red",
            padding=(0, 2),
        )
    )


def vote_results(
    con: Console, objections: tuple[Objection, ...], tallies: dict[str, int], winner: Objection
) -> None:
    t = Table(box=box.ROUNDED, border_style="cyan", show_lines=True)
    t.add_column("Raised By", style="bold magenta", min_width=20)
    t.add_column("Objection", min_width=50)
    t.add_column("Points", justify="right", min_width=8)
    for o in sorted(objections, key=lambda o: tallies.get(o.id, 0), reverse=True):
        text = o.objection_text if len(o.objection_text) <= 60 else o.objection_text[:57] + "..."
        win = o.id == winner.id
        t.add_row(
            ("🏆 " if win else "   ") + escape(o.raised_by),
            escape(text),
            str(tallies.get(o.id, 0)),
            style="bold green" if win else "",
        )
    con.print(Panel(t, title="[bold bright_cyan]🗳️  Objection Vote[/]", border_style="cyan"))


def proposal_diff(con: Console, diff: str) -> None:
    con.print(
        Panel(
            Syntax(diff, "diff", theme="ansi_dark", background_color="default"),
            title="[bold bright_cyan]Proposal Changes[/]",
            border_style="dim cyan",
            padding=(1, 2),
        )
    )


def verdict(con: Console, state: CouncilState) -> None:
    st = state.stats()
    icon, title, border = {
        "approved": ("🎉", "CONSENSUS REACHED", "bright_green"),
        "stalemate": ("⚠️", "STALEMATE", "bright_yellow"),
        "rejected": ("❌", "REJECTED", "bright_red"),
    }.get(state.global_status, ("❓", state.global_status.upper(), "white"))
    body = (
        f"[bold]{icon} {title}[/]\n\n"
        f"  Rounds: {st['rounds']}  │  Objections: {st['objections']}  │  "
        f"Resolved: {st['resolved']}  │  Deadlocked: {st['deadlocked']}"
    )
    con.print()
    con.print(Panel(body, border_style=border, padding=(1, 3)))


def stalemate_info(con: Console, state: CouncilState) -> None:
    con.print(
        Panel(
            f"[warning]⚠️  No consensus after {state.turn_count} rounds.[/]\n\n"
            f"Open objections: {len(state.objection_queue)}",
            title="[warning]Stalemate[/]",
            border_style="bright_yellow",
            padding=(1, 2),
        )
    )


def error(con: Console, msg: str) -> None:
    con.print(f"\n  [error]✖ {escape(msg)}[/]\n")


def success(con: Console, msg: str) -> None:
    con.print(f"\n  [success]✔ {escape(msg)}[/]\n")


def paths(con: Console, items: list[tuple[str, str]]) -> None:
    con.print()
    for label, p in items:
        con.print(f"  {label}: [bold bright_cyan]{p}[/]")
    con.print()


# ─── Event sink ─────────────────────────────────────────────


class _SpinnerBatch:
    """Live per-item spinner table driven from a daemon thread."""

    def __init__(self, con: Console, title: str, labels: tuple[str, ...]) -> None:
        self._con = con
        self._title = title
        self._labels = labels
        self._done: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def mark(self, label: str) -> None:
        with self._lock:
            self._done.add(label)

    def finish(self) -> None:
        self._stop.set()
        self._thread.join()

    def _table(self, frame: str) -> Panel:
        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        t.add_column("icon", width=3, justify="center")
        t.add_column("label", style="bold magenta", min_width=22)
        t.add_column("status", style="dim")
        with self._lock:
            done = set(self._done)
        for label in self._labels:
            if label in done:
                t.add_row("✅", escape(label), "[dim green]done[/]")
            else:
                t.add_row(f"[bold magenta]{frame}[/]", escape(label), "[dim]thinking...[/]")
        return Panel(
            t, title=f"[bold bright_cyan]{escape(self._title)}[/]", border_style="dim cyan"
        )

    def _loop(self) -> None:
        frames = itertools.cycle(_SPINNER)
        with Live(console=self._con, refresh_per_second=10, transient=True) as live:
            while not self._stop.is_set():
                live.update(self._table(next(frames)))
                time.sleep(0.1)
            live.update(self._table("✅"))


class RichSink:
    """Render engine events to a Rich console."""

    def __init__(self, con: Console | None = None, *, show_proposal: bool = True) -> None:
        self.con = con or make_console()
        self._show_proposal = show_proposal
        self._batches: dict[str, _SpinnerBatch] = {}

    def emit(self, event: Event) -> None:  # noqa: C901 — flat dispatch table
        match event:
            case Message(actor=actor, text=text, level=level):
                self._line(actor, text, level)
            case PhaseStarted(phase=p):
                phase(self.con, PHASE_TITLES.get(p, p.title()))
            case ParallelStarted(title=title, labels=labels, batch_id=bid):
                self._batches[bid] = _SpinnerBatch(self.con, title, labels)
            case ParallelItemDone(batch_id=bid, label=label):
                if bid in self._batches:
                    self._batches[bid].mark(label)
            case ParallelFinished(batch_id=bid):
                if batch := self._batches.pop(bid, None):
                    batch.finish()
            case DraftReady(state=state, points_of_debate=points):
                if points:
                    self._line(
                        "Moderator", f"{len(points)} open point(s) of debate flagged:", "warning"
                    )
                    for pt in points:
                        self._line("Moderator", f"  • {pt}", "warning")
                if self._show_proposal:
                    proposal(self.con, state.current_proposal, "v1")
            case ReviewRoundFinished(state=state):
                status_board(self.con, state)
            case VoteCompleted(objections=objs, tallies=tallies, winner=winner):
                vote_results(self.con, objs, tallies, winner)
            case ObjectionSelected(objection=o):
                objection_detail(self.con, o)
            case ObjectionResolved(diff=diff):
                if diff:
                    proposal_diff(self.con, diff)
            case DebateFinished(state=state):
                if state.global_status == "stalemate":
                    stalemate_info(self.con, state)
            case _:
                pass

    def _line(self, actor: str, text: str, level: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        actor_style = "moderator" if actor == "Moderator" else "expert"
        self.con.print(
            f"  [dim]{now}[/]  [{actor_style}]{escape(f'{actor:<18}')}[/]  [{level}]{escape(text)}[/]"
        )
