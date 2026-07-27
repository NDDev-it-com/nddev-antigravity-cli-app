# Public validation workflows

Run public, non-live checks from the module root:

```bash
python3 cli-tools/validate_public_contracts.py
python3 -m py_compile cli-tools/nddev_antigravity_cli.py cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_antigravity_cli.py list --json
```

For a local lifecycle smoke check, use a temporary target outside live
Antigravity state:

```bash
target="$(mktemp -d)/agy-home"
python3 cli-tools/nddev_antigravity_cli.py plan --target "$target" --json
python3 cli-tools/nddev_antigravity_cli.py install --target "$target" --json
python3 cli-tools/nddev_antigravity_cli.py status --target "$target" --json
python3 cli-tools/nddev_antigravity_cli.py remove --target "$target" --json
```

Do not run `launch`, browser auth, CI, tags, pushes, or root-private harness
lanes from this public toolkit.
