# AI Council

Multi-agent LLM debate for stress-testing ideas. Pitch a question; a council of domain experts argues about it until they converge on a proposal — or honestly report where they couldn't.

```bash
council init "What's the right architecture for a self-hosted multiplayer game server?"
```

## Why

One model gives you one perspective. Blind spots surface only when viewpoints collide: the security lead notices what the product manager missed, the economist flags what the engineer never considered. AI Council runs that collision as a structured, auditable process:

1. **Assemble** — an LLM proposes domain-specific experts for *this* question; you can edit the roster.
2. **Perspectives** — each expert gives an independent take before seeing anyone else's (no groupthink).
3. **Draft** — a Moderator synthesizes those into a first proposal, flagging genuine disagreements as open debate points.
4. **Debate** — every expert reviews. Objections are voted on, triaged to the right experts, resolved through proposed solutions, and the proposal is rewritten. A decision log stops the council from relitigating what it already settled.
5. **Report** — an executive summary plus a full transcript: every objection, solution, diff, and vote.

## Install

Requires Python 3.11+.

```bash
pip install aicouncil
# or from source
git clone https://github.com/RGonzalezTech/AI-Council.git && cd AI-Council && pip install -e .
```

Copy `.env.example` to `.env` and add one provider key (OpenRouter, OpenAI, Anthropic, Gemini, or [anything LiteLLM supports](https://docs.litellm.ai/docs/providers)).

## Usage

```bash
council init "Should we migrate from REST to GraphQL?"
council init "Refactor plan?" --file service.py --file ARCHITECTURE.md   # with reference material
council init "..." --model gemini/gemini-2.5-pro --moderator-model gemini/gemini-2.5-flash
council init "..." --size 7 --max-turns 20 --yes                         # bigger council, skip roster editing

council list                 # saved sessions
council resume [id]          # continue a crashed or stalemated session
council show <id>            # current state
council report <id>          # regenerate reports
```

Sessions are stored under `~/.aicouncil/sessions/<id>/` (override with `--sessions-dir` or `COUNCIL_SESSIONS_DIR`). Each contains `final_report.md`, `debate_log.md`, the full `state.json`, and human-readable projections of every artifact.

### Configuration

Everything is a `COUNCIL_*` environment variable or `.env` entry; CLI flags override.

| Setting | Default | Purpose |
|---|---|---|
| `COUNCIL_MODEL` | `openrouter/deepseek/deepseek-v4-pro` | Expert model — any [LiteLLM model string](https://docs.litellm.ai/docs/providers) |
| `COUNCIL_MODERATOR_MODEL` | *(same as model)* | Moderator model; use something cheaper/faster |
| `COUNCIL_COUNCIL_SIZE` | `5` | Experts to generate |
| `COUNCIL_MAX_TURNS` | `15` | Review rounds before stalemate |
| `COUNCIL_MAX_RESOLUTION_TURNS` | `5` | Attempts to satisfy an objector before deadlock |
| `COUNCIL_MAX_WORKERS` | `8` | Concurrent LLM calls |
| `COUNCIL_SESSIONS_DIR` | `~/.aicouncil/sessions` | Storage location |

Per-expert model overrides are available in the roster editor, so you can run a cheap model for routine reviewers and an expensive one for the devil's advocate.

## Use it as a library

The engine has no dependency on the terminal. Every seam is a protocol you can replace.

```python
from aicouncil import Council, Settings

council = Council(Settings(model="openrouter/anthropic/claude-sonnet-4-5"))
state = council.new_session("Should we open-source our billing service?")
state.council = council.intake.generate_council(state)
state = council.run(state)

print(state.proposal_executive_summary)
for doc in council.render_reports(state):
    print(doc.filename, len(doc.content))
```

Swap any piece:

```python
from aicouncil import Council, RecordingSink, MemorySessionStore, PromptLibrary, Prompt

council = Council(
    store=MemorySessionStore(),  # SessionStore: anything that can save/load/list
    sink=RecordingSink(),  # EventSink: receive every engine event
    prompts=PromptLibrary(
        overrides={  # replace any prompt without touching engine code
            "expert_review": Prompt(system="...", user="..."),
        }
    ),
)
```

| Extension point | Protocol | Default | Notes |
|---|---|---|---|
| Model provider | `LLMGateway` | `InstructorGateway` (LiteLLM + Instructor) | `FakeGateway` ships for tests |
| Prompts | `PromptLibrary` | `DEFAULT_PROMPTS` | Override by name |
| Persistence | `SessionStore` | `FileSessionStore` | `MemorySessionStore` for embedding/tests |
| Output | `EventSink` | `NullSink` (CLI uses `RichSink`) | `RecordingSink`, `MultiSink` included |
| Reports | `ReportRenderer` | `MarkdownRenderer` | Return any number of documents |

## Architecture

```
aicouncil/
├── engine.py        DebateEngine — the state machine. Depends only on protocols below.
├── events.py        Typed events + EventSink protocol
├── models.py        CouncilState and friends (pure data)
├── schemas.py       Pydantic response contracts enforced on every LLM call
├── settings.py      pydantic-settings config
├── intake.py        Pre-debate: file loading, council generation
├── app.py           Council façade / composition root
├── cli.py           Typer commands
├── llm/             LLMGateway protocol, Instructor impl, FakeGateway, prompts, typed calls
├── store/           SessionStore protocol, filesystem + memory impls
├── reports/         ReportRenderer protocol, Markdown impl
└── ui/              Rich event sink + interactive prompts
```

```
intake ─► drafting ─► debating ─► approved
                          │  ▲
                          ▼  │ extend
                       stalemate ─► rejected
```

Design notes that matter if you're extending it:

- **The engine emits, it doesn't print.** All rendering happens in an `EventSink`. Run it headless, in a server, or in tests with zero changes.
- **Every LLM response is a validated Pydantic object.** Instructor retries malformed output; the engine never parses JSON.
- **State is checkpointed after every mutation.** `council resume` continues from the last one; the resumed run re-requests only what's missing.
- **One objection per round.** Multiple objections trigger a 100-point vote; the winner is resolved, the proposal rewritten, and everyone re-reviews. Resolving A often dissolves B.
- **The decision log is institutional memory.** It's injected into every review prompt so the council can't oscillate.

## Development

```bash
pip install -e ".[dev]"
pytest            # unit tests run against FakeGateway — no API key needed
ruff check . && ruff format --check .
mypy aicouncil
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [ROADMAP.md](ROADMAP.md).

## License

MIT — see [LICENSE](LICENSE).
