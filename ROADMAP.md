# Roadmap

Things worth building, roughly in order of value. Open an issue before starting a large one so we don't collide.

## Next

- **Council presets** — save a roster (roles, prompts, per-expert models) to YAML and reuse it: `council preset save <name>`, `council init --preset <name>`. Ship a few built-ins (`startup`, `security-review`, `research`). The `IntakeService` seam already exists; this is mostly CLI and a small file format.
- **Mid-debate intervention** — let the user inject a constraint ("also consider GDPR") between rounds. Model it as a decision-log entry authored by "User" so it flows through existing prompts.
- **Rejection by the council** — today only the user can reject. Allow a deadlocked objector to formally veto when the objection is fundamental, ending the session as `rejected` rather than continuing.

## Later

- **Cost tracking** — LiteLLM exposes token usage; surface per-session cost in the report and a running total in the CLI.
- **JSON / HTML report renderers** — the `ReportRenderer` protocol makes these additive.
- **Streaming sink** — a WebSocket `EventSink` for a web front-end.
- **Session migration tooling** — if the on-disk format changes post-1.0, provide `council migrate`.

## Not planned

- LLM-driven routing of the state machine. The rules are deterministic; keep them in Python.
- Resolving multiple objections in one round. One-at-a-time is a deliberate simplification.
