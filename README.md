# AI Council

Multi-agent LLM debate CLI. Pitch an idea, get it torn apart and rebuilt by a panel of AI experts.

```
council init "What is the best architecture for a self-hosted multiplayer game server?"
```

## What it does

1. Assembles a council of 5 domain-specific AI experts
2. Each expert gives an independent perspective (no groupthink)
3. A Moderator synthesizes them into a proposal
4. Debate loop: experts review, object, propose solutions, vote — until consensus or stalemate
5. Outputs a battle-tested proposal + full audit trail

## ⚠️ Disclaimer

**This is a vibe-coded personal tool. I built it in ~44 minutes for my own use and moved on.** Not every line has been manually reviewed. It probably has bugs. It might eat your API credits. It is not production-critical, not polished, and not something I'm actively maintaining.

Use it as-is. If it breaks, you get to keep both pieces. If it's useful, cool. If not, also cool.

PRs are welcome but don't expect fast reviews. I've got other projects.

## Install

```bash
git clone https://github.com/RGonzalezTech/council.git
cd council
pip install -e .
```

## Setup

Copy `.env.example` to `.env` and add at least one API key:

```bash
cp .env.example .env
```

Supported providers (via [LiteLLM](https://docs.litellm.ai/docs/providers)): OpenAI, Anthropic, Google Gemini, OpenRouter, and 100+ others.

### Choosing a model

Set your default model in `.env`:

```bash
COUNCIL_MODEL=deepseek          # DeepSeek V4 Pro via OpenRouter (default)
COUNCIL_MODEL=deepseek-flash    # Cheaper/faster DeepSeek V4 Flash
COUNCIL_MODEL=gemini-pro        # Google Gemini 2.5 Pro
```

Or override per-run with `--model`:

```bash
council init "What is the best database indexing strategy for high-write loads?" --model gemini-flash
council init "What is the best way to handle distributed transactions in microservices?" --model "openrouter/anthropic/claude-sonnet-4"
```

The aliases (`deepseek`, `gemini-pro`, etc.) are defined in `council/config.py`. You can pass any raw [LiteLLM model string](https://docs.litellm.ai/docs/providers) directly — it'll work.

## Usage

```bash
# Start a new council session
council init "What is the best way to implement token-based auth?"

# With reference files (code, docs, specs)
council init "What is the best way to refactor this service?" --file service.py --file ARCHITECTURE.md

# Use a specific model
council init "What is the best design for a sliding-window rate limiter?" --model gemini-pro

# Resume a crashed/stalemate session
council resume

# List all sessions
council list

# Show session state
council show <session-id>

# Regenerate the Markdown report
council report <session-id>
```

## Output

Each session saves to `sessions/<uuid>/`:

- `final_report.md` — Executive summary with key decisions and full proposal
- `debate_log.md` — Complete transcript: every objection, solution, diff, and vote
- `council.log` — Debug log

## Tech stack

Typer · Rich · InquirerPy · Pydantic v2 · LiteLLM · Instructor

## License

MIT — do whatever you want. See [LICENSE](LICENSE).