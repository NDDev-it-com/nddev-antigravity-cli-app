# nddev-antigravity-cli-app

This public repository owns Antigravity CLI setup-manager runtime
implementation, setup/profile payloads, public contracts, documentation, and
release metadata only.

## Boundaries

- Keep public implementation in this repository.
- Keep private validation, benchmarks, durable memories, release evidence,
  registry pins, and CI orchestration outside this repository.
- Do not commit secrets, credentials, runtime logs, caches, generated evidence,
  or live Antigravity state.
- Do not mutate the operator's live `~/.gemini` state.

## Native Antigravity CLI surfaces

Use documented native surfaces only:

- `agy`
- `~/.gemini/antigravity-cli/settings.json`
- `~/.gemini/antigravity-cli/plugins/<plugin_name>/`
- plugin `skills/`, `agents/`, and `rules/`
- documented workspace/global skills, agents, rules, hooks, and MCP paths when
  the public contract intentionally owns them

Do not emulate a plugin marketplace. The default `nddev-builder` setup does
not install hooks, MCP servers, or credentials.

## Source owners

- Version and tested runtime: `VERSION`, `build/version.json`
- Public contract and manifest: `config/nddev-contract.json`,
  `build/manifest.json`
- Runtime source ledger and artifact pins:
  `references/antigravity-cli-baseline.json`
- Manager behavior: `cli-tools/nddev_antigravity_cli.py`
- Public validator: `cli-tools/validate_public_contracts.py`
- Profile payloads: `profiles/`
- Content setup payload: `setups/nddev-builder/`

Point to these files instead of copying volatile versions, pins, digests,
profile payloads, setup file lists, or launch policy into long-lived prose.

## Public checks

Run from the module root:

```bash
python3 cli-tools/validate_public_contracts.py
python3 -m py_compile cli-tools/nddev_antigravity_cli.py cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_antigravity_cli.py list --json
```
