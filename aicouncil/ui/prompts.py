"""Interactive prompts (InquirerPy). Kept separate so the CLI stays declarative."""

from __future__ import annotations

from collections.abc import Callable

from InquirerPy import inquirer
from rich.console import Console

from ..models import ExpertMember
from ..store import SessionSummary
from . import rich_ui as ui


def edit_council(
    con: Console,
    council: list[ExpertMember],
    *,
    generate_member: Callable[[str], ExpertMember],
    model_aliases: dict[str, str],
) -> list[ExpertMember]:
    """Interactive accept/edit/remove/add loop. Returns the final roster (≥1 member)."""
    while True:
        ui.council_table(con, council)
        con.print()
        action = inquirer.select(
            message="What would you like to do?",
            choices=[
                {"name": "✅ Accept council and begin debate", "value": "accept"},
                {"name": "✏️  Edit a member", "value": "edit"},
                {"name": "🗑️  Remove a member", "value": "remove"},
                {"name": "➕ Add a member", "value": "add"},
            ],
            default="accept",
        ).execute()

        if action == "accept":
            if council:
                return council
            ui.error(con, "Council must have at least one member.")
        elif action == "edit" and council:
            idx = _pick_member(council, "Select a member to edit:")
            council[idx] = _edit_member(con, council[idx], model_aliases)
            ui.success(con, f"Updated: {council[idx].role}")
        elif action == "remove" and council:
            idx = _pick_member(council, "Select a member to remove:")
            removed = council.pop(idx)
            ui.success(con, f"Removed: {removed.role}")
        elif action == "add":
            intent = (
                inquirer.text(
                    message="Describe the expert you want (e.g. 'a paranoid security auditor'):"
                )
                .execute()
                .strip()
            )
            if not intent:
                ui.error(con, "A description is required.")
                continue
            with con.status("[bold cyan]Generating member...[/]"):
                member = generate_member(intent)
            council.append(member)
            ui.success(con, f"Added: {member.role}")
        else:
            ui.error(con, "No members to act on.")


def _pick_member(council: list[ExpertMember], message: str) -> int:
    return inquirer.select(
        message=message,
        choices=[{"name": m.role, "value": i} for i, m in enumerate(council)],
    ).execute()


def _edit_member(con: Console, m: ExpertMember, aliases: dict[str, str]) -> ExpertMember:
    role = inquirer.text(message="Role:", default=m.role).execute().strip() or m.role
    con.print(f"\n  [dim]Current system prompt:[/] {m.system_prompt}\n")
    prompt = (
        inquirer.text(message="System prompt:", default=m.system_prompt).execute().strip()
        or m.system_prompt
    )
    choices = [{"name": "Session default", "value": ""}]
    choices += [{"name": f"{k}  ({v})", "value": v} for k, v in aliases.items()]
    choices += [{"name": "Other (type a LiteLLM model string)", "value": "__other__"}]
    model = inquirer.select(
        message="Model override:", choices=choices, default=m.model or ""
    ).execute()
    if model == "__other__":
        model = inquirer.text(message="Model string:", default=m.model or "").execute().strip()
    return ExpertMember(role=role, system_prompt=prompt, model=model or None)


def stalemate_action() -> str:
    return inquirer.select(
        message="How would you like to proceed?",
        choices=[
            {"name": "🔄 Extend debate (+10 rounds)", "value": "extend"},
            {"name": "✅ Accept the current proposal", "value": "approve"},
            {"name": "❌ Reject and close the session", "value": "reject"},
            {"name": "⏸️  Leave it as a stalemate for now", "value": "leave"},
        ],
    ).execute()


def pick_session(rows: list[SessionSummary], message: str) -> str | None:
    if not rows:
        return None
    return inquirer.select(
        message=message,
        choices=[
            {"name": f"[{r.status}] {r.premise[:50]} ({r.idea_id[:8]})", "value": r.idea_id}
            for r in rows
        ],
    ).execute()
