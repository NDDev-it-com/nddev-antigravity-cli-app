---
name: nddev-antigravity-mcp
description: Design or check Antigravity CLI MCP configuration boundaries without bundling default MCP servers or secrets.
---

# Antigravity MCP

Use this skill when MCP configuration is intentionally added or reviewed.

## Native paths and shape

- Global MCP config: `~/.gemini/config/mcp_config.json`
- Workspace MCP config: `.agents/mcp_config.json`
- Config root object: `mcpServers`
- Local stdio transport: `command`
- Remote transport: `serverUrl`

## Rules

- The default `nddev-builder` setup installs no MCP servers.
- Do not store credentials, OAuth client secrets, API tokens, or live service
  headers in setup payloads.
- Use `serverUrl` for remote connections; do not use legacy remote URL keys.
- MCP permissions are profile-owned; point to `profiles/` and the manager.

## Check

Run:

```bash
python3 cli-tools/validate_public_contracts.py
```
