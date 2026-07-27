---
name: nddev-antigravity-lifecycle
description: Implement or check target-owned Antigravity CLI installation, update, migration, launch, rollback, backup, and restore behavior.
---

# Antigravity setup and software lifecycle

Use this skill for manager lifecycle changes.

## Source owners

- Manager implementation: `cli-tools/nddev_antigravity_cli.py`
- Software lifecycle docs: `docs/software-lifecycle.md`
- Runtime facts and installed software state: run `list --json`,
  `status --json`, and `software-status --json` through the public manager.
- Source-tree fact owners: `../nddev-builder/references/source-owners.md`

## Rules

- All operations require an explicit absolute target.
- Never default to live user Antigravity state.
- Keep target locks, bounded reads/downloads, owner-only file modes,
  transaction staging, rollback, target-bound backups, and restore checks.
- `software-status` is read-only and must not execute `agy`.
- `install-cli` and `update-cli` install target-owned software only.
- `launch` is the auth boundary and must use the target-owned executable.
- Legacy managed state is launch-denied and only available for status,
  migrate, restore, and remove.
- Do not copy current runtime pins or ledger values into a skill. Route to the
  public manager output or the source-owner reference above.

## Check

Run:

```bash
python3 cli-tools/validate_public_contracts.py
python3 -m py_compile cli-tools/nddev_antigravity_cli.py
```
