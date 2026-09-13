"""
Runtime configuration.

All tunables live here and are loaded, in order of precedence, from:
  1. Explicit constructor arguments (e.g. CLI flags)
  2. Environment variables prefixed with ``COUNCIL_``
  3. A ``.env`` file in the working directory
  4. Defaults below
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODEL_ALIASES: dict[str, str] = {
    "deepseek": "openrouter/deepseek/deepseek-v4-pro",
    "deepseek-flash": "openrouter/deepseek/deepseek-v4-flash",
    "deepseek-pro": "openrouter/deepseek/deepseek-v4-pro",
    "gemini-flash": "gemini/gemini-2.5-flash",
    "gemini-pro": "gemini/gemini-2.5-pro",
    "claude-sonnet": "anthropic/claude-sonnet-4-5",
    "gpt-5": "openai/gpt-5",
}


class Settings(BaseSettings):
    """Process-wide configuration for the council."""

    model_config = SettingsConfigDict(
        env_prefix="COUNCIL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Models ───────────────────────────────────────────────
    model: str = Field(
        default="deepseek",
        description="Default model for experts (alias or LiteLLM string).",
    )
    moderator_model: str | None = Field(
        default=None,
        description="Model for Moderator calls. Falls back to `model` when unset.",
    )
    model_aliases: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_MODEL_ALIASES),
        description="Friendly-name → LiteLLM model string map.",
    )
    json_mode_prefixes: tuple[str, ...] = Field(
        default=("openrouter", "gemini", "deepseek", "google"),
        description=(
            "Provider prefixes that need Instructor JSON mode instead of tool calling. "
            "Matched against the segment before the first '/' in the model string."
        ),
    )
    max_retries: int = Field(default=3, ge=0, description="Instructor retries per call.")

    # ── Debate ───────────────────────────────────────────────
    council_size: int = Field(default=5, ge=1, le=12)
    max_turns: int = Field(default=15, ge=1)
    max_resolution_turns: int = Field(default=5, ge=1)
    max_workers: int = Field(default=8, ge=1, description="Upper bound on concurrent LLM calls.")

    # ── Storage ──────────────────────────────────────────────
    sessions_dir: Path = Field(
        default_factory=lambda: Path.home() / ".aicouncil" / "sessions",
        description="Where session artifacts are written.",
    )

    # ── Reference files ──────────────────────────────────────
    max_file_size: int = Field(default=250 * 1024, description="Per-file cap in bytes.")
    max_total_file_size: int = Field(default=1024 * 1024, description="Cumulative cap in bytes.")

    # ── Helpers ──────────────────────────────────────────────

    def resolve_model(self, name: str | None) -> str:
        """Expand an alias to a full LiteLLM model string; pass through anything else."""
        if not name:
            name = self.model
        if "/" in name:
            return name
        return self.model_aliases.get(name.lower(), name)

    @property
    def resolved_model(self) -> str:
        return self.resolve_model(self.model)

    @property
    def resolved_moderator_model(self) -> str:
        return self.resolve_model(self.moderator_model or self.model)
