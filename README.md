# NDDev Antigravity CLI Setup Manager

`nddev-antigravity-cli-app` installs and switches complete Antigravity CLI setup
variants in an explicit isolated HOME target. It never defaults to the
operator's live `~/.gemini/antigravity-cli`.

## Setups

- `safe`: `toolPermission=strict`, artifact review required, sandbox enabled,
  non-workspace access disabled.
- `balanced`: `toolPermission=proceed-in-sandbox`, dynamic artifact review,
  sandbox enabled, non-workspace access disabled.
- `full-auto`: `toolPermission=always-proceed`, artifact writes allowed,
  sandbox enabled, non-workspace access enabled.

## Native Builder Projection

Antigravity CLI documents plugins as bundles staged under
`~/.gemini/antigravity-cli/plugins/<plugin_name>/`. This module projects
`nddev-builder` onto that native plugin surface:

- `plugin.json`
- `skills/nddev-builder/SKILL.md`
- `agents/nddev-builder.md`
- `rules/nddev-builder.md`

No marketplace format is declared because the official Antigravity CLI docs do
not document one.

## Usage

```bash
python3 cli-tools/nddev_antigravity_cli.py list --json
python3 cli-tools/nddev_antigravity_cli.py plan --setup safe --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py install --setup safe --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py switch --setup balanced --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py switch --setup full-auto --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py restore --backup 0 --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py remove --target /absolute/agy-home --json
```

## Software lifecycle

The setup lifecycle and CLI binary lifecycle are separate. `install-cli` and
`update-cli` install the current `agy` binary into the explicit target from the
pinned official GitHub release artifact for Antigravity CLI 1.1.7. The manager
does not use npm or pip.

```bash
python3 cli-tools/nddev_antigravity_cli.py software-status --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py install-cli --target /absolute/agy-home --json
python3 cli-tools/nddev_antigravity_cli.py update-cli --target /absolute/agy-home --json
```

`install-cli` requires absent managed software. `update-cli` requires existing
managed software and is an idempotent no-op when `software-status` reports
`current=true`. The target-owned binary is written to `bin/agy` and mirrored
under `.nddev-software/antigravity-cli/versions/1.1.7/`. Updates stage a full
version tree and atomically swap it into place; rollback restores the version
tree, `bin/agy`, and the software stamp.

`software-status` reports both `installed` and `current`: `installed` means the
target has a structurally complete binary plus matching stamp digest; `current`
additionally requires the stamp to match this module's exact current version,
official source URL, current platform asset, artifact SHA-256 and size pins, and
build.

Launch Antigravity CLI through the managed target:

```bash
python3 cli-tools/nddev_antigravity_cli.py launch --target /absolute/agy-home -- [agy args...]
```

`launch` sets `HOME` to the managed target and places XDG directories under the
same target for the child process. It requires `software-status` to report
`installed=true` and `current=true`, executes only the absolute target-owned
`bin/agy`, and never falls back to `PATH`. It validates the managed target while
holding the target lock, releases the lock before starting the child process,
and rejects documented Antigravity CLI flags that override managed sandbox,
permission, execution-mode, or working-directory scope. Provider credential
environment variables are not inherited.

## Ownership

The manager owns only:

- `toolPermission`, `artifactReviewPolicy`, `enableTerminalSandbox`, and
  `allowNonWorkspaceAccess` in `.gemini/antigravity-cli/settings.json`
- the `nddev-builder` plugin bundle
- `NDDEV-ANTIGRAVITY-CLI-SETUP.json`

Other settings keys, credentials, session logs, caches, and unrelated files are
preserved.
