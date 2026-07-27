#!/usr/bin/env python3
"""Validate public nddev-antigravity-cli-app contracts without private inputs."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
CLI_VERSION = "1.1.7"
SETUP_IDS = ["nddev-builder"]
PROFILE_IDS = ["full-auto", "safe"]
DEFAULT_PROFILE = "full-auto"
MANAGED_LAUNCH_OPTION_NAMES = [
    "--sandbox",
    "--dangerously-skip-permissions",
    "--permission-mode",
    "--mode",
    "--cwd",
    "--agent",
]
BUILDER_ROOT = ".gemini/antigravity-cli/plugins/nddev-builder"
BUILDER_MANAGED_FILES = [
    f"{BUILDER_ROOT}/plugin.json",
    f"{BUILDER_ROOT}/skills/nddev-builder/SKILL.md",
    f"{BUILDER_ROOT}/skills/nddev-builder/references/native-surfaces.md",
    f"{BUILDER_ROOT}/skills/nddev-builder/references/source-owners.md",
    f"{BUILDER_ROOT}/skills/nddev-builder/references/validation-workflows.md",
    f"{BUILDER_ROOT}/skills/nddev-antigravity-config/SKILL.md",
    f"{BUILDER_ROOT}/skills/nddev-antigravity-permissions/SKILL.md",
    f"{BUILDER_ROOT}/skills/nddev-antigravity-agents/SKILL.md",
    f"{BUILDER_ROOT}/skills/nddev-antigravity-instructions/SKILL.md",
    f"{BUILDER_ROOT}/skills/nddev-antigravity-plugins/SKILL.md",
    f"{BUILDER_ROOT}/skills/nddev-antigravity-hooks/SKILL.md",
    f"{BUILDER_ROOT}/skills/nddev-antigravity-mcp/SKILL.md",
    f"{BUILDER_ROOT}/skills/nddev-antigravity-lifecycle/SKILL.md",
    f"{BUILDER_ROOT}/skills/nddev-antigravity-validation/SKILL.md",
    f"{BUILDER_ROOT}/agents/nddev-builder.md",
    f"{BUILDER_ROOT}/rules/nddev-builder.md",
]
MANAGED_FILES = [".gemini/antigravity-cli/settings.json", *BUILDER_MANAGED_FILES]
MANAGED_FILES_WITH_STAMP = [*MANAGED_FILES, "NDDEV-ANTIGRAVITY-CLI-SETUP.json"]
FULL_AUTO_SETTINGS = {
    "toolPermission": "always-proceed",
    "artifactReviewPolicy": "always-proceed",
    "enableTerminalSandbox": False,
    "allowNonWorkspaceAccess": True,
    "permissions": {
        "deny": [],
        "ask": [],
        "allow": [
            "read_file(*)",
            "write_file(*)",
            "read_url(*)",
            "execute_url(*)",
            "command(*)",
            "unsandboxed(*)",
            "mcp(*)",
        ],
    },
}
SAFE_SETTINGS = {
    "toolPermission": "strict",
    "artifactReviewPolicy": "asks-for-review",
    "enableTerminalSandbox": True,
    "allowNonWorkspaceAccess": False,
    "permissions": {
        "deny": ["unsandboxed(*)"],
        "ask": [
            "write_file(*)",
            "read_url(*)",
            "execute_url(*)",
            "command(*)",
            "mcp(*)",
        ],
        "allow": [],
    },
}
EXPECTED_SETTINGS = {
    "full-auto": FULL_AUTO_SETTINGS,
    "safe": SAFE_SETTINGS,
}
WORKFLOWS = [
    "actionlint.yml",
    "codeql.yml",
    "dependency-review.yml",
    "release.yml",
    "scorecard.yml",
    "secret-scan.yml",
    "zizmor.yml",
]


def load_json(relative: str, errors: list[str]) -> dict[str, Any] | None:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"missing required JSON file: {relative}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{relative}: invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{relative}: top-level value must be an object")
        return None
    return value


def read_text(relative: str, errors: list[str]) -> str | None:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"missing required text file: {relative}")
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{relative}: unreadable text: {exc}")
        return None
    if not text.strip() or not text.endswith("\n"):
        errors.append(f"{relative}: must be non-empty LF-terminated text")
    if "\r" in text:
        errors.append(f"{relative}: must use LF line endings")
    return text


def read_build_version(errors: list[str]) -> str | None:
    text = read_text("VERSION", errors)
    if text is None:
        return None
    build_version = text.strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", build_version):
        errors.append("VERSION: invalid semantic version")
        return None
    return build_version


def import_manager(errors: list[str]) -> Any | None:
    path = ROOT / "cli-tools/nddev_antigravity_cli.py"
    spec = importlib.util.spec_from_file_location("nddev_antigravity_cli_public_check", path)
    if spec is None or spec.loader is None:
        errors.append("cannot import manager module")
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - public checker reports import failures.
        errors.append(f"manager import failed: {exc}")
        return None
    return module


def parse_frontmatter(text: str, relative: str, errors: list[str]) -> dict[str, str]:
    if not text.startswith("---\n"):
        errors.append(f"{relative}: missing YAML frontmatter")
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        errors.append(f"{relative}: unterminated YAML frontmatter")
        return {}
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            errors.append(f"{relative}: unsupported frontmatter line: {line}")
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if key in metadata:
            errors.append(f"{relative}: duplicate frontmatter key: {key}")
        metadata[key] = value
    return metadata


def source_for_builder_target(relative: str) -> str:
    prefix = f"{BUILDER_ROOT}/"
    return f"setups/nddev-builder/plugins/nddev-builder/{relative[len(prefix):]}"


def check_profiles(errors: list[str]) -> None:
    for profile_id, expected in EXPECTED_SETTINGS.items():
        profile = load_json(f"profiles/{profile_id}/profile.json", errors)
        settings = load_json(f"profiles/{profile_id}/settings.json", errors)
        if profile is not None:
            if set(profile) != {"schema_version", "id", "description", "default"}:
                errors.append(f"profiles/{profile_id}/profile.json: invalid keys")
            if profile.get("schema_version") != 1 or profile.get("id") != profile_id:
                errors.append(f"profiles/{profile_id}/profile.json: identity mismatch")
            if profile.get("default") is not (profile_id == DEFAULT_PROFILE):
                errors.append(f"profiles/{profile_id}/profile.json: default flag mismatch")
            if not isinstance(profile.get("description"), str) or not profile["description"].strip():
                errors.append(f"profiles/{profile_id}/profile.json: description required")
        if settings != expected:
            errors.append(f"profiles/{profile_id}/settings.json: settings payload mismatch")


def check_setup_toolkit(errors: list[str]) -> None:
    setup = load_json("setups/nddev-builder/setup.json", errors)
    if setup is not None:
        if set(setup) != {"schema_version", "id", "description", "managed_files", "builder_enabled"}:
            errors.append("setups/nddev-builder/setup.json: invalid keys")
        if setup.get("schema_version") != 1 or setup.get("id") != "nddev-builder":
            errors.append("setups/nddev-builder/setup.json: identity mismatch")
        if setup.get("managed_files") != BUILDER_MANAGED_FILES:
            errors.append("setups/nddev-builder/setup.json: managed_files mismatch")
        if setup.get("builder_enabled") is not True:
            errors.append("setups/nddev-builder/setup.json: builder_enabled must be true")
    plugin = load_json("setups/nddev-builder/plugins/nddev-builder/plugin.json", errors)
    if plugin != {
        "$schema": "https://antigravity.google/schemas/v1/plugin.json",
        "name": "nddev-builder",
        "description": "NDDev setup-module builder toolkit for Antigravity CLI.",
    }:
        errors.append("nddev-builder plugin.json: exact native manifest mismatch")
    for managed in BUILDER_MANAGED_FILES:
        text = read_text(source_for_builder_target(managed), errors)
        if text is None:
            continue
        if managed.endswith("/SKILL.md"):
            metadata = parse_frontmatter(text, source_for_builder_target(managed), errors)
            if set(metadata) != {"name", "description"}:
                errors.append(f"{source_for_builder_target(managed)}: skill frontmatter keys mismatch")
            folder_name = Path(managed).parent.name
            if metadata.get("name") != folder_name:
                errors.append(f"{source_for_builder_target(managed)}: skill name must match folder")
            if not metadata.get("description", "").strip():
                errors.append(f"{source_for_builder_target(managed)}: description required")
            for forbidden in ("validation/nddev-", ".serena/", "release-evidence"):
                if forbidden in text:
                    errors.append(f"{source_for_builder_target(managed)}: private artifact reference {forbidden}")
        if re.search(r"\b\d+\.\d+\.\d+\b", text):
            errors.append(f"{source_for_builder_target(managed)}: volatile version literal")
    entry = read_text(
        "setups/nddev-builder/plugins/nddev-builder/skills/nddev-builder/SKILL.md",
        errors,
    )
    if entry is not None:
        entry_dir = ROOT / "setups/nddev-builder/plugins/nddev-builder/skills/nddev-builder"
        for raw in re.findall(r"`([^`]+(?:SKILL\.md|\.md))`", entry):
            resolved = (entry_dir / raw).resolve()
            try:
                relative = resolved.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(f"entry skill routed path escapes repository: {raw}")
                continue
            if not resolved.is_file():
                errors.append(f"entry skill routed path missing: {relative}")
    agent = read_text("setups/nddev-builder/plugins/nddev-builder/agents/nddev-builder.md", errors)
    if agent is not None:
        metadata = parse_frontmatter(agent, "setups/nddev-builder/plugins/nddev-builder/agents/nddev-builder.md", errors)
        if "mode" in metadata or "permission" in metadata:
            errors.append("nddev-builder agent: legacy mode/permission keys are forbidden")
        for key in ("name", "description", "mainAgent", "subagent", "inheritMcp"):
            if key not in metadata:
                errors.append(f"nddev-builder agent: missing native frontmatter key {key}")


def check_contracts(errors: list[str], build_version: str | None) -> None:
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/antigravity-cli-baseline.json", errors)
    if version is not None and build_version is not None:
        if version.get("build_version") != build_version:
            errors.append("VERSION disagrees with build/version.json:build_version")
        if version.get("antigravity_cli_tested") != CLI_VERSION:
            errors.append(f"build/version.json: antigravity_cli_tested must be {CLI_VERSION}")
    if manifest is not None:
        if build_version is not None and manifest.get("build_version") != build_version:
            errors.append("build/manifest.json: build_version mismatch")
        setup_system = manifest.get("setup_system", {})
        if setup_system.get("content_setup_ids") != SETUP_IDS:
            errors.append("build/manifest.json: content setup ids mismatch")
        if setup_system.get("permission_profile_ids") != PROFILE_IDS:
            errors.append("build/manifest.json: permission profile ids mismatch")
        if setup_system.get("default_permission_profile_id") != DEFAULT_PROFILE:
            errors.append("build/manifest.json: default profile mismatch")
        if manifest.get("managed_files") != MANAGED_FILES_WITH_STAMP:
            errors.append("build/manifest.json: managed_files mismatch")
        if manifest.get("builder", {}).get("managed_files") != BUILDER_MANAGED_FILES:
            errors.append("build/manifest.json: builder managed files mismatch")
        if manifest.get("builder", {}).get("marketplace") is not None:
            errors.append("build/manifest.json: builder marketplace must be null")
        if manifest.get("builder", {}).get("default_hooks") is not False:
            errors.append("build/manifest.json: default hooks must be false")
        if manifest.get("builder", {}).get("default_mcp_servers") is not False:
            errors.append("build/manifest.json: default MCP servers must be false")
        policy = manifest.get("command_policy", {})
        for command in ("migrate", "software-status", "install-cli", "update-cli"):
            if command not in policy.get("json_supported", []):
                errors.append(f"build/manifest.json: command_policy missing {command}")
        launch = manifest.get("runtime_launch", {})
        if launch.get("managed_override_args_blocked") != MANAGED_LAUNCH_OPTION_NAMES:
            errors.append("build/manifest.json: launch override policy mismatch")
        software = manifest.get("software_install", {})
        if software.get("mechanism") != "official-antigravity-install-manifest":
            errors.append("build/manifest.json: software mechanism mismatch")
        if software.get("platform_manifest_ids") != [
            "darwin_amd64",
            "darwin_arm64",
            "linux_amd64",
            "linux_arm64",
        ]:
            errors.append("build/manifest.json: platform manifest ids mismatch")
        if software.get("artifact_pin_fields") != ["version", "url", "sha512"]:
            errors.append("build/manifest.json: artifact pin fields mismatch")
        if software.get("npm") is not None or software.get("pip") is not None:
            errors.append("build/manifest.json: npm/pip must stay null")
        backup = manifest.get("backup_policy", {})
        if backup.get("location") != "<target>/.nddev-antigravity-cli-backups":
            errors.append("build/manifest.json: backup location must be target-internal")
        if backup.get("lock") != "<target>/.nddev-antigravity-cli-backups-lock":
            errors.append("build/manifest.json: backup lock must be target-internal")
        if backup.get("pool_lock") is not True:
            errors.append("build/manifest.json: backup pool lock must be enabled")
    if contract is not None:
        if contract.get("contract_version") != 2:
            errors.append("config/nddev-contract.json: contract_version must be 2")
        if contract.get("manifest_ref") != "build/manifest.json":
            errors.append("config/nddev-contract.json: manifest_ref mismatch")
        if contract.get("setup_system", {}).get("content_setup_ids") != SETUP_IDS:
            errors.append("config/nddev-contract.json: content setup ids mismatch")
        if contract.get("setup_system", {}).get("permission_profile_ids") != PROFILE_IDS:
            errors.append("config/nddev-contract.json: permission profile ids mismatch")
        if contract.get("managed_state", {}).get("stamp_schema") != 2:
            errors.append("config/nddev-contract.json: stamp_schema must be 2")
        if contract.get("managed_state", {}).get("legacy_launch_denied") is not True:
            errors.append("config/nddev-contract.json: legacy launch denial required")
        if contract.get("builder", {}).get("marketplace") is not None:
            errors.append("config/nddev-contract.json: builder marketplace must be null")
        safety = contract.get("safety", {})
        if safety.get("target_lock") != ".nddev-antigravity-cli-lock":
            errors.append("config/nddev-contract.json: target lock must be target-internal")
        if safety.get("backup_pool_location") != ".nddev-antigravity-cli-backups":
            errors.append("config/nddev-contract.json: backup pool must be target-internal")
        if safety.get("backup_pool_lock") != ".nddev-antigravity-cli-backups-lock":
            errors.append("config/nddev-contract.json: backup pool lock must be target-internal")
    if baseline is not None:
        if baseline.get("schema_version") != 2:
            errors.append("baseline schema_version must be 2")
        if baseline.get("verified_date") != "2026-07-27":
            errors.append("baseline verified_date mismatch")
        if version is not None:
            release = baseline.get("release", {})
            if release.get("tag") != version.get("antigravity_cli_release_tag"):
                errors.append("baseline release tag mismatch")
            if release.get("published_at") != version.get("antigravity_cli_release_published_at"):
                errors.append("baseline release timestamp mismatch")
        if baseline.get("configuration", {}).get("marketplace") is not None:
            errors.append("baseline marketplace must be null")
        manifests = baseline.get("platform_manifests")
        if not isinstance(manifests, dict) or sorted(manifests) != [
            "darwin_amd64",
            "darwin_arm64",
            "linux_amd64",
            "linux_arm64",
        ]:
            errors.append("baseline platform manifests mismatch")
        else:
            for platform_id, meta in manifests.items():
                if set(meta) != {"version", "url", "sha512"}:
                    errors.append(f"baseline {platform_id}: invalid manifest keys")
                if meta.get("version") != CLI_VERSION:
                    errors.append(f"baseline {platform_id}: version mismatch")
                if not re.fullmatch(r"[0-9a-f]{128}", str(meta.get("sha512", ""))):
                    errors.append(f"baseline {platform_id}: missing SHA-512")
        script = baseline.get("install_script", {})
        if not re.fullmatch(r"[0-9a-f]{64}", str(script.get("sha256", ""))):
            errors.append("baseline install_script sha256 missing")
    for relative in (
        "README.md",
        "AGENTS.md",
        "CHANGELOG.md",
        "docs/software-lifecycle.md",
        "SECURITY.md",
        "cli-tools/nddev_antigravity_cli.py",
    ):
        read_text(relative, errors)
    for workflow in WORKFLOWS:
        read_text(f".github/workflows/{workflow}", errors)


def check_manager_constants(errors: list[str], build_version: str | None) -> None:
    manager = import_manager(errors)
    if manager is None:
        return
    if build_version is not None and manager.VERSION != build_version:
        errors.append("manager VERSION mismatch")
    if list(manager.SETUP_IDS) != SETUP_IDS:
        errors.append("manager SETUP_IDS mismatch")
    if list(manager.PROFILE_IDS) != PROFILE_IDS:
        errors.append("manager PROFILE_IDS mismatch")
    if list(manager.MANAGED_FILES) != MANAGED_FILES:
        errors.append("manager MANAGED_FILES mismatch")
    if list(manager.BUILDER_MANAGED_FILES) != BUILDER_MANAGED_FILES:
        errors.append("manager BUILDER_MANAGED_FILES mismatch")
    if manager.expected_settings_for_profile("full-auto") != FULL_AUTO_SETTINGS:
        errors.append("manager full-auto settings mismatch")
    if manager.expected_settings_for_profile("safe") != SAFE_SETTINGS:
        errors.append("manager safe settings mismatch")
    if manager.INSTALL_SCRIPT_SHA256 != "ee1ea43ce4e9e56356c4ab6dad907ef357ae4bdfcaadb682735909fb57c9c640":
        errors.append("manager install script sha256 mismatch")
    if sorted(manager.OFFICIAL_MANIFESTS) != [
        "darwin_amd64",
        "darwin_arm64",
        "linux_amd64",
        "linux_arm64",
    ]:
        errors.append("manager official manifest platform ids mismatch")
    for meta in manager.OFFICIAL_MANIFESTS.values():
        if set(meta) != {"version", "url", "sha512"}:
            errors.append("manager official manifest fields mismatch")
    for argv in (
        ["list", "--json"],
        ["plan", "--target", "/tmp/nddev-antigravity-cli"],
        ["install", "--profile", "safe", "--target", "/tmp/nddev-antigravity-cli"],
        ["migrate", "--target", "/tmp/nddev-antigravity-cli"],
        ["launch", "--target", "/tmp/nddev-antigravity-cli", "--", "--help"],
    ):
        try:
            manager.parse_args(argv)
        except SystemExit as exc:
            errors.append(f"manager parse_args rejected {argv}: {exc}")


def check_no_production_test_switches(errors: list[str]) -> None:
    source = read_text("cli-tools/nddev_antigravity_cli.py", errors)
    if source is None:
        return
    forbidden_patterns = {
        r"NDDEV_[A-Z0-9_]*TEST[A-Z0-9_]*": "NDDEV test environment switch",
        r"\bALLOW_TEST[A-Z0-9_]*\b": "ALLOW_TEST switch",
        r"\bTEST_(?:ARTIFACT|FAIL|TIMEOUT|SOURCE)[A-Z0-9_]*\b": "test behavior switch",
        r"\b(?:FIXTURE|SOURCE)_OVERRIDE[A-Z0-9_]*\b": "fixture/source override",
        r"file://": "local fixture source support",
        r"injected failure": "artificial failure hook",
    }
    for pattern, label in forbidden_patterns.items():
        if re.search(pattern, source):
            errors.append(f"manager exposes forbidden production test path: {label}")


def expect_manager_error(
    errors: list[str],
    label: str,
    manager: Any,
    callback: Any,
) -> None:
    try:
        callback()
    except manager.ManagerError:
        pass
    else:
        errors.append(f"{label}: expected ManagerError")


def chmod_private(path: Path) -> None:
    os.chmod(path, 0o700)


def install_fake_current_software(manager: Any, target: Path, script: bytes) -> None:
    manifest = manager.pinned_manifest()
    artifact = {
        "platform": manifest["platform"],
        "manifest_url": manifest["manifest_url"],
        "manifest_version": manifest["version"],
        "artifact_url": manifest["url"],
        "artifact_size": len(script),
        "artifact_sha512": manifest["sha512"],
        "binary_sha256": manager.sha256_bytes(script),
    }
    for guarded_path, label in (
        (manager.software_root(target), "test software root"),
        (manager.software_root(target) / "versions", "test software versions directory"),
        (manager.software_version_dir(target), "test software version directory"),
    ):
        manager.reject_existing_software_ancestor_links(target, guarded_path, label)
    manager.ensure_real_directory_path(manager.software_root(target), "test software root")
    manager.ensure_real_directory_path(
        manager.software_root(target) / "versions",
        "test software versions directory",
    )
    manager.ensure_real_directory_path(
        manager.software_version_dir(target),
        "test software version directory",
    )
    manager.atomic_write_executable(manager.managed_cli_path(target), script)
    manager.atomic_write_executable(manager.software_tree_binary_path(target), script)
    manager.atomic_write(
        manager.software_stamp_path(target),
        manager.canonical_json(manager.software_stamp(target, artifact)),
    )


def snapshot_target_regular_files(target: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in sorted(target.rglob("*")):
        relative = str(path.relative_to(target))
        if path.is_symlink():
            result[relative] = b"<symlink>"
            continue
        if path.is_file():
            result[relative] = path.read_bytes()
    return result


def snapshot_managed_files(manager: Any, target: Path) -> dict[str, bytes | None]:
    result: dict[str, bytes | None] = {}
    for relative in (*manager.MANAGED_FILES, manager.STAMP_NAME):
        if manager.target_file_exists(target, relative):
            result[relative] = manager.read_target_file(target, relative, owner_only=False)
        else:
            result[relative] = None
    return result


def require_status_clean(errors: list[str], label: str, manager: Any, target: Path) -> None:
    status = manager.current_status(target)
    if status.get("state") != "managed" or status.get("drift") != []:
        errors.append(f"{label}: target status is not clean: {status}")


def write_legacy_backup_envelope(
    manager: Any,
    target: Path,
    *,
    build_version: Any,
    stamp_sha256: Any,
) -> None:
    pool = manager.backup_pool(target)
    slot_dir = pool / "0"
    files_dir = slot_dir / "files"
    pool.mkdir(mode=0o700, exist_ok=True)
    os.chmod(pool, 0o700)
    slot_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(slot_dir, 0o700)
    files_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(files_dir, 0o700)
    envelope = {
        "schema_version": manager.LEGACY_BACKUP_SCHEMA,
        "product_name": manager.PRODUCT_NAME,
        "build_version": build_version,
        "slot": 0,
        "canonical_target": str(target),
        "source_setup_id": "safe",
        "managed_files": {relative: None for relative in manager.LEGACY_MANAGED_FILES},
        "stamp_sha256": stamp_sha256,
    }
    manager.atomic_write(slot_dir / manager.BACKUP_NAME, manager.canonical_json(envelope))


def check_restore_rejects_malformed_legacy_backup(errors: list[str], manager: Any) -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "malformed-legacy-backup-target"
        manager.mutate_setup(
            target,
            manager.DEFAULT_SETUP_ID,
            manager.DEFAULT_PROFILE_ID,
            "install",
        )
        clean_managed = snapshot_managed_files(manager, target)
        require_status_clean(errors, "malformed legacy backup precheck", manager, target)
        for build_version, stamp_sha256 in (
            (["not", "a", "scalar"], "0" * 64),
            (manager.VERSION, "not-a-sha256"),
        ):
            write_legacy_backup_envelope(
                manager,
                target,
                build_version=build_version,
                stamp_sha256=stamp_sha256,
            )
            before_all = snapshot_target_regular_files(target)
            expect_manager_error(
                errors,
                "malformed legacy backup restore",
                manager,
                lambda: manager.restore_backup(target, 0),
            )
            if snapshot_target_regular_files(target) != before_all:
                errors.append("malformed legacy backup restore: target bytes changed")
            if snapshot_managed_files(manager, target) != clean_managed:
                errors.append("malformed legacy backup restore: managed bytes changed")
            require_status_clean(errors, "malformed legacy backup postcheck", manager, target)


def check_malformed_legacy_stamp_errors(errors: list[str], manager: Any) -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "malformed-legacy-stamp-target"
        target.mkdir(mode=0o700)
        os.chmod(target, 0o700)
        stamp = {
            "schema_version": manager.LEGACY_STAMP_SCHEMA,
            "product_name": manager.PRODUCT_NAME,
            "build_version": manager.VERSION,
            "setup_id": ["safe"],
            "canonical_target": str(target),
            "managed_files": {relative: None for relative in manager.LEGACY_MANAGED_FILES},
            "builder": {
                "projection": "native-plugin",
                "enabled": True,
                "marketplace": None,
                "files": list(manager.LEGACY_BUILDER_MANAGED_FILES),
            },
        }
        manager.atomic_write(target / manager.STAMP_NAME, manager.canonical_json(stamp))
        expect_manager_error(
            errors,
            "malformed legacy stamp setup_id list",
            manager,
            lambda: manager.current_status(target),
        )
        launched = subprocess.run(
            [
                sys.executable,
                str(ROOT / "cli-tools/nddev_antigravity_cli.py"),
                "status",
                "--target",
                str(target),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        combined = launched.stdout + launched.stderr
        if launched.returncode == 0:
            errors.append("malformed legacy stamp CLI: expected non-zero exit")
        if "Traceback" in combined or "TypeError" in combined:
            errors.append("malformed legacy stamp CLI: traceback leaked")


def check_launch_allowed_requires_software(errors: list[str], manager: Any) -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "launch-allowed-target"
        manager.mutate_setup(
            target,
            manager.DEFAULT_SETUP_ID,
            manager.DEFAULT_PROFILE_ID,
            "install",
        )
        status = manager.current_status(target)
        if status.get("drift") != []:
            errors.append(f"launch_allowed without software: unexpected drift: {status}")
        if status.get("launch_allowed") is not False:
            errors.append("launch_allowed without software: expected false")
        expect_manager_error(
            errors,
            "launch without target-owned software",
            manager,
            lambda: manager.validate_launch_ready(target, []),
        )
        install_fake_current_software(
            manager,
            target,
            b"#!/bin/sh\nexit 0\n",
        )
        status = manager.current_status(target)
        if status.get("launch_allowed") is not True:
            errors.append(f"launch_allowed with target-owned software: expected true: {status}")
        try:
            manager.validate_launch_ready(target, [])
        except manager.ManagerError as exc:
            errors.append(f"launch with target-owned software rejected: {exc}")


def check_adversarial_smokes(errors: list[str]) -> None:
    manager = import_manager(errors)
    if manager is None:
        return

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "world-target"
        target.mkdir()
        os.chmod(target, 0o777)
        expect_manager_error(
            errors,
            "0777 target install",
            manager,
            lambda: manager.mutate_setup(
                target,
                manager.DEFAULT_SETUP_ID,
                manager.DEFAULT_PROFILE_ID,
                "install",
            ),
        )

    with tempfile.TemporaryDirectory(dir=tempfile.gettempdir()) as raw:
        root = Path(raw)
        target = root / "sticky-valid-target"
        result = manager.mutate_setup(
            target,
            manager.DEFAULT_SETUP_ID,
            manager.DEFAULT_PROFILE_ID,
            "install",
        )
        if result.get("setup_id") != manager.DEFAULT_SETUP_ID:
            errors.append("sticky temp target install: setup id mismatch")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "lock-target"
        target.mkdir(mode=0o700)
        chmod_private(target)
        marker = root / "external-marker"
        marker.write_text("keep\n", encoding="utf-8")
        os.symlink(marker, target / ".nddev-antigravity-cli-lock")
        expect_manager_error(
            errors,
            "symlink target lock",
            manager,
            lambda: manager.mutate_setup(
                target,
                manager.DEFAULT_SETUP_ID,
                manager.DEFAULT_PROFILE_ID,
                "install",
            ),
        )
        if marker.read_text(encoding="utf-8") != "keep\n":
            errors.append("symlink target lock: external marker changed")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "backup-pool-target"
        manager.mutate_setup(
            target,
            manager.DEFAULT_SETUP_ID,
            manager.DEFAULT_PROFILE_ID,
            "install",
        )
        marker_dir = root / "external-dir"
        marker_dir.mkdir()
        marker = marker_dir / "marker"
        marker.write_text("keep\n", encoding="utf-8")
        os.symlink(marker_dir, target / ".nddev-antigravity-cli-backups")
        expect_manager_error(
            errors,
            "symlink backup pool",
            manager,
            lambda: manager.mutate_setup(target, manager.DEFAULT_SETUP_ID, "safe", "switch"),
        )
        if marker.read_text(encoding="utf-8") != "keep\n":
            errors.append("symlink backup pool: external marker changed")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "backup-slot-target"
        manager.mutate_setup(
            target,
            manager.DEFAULT_SETUP_ID,
            manager.DEFAULT_PROFILE_ID,
            "install",
        )
        marker_dir = root / "external-slot"
        marker_dir.mkdir()
        marker = marker_dir / "marker"
        marker.write_text("keep\n", encoding="utf-8")
        pool = target / ".nddev-antigravity-cli-backups"
        pool.mkdir(mode=0o700)
        chmod_private(pool)
        os.symlink(marker_dir, pool / "0")
        expect_manager_error(
            errors,
            "symlink backup slot",
            manager,
            lambda: manager.mutate_setup(target, manager.DEFAULT_SETUP_ID, "safe", "switch"),
        )
        if marker.read_text(encoding="utf-8") != "keep\n":
            errors.append("symlink backup slot: external marker changed")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "backup-lock-target"
        manager.mutate_setup(
            target,
            manager.DEFAULT_SETUP_ID,
            manager.DEFAULT_PROFILE_ID,
            "install",
        )
        marker = root / "backup-lock-marker"
        marker.write_text("keep\n", encoding="utf-8")
        os.symlink(marker, target / ".nddev-antigravity-cli-backups-lock")
        expect_manager_error(
            errors,
            "symlink backup pool lock",
            manager,
            lambda: manager.mutate_setup(target, manager.DEFAULT_SETUP_ID, "safe", "switch"),
        )
        if marker.read_text(encoding="utf-8") != "keep\n":
            errors.append("symlink backup pool lock: external marker changed")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "software-link-target"
        target.mkdir(mode=0o700)
        chmod_private(target)
        marker_dir = root / "external-software"
        marker_dir.mkdir()
        marker = marker_dir / "marker"
        marker.write_text("keep\n", encoding="utf-8")
        os.symlink(marker_dir, target / ".nddev-software")
        expect_manager_error(
            errors,
            "symlink software ancestor",
            manager,
            lambda: manager.reject_existing_software_ancestor_links(
                target,
                manager.software_root(target),
                "software root",
            ),
        )
        if marker.read_text(encoding="utf-8") != "keep\n":
            errors.append("symlink software ancestor: external marker changed")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "path-target"
        fake_path = root / "fake-path"
        fake_path.mkdir()
        fake_python = fake_path / "python3"
        fake_python.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        os.chmod(fake_python, 0o700)
        manager.mutate_setup(
            target,
            manager.DEFAULT_SETUP_ID,
            manager.DEFAULT_PROFILE_ID,
            "install",
        )
        install_fake_current_software(
            manager,
            target,
            b"#!/bin/sh\nprintf '%s\\n' \"$PATH\"\n",
        )
        executable = manager.validate_launch_ready(target, [])
        old_path = os.environ.get("PATH")
        os.environ["PATH"] = str(fake_path)
        try:
            env = manager.build_launch_env(target)
        finally:
            if old_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old_path
        if str(fake_path) in env.get("PATH", ""):
            errors.append("fake PATH launch env: inherited attacker PATH")
        launched = subprocess.run(
            [str(executable)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if launched.returncode != 0:
            errors.append(f"fake PATH launch env: fake agy failed: {launched.stderr}")
        if str(fake_path) in launched.stdout:
            errors.append("fake PATH launch env: child observed attacker PATH")

    check_restore_rejects_malformed_legacy_backup(errors, manager)
    check_malformed_legacy_stamp_errors(errors, manager)
    check_launch_allowed_requires_software(errors, manager)


def check_no_current_forbidden_surfaces(errors: list[str]) -> None:
    for forbidden_path in (
        "setups/safe",
        "setups/full-auto",
        "setups/" + "bal" + "anced",
    ):
        if (ROOT / forbidden_path).exists():
            errors.append(f"retired setup path must be absent: {forbidden_path}")
    for relative in (
        "README.md",
        "docs/software-lifecycle.md",
        "config/nddev-contract.json",
        "build/manifest.json",
        "references/antigravity-cli-baseline.json",
    ):
        text = read_text(relative, errors)
        if text is None:
            continue
        unsupported_platform = "Win" + "dows"
        if unsupported_platform in text or unsupported_platform.lower() in text:
            errors.append(f"{relative}: unsupported platform support text must be absent")
        retired_profile = "bal" + "anced"
        if retired_profile in text:
            errors.append(f"{relative}: retired setup/profile text must be absent")


def main() -> int:
    errors: list[str] = []
    build_version = read_build_version(errors)
    check_profiles(errors)
    check_setup_toolkit(errors)
    check_contracts(errors, build_version)
    check_manager_constants(errors, build_version)
    check_no_production_test_switches(errors)
    check_adversarial_smokes(errors)
    check_no_current_forbidden_surfaces(errors)
    if errors:
        print(f"validate_public_contracts.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
