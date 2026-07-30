# Antigravity CLI software lifecycle

`nddev-antigravity-cli-app` can manage the `agy` executable inside the same
explicit target used for setup state. This is optional and target-owned; it
does not install into a live user home or system prefix.

## Commands

- `software-status --target <absolute-target>` is read-only and never executes
  `agy`.
- `install-cli --target <absolute-target>` installs only when no managed
  software stamp or binary is present.
- `update-cli --target <absolute-target>` requires existing managed software.
  If the target is already current, it returns an idempotent no-op without
  downloading.
- `remove-cli --target <absolute-target>` removes only target-owned software
  while preserving setup-managed Antigravity configuration.

## Source and integrity

Production installs use the official Antigravity CLI install manifest for the
runtime version declared in `build/version.json`. Exact install-script
provenance, manifest URLs, platform ids, artifact URLs, and SHA-512 pins are
owned by `references/antigravity-cli-baseline.json` and mirrored in the manager
constants.

The manager does not execute the vendor install script. It reads the official
manifest, verifies that it still matches the pinned baseline, downloads the
pinned artifact, verifies SHA-512, and extracts one regular CLI binary member
from the tar stream.

## Target layout and rollback

The managed executable is written to:

- `bin/agy`
- `.nddev-software/antigravity-cli/versions/<runtime-version>/agy`
- `.nddev-software/antigravity-cli/NDDEV-ANTIGRAVITY-CLI-SOFTWARE.json`

Updates stage a complete version tree under the target and atomically rename it
into place. On failure, the manager restores the previous version tree, the
visible `bin/agy`, and the software stamp.

Lifecycle locking is code-owned by `cli-tools/nddev_antigravity_cli.py`. The
stable guarantee is that target lifecycle mutations are serialized for the
explicit target, runtime state remains writable for launched Antigravity, and
unsafe ownership or path-shape changes fail closed. Exact lock topology, modes,
ordering, binding, rollback, cleanup-pending, and recovery semantics are
declared by the manager and summarized machine-readably in
`build/manifest.json` and `config/nddev-contract.json`.

## Launch safety

`launch` is the managed auth boundary. It uses the explicit target, requires
clean managed state and current target-owned software, forwards the child exit
code, and does not use live user credentials. The detailed executable handoff,
argument rejection, child environment, and same-UID no-sandbox boundary are
owned by `cli-tools/nddev_antigravity_cli.py` with contract pointers in
`build/manifest.json` and `config/nddev-contract.json`.

Launch captures and strictly resolves the caller current directory once and
uses that project workspace as the explicit child working directory. It stays
separate from the managed target home, and the manager does not invent a
native Antigravity workspace flag.

Legacy managed targets are launch-denied until migrated.
