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

Launch Antigravity CLI through the managed target:

```bash
python3 cli-tools/nddev_antigravity_cli.py launch --target /absolute/agy-home -- [agy args...]
```

`launch` sets `HOME` to the managed target and places XDG directories under the
same target for the child process. Provider credential environment variables are
not inherited.

## Ownership

The manager owns only:

- `toolPermission`, `artifactReviewPolicy`, `enableTerminalSandbox`, and
  `allowNonWorkspaceAccess` in `.gemini/antigravity-cli/settings.json`
- the `nddev-builder` plugin bundle
- `NDDEV-ANTIGRAVITY-CLI-SETUP.json`

Other settings keys, credentials, session logs, caches, and unrelated files are
preserved.
