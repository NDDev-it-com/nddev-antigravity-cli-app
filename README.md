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
- Supported hosts: macOS arm64/x64 and Ubuntu glibc arm64/x64

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
python3 cli-tools/nddev_antigravity_cli.py update --target /absolute/agy-home --json
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
python3 cli-tools/nddev_antigravity_cli.py remove-cli --target /absolute/agy-home --json
```

`software-status` is read-only and never executes `agy`. Read-only commands
report cleanup-pending state but never repair it; the next mutation drains valid
pending cleanup before active changes.

Launch through the managed target:

```bash
python3 cli-tools/nddev_antigravity_cli.py launch --target /absolute/agy-home -- [agy args...]
```

`launch` is the authentication boundary. The stable user-visible guarantee is
that it launches only from the explicit managed target, requires clean managed
state and current target-owned software, keeps lifecycle mutations serialized
through child completion, preserves normal runtime writes for the child, and
does not inherit ambient credentials. Exact lock, executable handoff,
environment, denial, and recovery mechanics are code-owned by
`cli-tools/nddev_antigravity_cli.py`; machine-readable release contracts live in
`build/manifest.json` and `config/nddev-contract.json`.

At launch-command entry, the manager captures the caller's current directory
once, strictly resolves it as an existing accessible project workspace, and
passes it explicitly as the child working directory. The managed target
remains the isolated Antigravity configuration and runtime home. No native
workspace flag is added by this module.

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
