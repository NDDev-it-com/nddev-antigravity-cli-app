---
name: nddev-antigravity-hooks
description: Design or check Antigravity CLI hook files without adding default hooks to the NDDev builder setup.
---

# Antigravity hooks

Use this skill only when hooks are intentionally added to a future setup.

## Native paths

- Workspace hooks: `.agents/hooks.json`
- Global hooks: `~/.gemini/config/hooks.json`
- Plugin hooks: `<plugin-root>/hooks.json`

## Rules

- The default `nddev-builder` setup installs no hooks.
- Do not write hook files unless the public contract and manager explicitly own
  them.
- Hook commands must be deterministic, bounded, and free of secrets.
- Hook schemas belong in validators, not in prose copies.

## Check

Run:

```bash
python3 cli-tools/validate_public_contracts.py
```
