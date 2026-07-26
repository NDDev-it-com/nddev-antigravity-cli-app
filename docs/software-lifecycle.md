# Antigravity CLI software lifecycle

`nddev-antigravity-cli-app` can manage the `agy` executable inside the same
explicit target used for setup state. This is optional and target-owned; it
does not install into a live user home or system prefix.

## Commands

- `software-status --target <absolute-target>` is read-only.
- `install-cli --target <absolute-target>` installs only when no managed
  software stamp or binary is present.
- `update-cli --target <absolute-target>` requires existing managed software.
  If the target is already current, it returns an idempotent no-op without
  downloading.

## Source and integrity

Production installs use only the official Antigravity CLI GitHub release
artifacts for version 1.1.7. The current platform asset name and artifact
SHA-256 are pinned in `references/antigravity-cli-baseline.json`; npm and pip
install paths are intentionally unsupported.

The archive reader never extracts an archive wholesale. It reads exactly one
regular `agy` or `agy.exe` member from the archive stream, rejects absolute,
parent-traversal, Windows-drive, NUL, and leading-`//` paths, rejects tar
symlinks, hardlinks, devices, and duplicate candidates, and requires zip
candidates to be regular files by `external_attr`.

## Target layout and rollback

The managed executable is written to:

- `bin/agy`
- `.nddev-software/antigravity-cli/versions/1.1.7/agy`
- `.nddev-software/antigravity-cli/NDDEV-ANTIGRAVITY-CLI-SOFTWARE.json`

Updates stage a complete version tree under the target and atomically rename it
into place. On failure, the manager restores the previous version tree, the
visible `bin/agy`, and the software stamp.
