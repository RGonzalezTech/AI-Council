# Contributing

Thanks for your interest. This project is small enough that a good PR is usually the fastest conversation.

## Setup

```bash
git clone https://github.com/RGonzalezTech/AI-Council.git
cd AI-Council
python -m venv .venv && source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Before opening a PR

```bash
ruff check . && ruff format .
mypy aicouncil
pytest
```

CI runs the same three on Linux and Windows across Python 3.11–3.13.

## Ground rules

- **The engine stays pure.** `aicouncil/engine.py` must not import `rich`, `typer`, `InquirerPy`, or touch the filesystem. If you need output, emit an event. If you need persistence, go through `SessionStore`.
- **Every LLM call has a schema.** Add the Pydantic model to `schemas.py`, the prompt to `llm/prompts.py`, and the typed call to `llm/calls.py`. Give it a `FakeGateway` responder in `tests/conftest.py`.
- **Tests run offline.** Nothing in `tests/` may make a network call. Use `FakeGateway` and `MemorySessionStore`.
- **New settings go in `settings.py`** with a default and a description. Document them in the README table.
- **Prompt changes are behavior changes.** Say why in the PR and, ideally, include a before/after example from a real session.

## Adding an extension

| I want to… | Implement | Register |
|---|---|---|
| Support a new provider quirk | `LLMGateway` | pass `gateway=` to `Council` |
| Render to a new front-end | `EventSink` | pass `sink=` to `Council` |
| Store sessions elsewhere | `SessionStore` | pass `store=` to `Council` |
| Produce a new report format | `ReportRenderer` | pass `renderer=` to `Council` |
| Change what an agent is told | `Prompt` | `PromptLibrary(overrides={...})` |

## Reporting bugs

Include the `council.log` from the session directory (it contains prompts and model names but no API keys) and the command you ran.
