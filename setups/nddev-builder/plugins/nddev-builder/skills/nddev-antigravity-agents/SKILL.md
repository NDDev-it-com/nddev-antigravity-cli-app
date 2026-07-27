---
name: nddev-antigravity-agents
description: Create or check native Antigravity CLI Markdown agents and subagents for the NDDev builder plugin.
---

# Antigravity agents and subagents

Use this skill when editing plugin agent files or agent-related documentation.

## Native paths

- Workspace agent file: `.agents/agents/<name>.md`
- Workspace agent directory form: `.agents/agents/<name>/agent.md`
- Global agent file: `~/.gemini/config/agents/<name>.md`
- Global directory form: `~/.gemini/config/agents/<name>/agent.md`
- Plugin agent file: `<plugin-root>/agents/<name>.md`

## Rules

- Use native Markdown frontmatter.
- Do not use legacy or invented keys such as `mode` or nested `permission`.
- Keep the managed plugin agent under
  `setups/nddev-builder/plugins/nddev-builder/agents/`.
- Do not bundle private harness instructions.

## Check

Run:

```bash
python3 cli-tools/validate_public_contracts.py
```
