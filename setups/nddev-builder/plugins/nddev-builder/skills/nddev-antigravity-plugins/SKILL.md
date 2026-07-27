---
name: nddev-antigravity-plugins
description: Create or check native Antigravity CLI plugin packaging while avoiding unsupported marketplace emulation.
---

# Antigravity plugins

Use this skill when editing plugin manifests, staged plugin layout, or
marketplace-related documentation.

## Native paths

- CLI-staged plugin root:
  `~/.gemini/antigravity-cli/plugins/<plugin_name>/`
- Plugin manifest:
  `<plugin-root>/plugin.json`
- Plugin capability folders:
  `<plugin-root>/skills/`, `<plugin-root>/agents/`, `<plugin-root>/rules/`
- Optional plugin files:
  `<plugin-root>/hooks.json`, `<plugin-root>/mcp_config.json`

## Rules

- Keep `plugin.json` minimal and native.
- Do not emulate a plugin marketplace.
- MCP Store behavior is MCP-specific, not a plugin marketplace for this
  setup manager.
- Default NDDev builder does not install hooks or MCP servers.

## Check

Run:

```bash
python3 cli-tools/validate_public_contracts.py
```
