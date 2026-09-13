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

DEFAULT_MODEL = "openrouter/deepseek/deepseek-v4-pro"


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
        default=DEFAULT_MODEL,
        description="Default LiteLLM model string for experts.",
    )
    moderator_model: str | None = Field(
        default=None,
        description="Model for Moderator calls. Falls back to `model` when unset.",
    )
    json_mode_providers: tuple[str, ...] = Field(
        default=("openrouter", "gemini", "deepseek", "google"),
        description=(
            "Providers that need Instructor JSON mode instead of tool calling. "
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

    @property
    def effective_moderator_model(self) -> str:
        return self.moderator_model or self.model
