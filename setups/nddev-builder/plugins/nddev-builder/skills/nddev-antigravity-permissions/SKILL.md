---
name: nddev-antigravity-permissions
description: Design or review NDDev Antigravity CLI permission, sandbox, non-workspace, and artifact-review posture.
---

# Antigravity permissions and sandbox

Use this skill for permission profile work.

## Native settings path

`~/.gemini/antigravity-cli/settings.json`

## Source owners

- Exact profile JSON: `profiles/<profile-id>/settings.json`
- Profile validation and launch enforcement:
  `cli-tools/nddev_antigravity_cli.py`
- Public contract: `config/nddev-contract.json`

## Rules

- Do not copy profile JSON into docs or prompts; point to `profiles/`.
- Full-auto must be non-interactive and unsandboxed according to the public
  profile payload.
- Safe must remain review-gated and sandboxed.
- Permission selector strings are code-owned by the profile payloads and
  validator.
- Launch flags that override managed permission, sandbox, execution mode, or
  working-directory scope must be rejected.

## Check

Run:

```bash
python3 cli-tools/validate_public_contracts.py
```
