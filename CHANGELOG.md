# Changelog

## 0.2.0 — Unreleased

Ground-up restructure for open-source release. **Not backward compatible** with 0.1 session directories.

### Added
- `Council` façade and public Python API; the engine runs headless without the CLI.
- Protocols for every seam: `LLMGateway`, `EventSink`, `SessionStore`, `ReportRenderer`, `PromptLibrary`.
- `FakeGateway`, `MemorySessionStore`, `RecordingSink` for offline testing.
- `pydantic-settings` configuration (`COUNCIL_*` env vars / `.env`), including `COUNCIL_MODERATOR_MODEL`, `COUNCIL_COUNCIL_SIZE`, `COUNCIL_SESSIONS_DIR`.
- CLI: `--moderator-model`, `--size`, `--yes`, `--sessions-dir`, `--version`, `council models`; session ids accept unique prefixes.
- Stalemate handling in `init` (previously only in `resume`); "leave as stalemate" option.
- Objections keep their original text; narrowed concerns are recorded as `revisions`.
- Proposed solutions record which resolution attempt produced them.
- Test suite (offline) and CI on Linux/Windows, Python 3.11–3.13.

### Changed
- Package renamed `council` → `aicouncil`; CLI command remains `council`.
- Sessions default to `~/.aicouncil/sessions` instead of `./sessions`.
- `state.json` is now the complete, authoritative checkpoint; other files are projections.
- Per-expert `model` is `None` by default and falls back to the session model (previously always populated).
- Gemini alias uses the `gemini/` LiteLLM prefix (was `google/`).

### Fixed
- `COUNCIL_MODEL` in `.env` was read before `load_dotenv()` ran and had no effect.
- Provider-specific JSON mode is chosen from the model's provider prefix, not substring matching.
- Provider errors and Ctrl-C now print a resume hint instead of a bare traceback.
- Vote ties resolve deterministically (earliest objection wins).

## 0.1.0

Initial vibe-coded release.
