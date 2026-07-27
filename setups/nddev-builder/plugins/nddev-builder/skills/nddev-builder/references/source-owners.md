# Code-owned fact owners

Keep volatile facts in their owning files. Skills and documents should point to
these owners instead of copying their values.

- Build version and tested runtime: `VERSION` and `build/version.json`
- Public contract and managed state contract: `config/nddev-contract.json`
- Runtime setup manifest: `build/manifest.json`
- Official runtime source ledger and artifact pins:
  `references/antigravity-cli-baseline.json`
- Profile payloads: `profiles/<profile-id>/settings.json`
- Content setup payload: `setups/nddev-builder/`
- Manager behavior, stamps, locks, backups, software lifecycle, launch policy:
  `cli-tools/nddev_antigravity_cli.py`
- Public contract validator:
  `cli-tools/validate_public_contracts.py`
- Public software lifecycle documentation:
  `docs/software-lifecycle.md`

Do not copy current SHAs, artifact digests, supported platform pins, setup file
lists, profile JSON, or command allowlists into durable notes when one of the
owners above already declares them.
