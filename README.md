# NDDev Antigravity CLI Setup Manager

`nddev-antigravity-cli-app` is a dependency-free public setup manager for
Google Antigravity CLI. It writes one NDDev content setup and one orthogonal
permission profile into an explicit isolated HOME target. It never defaults to
the operator's live `~/.gemini` state.

## Current model

- Content setup: `nddev-builder`
- Default permission profile: `full-auto`
- Review-gated permission profile: `safe`
- Managed command: `agy`
- Managed target executable: `bin/agy`

Exact profile payloads are owned by `profiles/`. Exact runtime pins and source
provenance are owned by `references/antigravity-cli-baseline.json`. Manager
behavior is owned by `cli-tools/nddev_antigravity_cli.py`.

## Native builder toolkit

The public `nddev-builder` setup is staged as a native Antigravity CLI plugin
under the managed target:

```text
~/.gemini/antigravity-cli/plugins/nddev-builder/
```

It installs a full public builder toolkit:

- plugin manifest
- routed entry Agent Skill
- focused Agent Skills for configuration/profile, permissions/sandbox,
  agents/subagents, instructions/skills/rules, plugins, hooks, MCP, lifecycle,
  and validation
- focused references for native paths, code-owned fact owners, and executable
  public validation workflows
- native Markdown builder agent
- native builder rule

The default setup does not install hooks, MCP servers, credentials, or a plugin
marketplace.

## Usage

List available content setups and profiles:

```bash
python3 cli-tools/nddev_antigravity_cli.py list --json
```

Plan or install the default setup/profile:

```bash
python3 cli-tools/nddev_antigravity_cli.py plan --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py install --target /absolute/agy-home --json
```

Install or switch to the review-gated profile:

```bash
python3 cli-tools/nddev_antigravity_cli.py install --profile safe --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py switch --profile safe --target /absolute/agy-home --json
```

Inspect, migrate, restore, or remove managed state:

```bash
python3 cli-tools/nddev_antigravity_cli.py status --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py migrate --profile full-auto --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py restore --backup 0 --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py remove --target /absolute/agy-home --json
```

Legacy managed targets are readable for status, migrate, restore, and remove.
They cannot launch until migrated.

## Software lifecycle

The setup lifecycle and CLI binary lifecycle are separate. `install-cli` and
`update-cli` install a target-owned `agy` binary from the official Antigravity
install manifest pins recorded in `references/antigravity-cli-baseline.json`.
The manager does not use npm, pip, shell-profile mutation, or the caller's live
home directory.

```bash
python3 cli-tools/nddev_antigravity_cli.py software-status --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py install-cli --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py update-cli --target /absolute/agy-home --json
```

`software-status` is read-only and never executes `agy`.

Launch through the managed target:

```bash
python3 cli-tools/nddev_antigravity_cli.py launch --target /absolute/agy-home -- [agy args...]
```

`launch` is the authentication boundary. It requires clean managed setup state,
current target-owned software, the target-owned executable, and a filtered
child environment.

## Public validation

Run from the module root:

```bash
python3 cli-tools/validate_public_contracts.py
python3 -m py_compile cli-tools/nddev_antigravity_cli.py cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_antigravity_cli.py list --json
```

Use only temporary targets for local lifecycle smoke checks. Do not run against
live Antigravity state.

## Ownership

This public module owns runtime implementation, setup/profile payloads, public
contracts, public documentation, and public release metadata. Private tests,
benchmarks, memories, release evidence, root registry pins, and CI
orchestration belong outside this repository.
