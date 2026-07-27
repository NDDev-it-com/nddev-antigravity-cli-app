---
name: nddev-antigravity-config
description: Create or check Antigravity CLI NDDev content setup and profile payloads without duplicating code-owned version or pin facts.
---

# Antigravity configuration and profiles

Use this skill when changing setup/profile structure, managed settings,
contract fields, or setup rendering.

## Source owners

- Content setup source: `setups/nddev-builder/`
- Profile payloads: `profiles/<profile-id>/settings.json`
- Public contract: `config/nddev-contract.json`
- Runtime manifest: `build/manifest.json`
- Manager renderer: `cli-tools/nddev_antigravity_cli.py`

## Rules

- Keep content setup and permission profile orthogonal.
- Keep `nddev-builder` as the only content setup unless the contract is
  intentionally extended.
- Keep full-auto as the default profile.
- Do not add a third permission profile or unsupported platform payloads.
- Preserve unmanaged settings keys when rendering target settings.

## Check

Run:

```bash
python3 cli-tools/validate_public_contracts.py
```
