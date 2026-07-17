This repository contains three security-sensitive stdio MCP servers.

- Use the stable MCP Python SDK v1 line (`mcp>=1.28.1,<2`).
- Never commit API keys, tokens, local session databases, or generated MCP configs containing secrets.
- Keep Codex, Claude, and Grok as independent process entry points with shared infrastructure only.
- Pass prompts through stdin, never through a shell command string.
- Default Codex and Claude to read-only execution/tool access.
- Grok configuration comes from process environment; tool results and diagnostics must never reveal API keys.
- Run `ruff check .` and `pytest` in the `mcpserver` Conda environment before committing.

SDK references:
- https://github.com/modelcontextprotocol/python-sdk/tree/v1.x
- https://modelcontextprotocol.io/docs/develop/build-server
