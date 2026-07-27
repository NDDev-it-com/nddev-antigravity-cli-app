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

Setup backups and locks are target-internal under the explicit target. The
target lifecycle lock is a persistent private lock directory containing a 0600
regular lock file held with nonblocking `fcntl.flock` for the complete
lifecycle operation. While held, the lock directory is traversable but not
writable, so ordinary child cleanup cannot unlink the lock file. Backup pool
locks remain target-internal private directories. The manager rejects
symlinked or non-private lock, backup pool, and backup slot paths.

## Launch safety

`launch` holds the target-internal lifecycle lock from preflight through child
process completion. While holding that lock, it validates the managed setup,
requires current target-owned software, immediately rechecks the target-owned
`bin/agy` and version-tree binary digests, builds the filtered child
environment, and starts only the absolute target-owned `bin/agy` path. During
the child lifetime, the manager keeps the target-owned executable and software
parent directories read/execute-only and restores their owner-private writable
mode afterward. The protected directories are verified through `O_NOFOLLOW`
file descriptors before mode changes and before the immediate executable digest
recheck. This is a write-protected verified-path handoff under a no-sandbox
same-UID threat boundary; it is not portable fd execution and does not claim
deliberate same-UID chmod resistance. Other lifecycle mutations fail while the
launched child is running. It rejects
Antigravity CLI override flags that would replace the managed sandbox,
permission, execution-mode, custom-agent, or working-directory scope for the
session.

Legacy managed targets are launch-denied until migrated.
