# Changelog

## [0.2.3]

- Refresh the tested Antigravity CLI runtime and official artifact pins to 1.1.11.

## 0.2.2

- Capture and strictly resolve the caller workspace once at launch entry and
  pass it explicitly as the Antigravity child working directory.
- Declare target/workspace roles in public status and contracts without adding
  an unverified native workspace flag.

## 0.2.1

- Harden monotonic product and canonical-target coordination, cleanup-pending
  lifecycle recovery, and read-only no-mutation behavior.
- Add separate setup update and software remove commands.
- Update the target-owned Antigravity CLI runtime baseline to the latest
  official release metadata owned by the machine-readable baseline.

## 0.2.0

- Replace setup-as-profile layout with one `nddev-builder` content setup and
  orthogonal `full-auto` and `safe` permission profiles.
- Make `full-auto` the default profile with non-interactive documented allow
  selectors and terminal sandboxing disabled.
- Expand the native `nddev-builder` plugin projection into a routed public
  Agent Skills toolkit with focused native-surface guidance.
- Move target-owned software installation to official Antigravity CLI manifest
  pins with SHA-512 artifact verification.
- Add legacy managed-target launch denial plus status, migrate, restore, and
  remove handling.
- Harden launch argument rejection, pre-login environment isolation, and backup
  pool locking.

## 0.1.0

- Add target-explicit Antigravity CLI setup manager.
- Add native `nddev-builder` plugin projection with skills, agents, and rules.
- Add target-owned Antigravity CLI software status/install/update lifecycle.
- Add public contract, manifest, runtime baseline, validator, and shared-CI
  workflow callers.
