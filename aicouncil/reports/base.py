"""Report rendering protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import CouncilState


@dataclass(frozen=True, slots=True)
class RenderedReport:
    filename: str
    content: str


class ReportRenderer(Protocol):
    """Turns a finished `CouncilState` into one or more documents."""

    def render(self, state: CouncilState) -> list[RenderedReport]: ...
