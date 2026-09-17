"""AI Council — multi-agent LLM debate engine for stress-testing ideas."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aicouncil")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0.0.0+dev"

from .app import Council
from .engine import DebateEngine
from .events import Event, EventSink, MultiSink, NullSink, RecordingSink
from .llm import CouncilLLM, FakeGateway, InstructorGateway, LLMGateway, Prompt, PromptLibrary
from .models import CouncilState, ExpertMember, Objection
from .reports import MarkdownRenderer, ReportRenderer
from .settings import Settings
from .store import FileSessionStore, MemorySessionStore, SessionStore

__all__ = [
    "Council",
    "CouncilLLM",
    "CouncilState",
    "DebateEngine",
    "Event",
    "EventSink",
    "ExpertMember",
    "FakeGateway",
    "FileSessionStore",
    "InstructorGateway",
    "LLMGateway",
    "MarkdownRenderer",
    "MemorySessionStore",
    "MultiSink",
    "NullSink",
    "Objection",
    "Prompt",
    "PromptLibrary",
    "RecordingSink",
    "ReportRenderer",
    "SessionStore",
    "Settings",
    "__version__",
]
