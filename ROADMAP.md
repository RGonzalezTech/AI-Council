# ROADMAP

Planned features and future directions for AI Council.

---

## External Data Access

Each debate agent should be able to back up its claims with external evidence.
The original file-reference system (`--file` at intake, LLM-summarized into
`context_summary`) was removed in the `refactor/solid` branch because it was
out of scope — the focus is on the core debate engine and protocol contracts.

The replacement should be more powerful:

- **Per-agent evidence access**: agents can search the web or reference provided
  documents *during debate*, not just at intake
- **Web search**: agents query live sources to support or challenge claims
- **File/dataset access**: agents can cite specific data, code, or documents
- **Source attribution**: evidence comes with citations the moderator can verify
- **Pluggable backends**: web search API, local RAG, vector store — protocol,
  not hard-wired implementation

The `context_summary` field on `CouncilState` and the `context_block` plumbing
through `CouncilLLM` remain as inert hooks for this feature.

---

## Additional Ideas

- **Streaming events**: real-time WebSocket/SSE event stream for UI frontends
- **Custom expert personas**: user-defined expert profiles beyond generated ones
- **Multi-turn evidence gathering**: agents can request more data mid-debate
- **Debate transcripts**: structured timeline export (JSON/HTML) beyond Markdown
- **Plugin system**: third-party prompt packs, domain-specific expert libraries