---
name: nddev-antigravity-validation
description: Run public creator, checker, release-readiness, and non-live validation workflows for the Antigravity CLI setup module.
---

# Antigravity public validation

Use this skill before committing public module changes.

## Public checks

Run from the module root:

```bash
python3 cli-tools/validate_public_contracts.py
python3 -m py_compile cli-tools/nddev_antigravity_cli.py cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_antigravity_cli.py list --json
```

## Local lifecycle smoke

Use a temporary target only. Do not use live Antigravity state.

```bash
target="$(mktemp -d)/agy-home"
python3 cli-tools/nddev_antigravity_cli.py install --target "$target" --json
python3 cli-tools/nddev_antigravity_cli.py status --target "$target" --json
python3 cli-tools/nddev_antigravity_cli.py remove --target "$target" --json
```

Root-private validation lanes, private memories, release evidence, and CI are
owned outside this public module.
