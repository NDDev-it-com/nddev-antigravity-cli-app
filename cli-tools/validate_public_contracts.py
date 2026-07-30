#!/usr/bin/env python3
"""Validate public nddev-antigravity-cli-app contracts without private inputs."""

from __future__ import annotations

import ast
import json
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
PRODUCT_NAME = "nddev-antigravity-cli-app"
CLI_VERSION = "1.1.8"
CLAUDE_BRIDGE_DIR = ".claude"
CLAUDE_BRIDGE_PATH = ".claude/CLAUDE.md"
CLAUDE_BRIDGE_BYTES = b"@../AGENTS.md\n"
CLAUDE_IMPORT_TARGET = "AGENTS.md"
REQUIRED_CLAUDE_RUNTIME_PATHS = {
    CLAUDE_BRIDGE_DIR,
    CLAUDE_IMPORT_TARGET,
}
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


def validate_launch_scope(owner: str, launch: dict[str, Any], errors: list[str]) -> None:
    expected = {
        "target_role": "managed-configuration-runtime-home",
        "workspace_source": "captured-caller-current-directory",
        "child_working_directory_policy": "strict-resolved-caller-workspace",
        "native_workspace_argument": None,
    }
    for key, value in expected.items():
        if launch.get(key) != value:
            errors.append(f"{owner}: runtime_launch.{key} mismatch")
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
RELEASE_WORKFLOW = ".github/workflows/release.yml"
RELEASE_SUPPLY_CHAIN_CALLER = (
    "NDDev-it-com/ci-workflows/.github/workflows/release-supply-chain.yml"
    "@2ccb80e96f5771b6a6b4eae63a4f47e232906dc7"
)
RELEASE_SUPPLY_CHAIN_VERSION_COMMENT = "0.12.0"
RELEASE_JOB_PERMISSIONS = {
    "attestations": "write",
    "artifact-metadata": "write",
    "contents": "write",
    "id-token": "write",
}
REQUIRED_ARCHIVE_PATHS = {
    "README.md",
    "LICENSE",
    "VERSION",
    "CHANGELOG.md",
    "SECURITY.md",
    CLAUDE_IMPORT_TARGET,
    CLAUDE_BRIDGE_DIR,
    ".gitignore",
    ".gds",
    ".github",
    "build",
    "cli-tools",
    "config",
    "docs",
    "references",
    "profiles",
    "setups",
}
BASE_RUNTIME_PATHS = {
    "README.md",
    "LICENSE",
    "VERSION",
    CLAUDE_IMPORT_TARGET,
    CLAUDE_BRIDGE_DIR,
    "build",
    "cli-tools",
    "config",
    "references",
}
IGNORED_TREE_PARTS = {".git", "__pycache__"}
PRIVATE_TREE_PARTS = {
    ".agents",
    ".serena",
    "release-evidence",
    "validation",
}


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


def public_tree_paths(errors: list[str]) -> set[str]:
    paths: set[str] = set()
    for path in ROOT.rglob("*"):
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        parts = set(Path(relative).parts)
        if parts & IGNORED_TREE_PARTS:
            continue
        try:
            info = path.lstat()
        except OSError as exc:
            errors.append(f"public tree path cannot be inspected: {relative}: {exc}")
            continue
        if stat.S_ISLNK(info.st_mode):
            errors.append(f"public tree path must not be a symlink: {relative}")
            continue
        if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
            errors.append(f"public tree path has unsupported file type: {relative}")
            continue
        private_markers = sorted(parts & PRIVATE_TREE_PARTS)
        if private_markers:
            errors.append(f"public tree contains private marker path {private_markers}: {relative}")
            continue
        paths = paths | {relative}
    return paths


def is_normalized_release_path(value: str) -> bool:
    if not value or "\\" in value or any(ord(character) < 32 for character in value):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and "." not in path.parts
        and ".." not in path.parts
        and str(path) == value
    )


def declared_path_exists_safely(value: str, public_paths: set[str]) -> bool:
    path = ROOT / value
    try:
        info = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return False
    if stat.S_ISREG(info.st_mode):
        return value in public_paths
    if stat.S_ISDIR(info.st_mode):
        prefix = f"{value}/"
        return value in public_paths and any(item.startswith(prefix) for item in public_paths)
    return False


def path_covered_by_tokens(value: str, tokens: set[str]) -> bool:
    path = PurePosixPath(value)
    for token in tokens:
        container = PurePosixPath(token)
        if path == container:
            return True
        try:
            path.relative_to(container)
        except ValueError:
            continue
        return True
    return False


def declared_path_is_tracked(value: str, tracked: set[str] | None) -> bool:
    if tracked is None:
        return True
    path = ROOT / value
    if path.is_file():
        return value in tracked
    if path.is_dir():
        prefix = f"{value}/"
        return any(item.startswith(prefix) for item in tracked)
    return False


def workflow_scalar(text: str, key: str) -> str | None:
    matches = re.findall(rf"(?m)^      {re.escape(key)}:\s+(.+?)\s*$", text)
    return matches[0] if len(matches) == 1 else None


def workflow_block_tokens(text: str, key: str, errors: list[str]) -> set[str]:
    lines = text.splitlines()
    tokens: list[str] = []
    for index, line in enumerate(lines):
        if line == f"      {key}: >-":
            for following in lines[index + 1 :]:
                if following and not following.startswith("        "):
                    break
                tokens.extend(following.split())
            break
    else:
        errors.append(f"{RELEASE_WORKFLOW}: missing block input {key}")
    duplicates = sorted({token for token in tokens if tokens.count(token) > 1})
    if duplicates:
        errors.append(f"{RELEASE_WORKFLOW}: duplicate {key} paths: {duplicates}")
    for token in tokens:
        if not is_normalized_release_path(token):
            errors.append(f"{RELEASE_WORKFLOW}: invalid {key} path token: {token}")
    return set(tokens)


def job_permissions(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line == "    permissions:":
            permissions: dict[str, str] = {}
            for following in lines[index + 1 :]:
                if following and not following.startswith("      "):
                    break
                if not following.strip():
                    continue
                match = re.fullmatch(r"      ([A-Za-z0-9_-]+): (read|write|none)", following)
                if match is None:
                    return None
                permissions[match.group(1)] = match.group(2)
            return permissions
    return None


def release_runtime_required_paths(
    manifest: dict[str, Any] | None,
    contract: dict[str, Any] | None,
) -> set[str]:
    required = set(BASE_RUNTIME_PATHS)
    if isinstance(manifest, dict):
        source_roots = manifest.get("source_roots")
        if isinstance(source_roots, dict):
            for value in source_roots.values():
                if isinstance(value, str) and value:
                    required = required | {value}
    if isinstance(contract, dict):
        setup_system = contract.get("setup_system")
        if isinstance(setup_system, dict):
            for key in ("catalog_root", "profile_root"):
                value = setup_system.get(key)
                if isinstance(value, str) and value:
                    required = required | {value}
        for key in ("manifest_ref", "version_ref"):
            value = contract.get(key)
            if isinstance(value, str) and "/" in value:
                required = required | {value.split("/", 1)[0]}
        runtime = contract.get("runtime_compatibility")
        if isinstance(runtime, dict):
            baseline_ref = runtime.get("baseline_ref")
            if isinstance(baseline_ref, str) and "/" in baseline_ref:
                required = required | {baseline_ref.split("/", 1)[0]}
    return required


def check_release_workflow(
    errors: list[str],
    manifest: dict[str, Any] | None,
    contract: dict[str, Any] | None,
) -> None:
    text = read_text(RELEASE_WORKFLOW, errors)
    if text is None:
        return
    public_paths = public_tree_paths(errors)
    tracked = public_paths

    uses = re.findall(r"(?m)^    uses:\s+(\S+)(?:\s+#\s*(\S+))?\s*$", text)
    if uses != [(RELEASE_SUPPLY_CHAIN_CALLER, RELEASE_SUPPLY_CHAIN_VERSION_COMMENT)]:
        errors.append(f"{RELEASE_WORKFLOW}: reusable release caller pin mismatch")
    if re.search(r"(?m)^permissions:\s+\{\}\s*$", text) is None:
        errors.append(f"{RELEASE_WORKFLOW}: top-level permissions must be empty")
    if job_permissions(text) != RELEASE_JOB_PERMISSIONS:
        errors.append(f"{RELEASE_WORKFLOW}: publish job permissions mismatch")
    if workflow_scalar(text, "version") != "${{ github.ref_name }}":
        errors.append(f"{RELEASE_WORKFLOW}: release version input mismatch")
    if workflow_scalar(text, "package_name") != PRODUCT_NAME:
        errors.append(f"{RELEASE_WORKFLOW}: package_name input mismatch")

    archive_paths = workflow_block_tokens(text, "archive_paths", errors)
    runtime_paths = workflow_block_tokens(text, "runtime_paths", errors)
    for path in sorted(REQUIRED_CLAUDE_RUNTIME_PATHS):
        if path not in archive_paths:
            errors.append(f"{RELEASE_WORKFLOW}: archive_paths must explicitly include {path}")
        if path not in runtime_paths:
            errors.append(f"{RELEASE_WORKFLOW}: runtime_paths must explicitly include {path}")
    missing_archive = sorted(REQUIRED_ARCHIVE_PATHS - archive_paths)
    if missing_archive:
        errors.append(f"{RELEASE_WORKFLOW}: archive_paths missing {missing_archive}")
    required_runtime = release_runtime_required_paths(manifest, contract)
    missing_runtime = sorted(
        path for path in required_runtime if not path_covered_by_tokens(path, runtime_paths)
    )
    if missing_runtime:
        errors.append(f"{RELEASE_WORKFLOW}: runtime_paths missing {missing_runtime}")
    for token_set_name, token_set in (
        ("archive_paths", archive_paths),
        ("runtime_paths", runtime_paths),
    ):
        for token in sorted(token_set):
            if not declared_path_exists_safely(token, public_paths):
                errors.append(
                    f"{RELEASE_WORKFLOW}: {token_set_name} path is missing or unsafe: {token}"
                )
            elif not declared_path_is_tracked(token, tracked):
                errors.append(f"{RELEASE_WORKFLOW}: {token_set_name} path is not tracked: {token}")
    for token in sorted(runtime_paths):
        if not path_covered_by_tokens(token, archive_paths):
            errors.append(f"{RELEASE_WORKFLOW}: runtime path is outside archive: {token}")
    public_docs = {
        path for path in public_paths if path.endswith(".md") or path.startswith("docs/")
    }
    for path in sorted(public_docs):
        if not path_covered_by_tokens(path, archive_paths):
            errors.append(f"{RELEASE_WORKFLOW}: public documentation not archived: {path}")


def read_build_version(errors: list[str]) -> str | None:
    text = read_text("VERSION", errors)
    if text is None:
        return None
    build_version = text.strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", build_version):
        errors.append("VERSION: invalid semantic version")
        return None
    return build_version


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
    return f"setups/nddev-builder/plugins/nddev-builder/{relative[len(prefix) :]}"


def is_projected_local_reference(raw: str) -> bool:
    if "\n" in raw or raw.startswith(("http://", "https://", "~", "$", "<")):
        return False
    if raw.startswith(("./", "../", "references/")):
        return True
    return raw.startswith("nddev-builder/references/")


def check_projected_local_references(text: str, relative: str, errors: list[str]) -> None:
    base = (ROOT / relative).parent
    for raw in re.findall(r"`([^`]+)`", text):
        if not is_projected_local_reference(raw):
            continue
        resolved = (base / raw).resolve()
        try:
            display = resolved.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"{relative}: projected reference escapes repository: {raw}")
            continue
        if not resolved.is_file():
            errors.append(f"{relative}: unresolved projected local reference {raw}: {display}")


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
            if (
                not isinstance(profile.get("description"), str)
                or not profile["description"].strip()
            ):
                errors.append(f"profiles/{profile_id}/profile.json: description required")
        if settings != expected:
            errors.append(f"profiles/{profile_id}/settings.json: settings payload mismatch")


def check_setup_toolkit(errors: list[str]) -> None:
    setup = load_json("setups/nddev-builder/setup.json", errors)
    if setup is not None:
        if set(setup) != {
            "schema_version",
            "id",
            "description",
            "managed_files",
            "builder_enabled",
        }:
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
        source_relative = source_for_builder_target(managed)
        text = read_text(source_relative, errors)
        if text is None:
            continue
        check_projected_local_references(text, source_relative, errors)
        if managed.endswith("/SKILL.md"):
            metadata = parse_frontmatter(text, source_relative, errors)
            if set(metadata) != {"name", "description"}:
                errors.append(f"{source_relative}: skill frontmatter keys mismatch")
            folder_name = Path(managed).parent.name
            if metadata.get("name") != folder_name:
                errors.append(f"{source_relative}: skill name must match folder")
            if not metadata.get("description", "").strip():
                errors.append(f"{source_relative}: description required")
            for forbidden in ("validation/nddev-", ".serena/", "release-evidence"):
                if forbidden in text:
                    errors.append(f"{source_relative}: private artifact reference {forbidden}")
        if re.search(r"\b\d+\.\d+\.\d+\b", text):
            errors.append(f"{source_relative}: volatile version literal")
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
        metadata = parse_frontmatter(
            agent, "setups/nddev-builder/plugins/nddev-builder/agents/nddev-builder.md", errors
        )
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
        if version.get("python_requires") != ">=3.9":
            errors.append("build/version.json: python_requires must be >=3.9")
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
        for command in (
            "update",
            "migrate",
            "software-status",
            "install-cli",
            "update-cli",
            "remove-cli",
        ):
            if command not in policy.get("json_supported", []):
                errors.append(f"build/manifest.json: command_policy missing {command}")
        launch = manifest.get("runtime_launch", {})
        validate_launch_scope("build/manifest.json", launch, errors)
        if launch.get("managed_override_args_blocked") != MANAGED_LAUNCH_OPTION_NAMES:
            errors.append("build/manifest.json: launch override policy mismatch")
        for key in (
            "target_lock_held_through_child",
            "immediate_executable_digest_recheck",
            "lifecycle_mutations_blocked_while_child_runs",
        ):
            if launch.get(key) is not True:
                errors.append(f"build/manifest.json: runtime_launch.{key} must be true")
        if launch.get("target_lock_mechanism") != "persistent-target-internal-flock-file":
            errors.append("build/manifest.json: target lock mechanism mismatch")
        if (
            launch.get("authoritative_lock_mechanism")
            != "monotonic-product-and-canonical-target-bootstrap-flock-files"
        ):
            errors.append("build/manifest.json: authoritative lock mechanism mismatch")
        if launch.get("read_only_cold_orphan_target_anchors_fail_closed") is not True:
            errors.append("build/manifest.json: read-only cold orphan target anchor policy missing")
        if (
            launch.get("read_only_cold_product_namespace_must_be_empty_without_global_lock")
            is not True
        ):
            errors.append("build/manifest.json: read-only cold product namespace policy missing")
        if launch.get("external_lock_binding") != "atomic-no-replace-product-namespaced-json":
            errors.append("build/manifest.json: external lock binding mismatch")
        if launch.get("external_lock_persistent") is not True:
            errors.append("build/manifest.json: external lock persistence must be true")
        if launch.get("external_lock_exposed_to_child") is not False:
            errors.append("build/manifest.json: external lock must not be exposed to child")
        if launch.get("target_internal_lock_role") != "target-local-state":
            errors.append("build/manifest.json: target internal lock role mismatch")
        if launch.get("executable_handoff") != "write-protected-verified-path":
            errors.append("build/manifest.json: executable handoff mismatch")
        if launch.get("protected_path_scope") != "lock-and-artifact-directories-only":
            errors.append("build/manifest.json: protected path scope mismatch")
        if launch.get("runtime_state_writable_during_child") is not True:
            errors.append("build/manifest.json: runtime state writability must be true")
        if launch.get("portable_fd_execution") is not False:
            errors.append("build/manifest.json: portable fd execution claim must be false")
        if launch.get("same_uid_chmod_resistance") is not False:
            errors.append("build/manifest.json: same-UID chmod resistance claim must be false")
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
        if "remove-cli" not in str(software.get("remove_command")):
            errors.append("build/manifest.json: software remove command mismatch")
        if software.get("npm") is not None or software.get("pip") is not None:
            errors.append("build/manifest.json: npm/pip must stay null")
        cleanup = manifest.get("cleanup_policy", {})
        if cleanup.get("immutable_pending_journal") is not True:
            errors.append("build/manifest.json: cleanup journal must be immutable pending")
        if cleanup.get("read_only_repairs") is not False:
            errors.append("build/manifest.json: read-only cleanup repair must be false")
        if cleanup.get("top_level_result_field") != "cleanup_pending":
            errors.append("build/manifest.json: cleanup result field mismatch")
        platform_support = manifest.get("platform_support", {})
        if platform_support.get("supported_hosts") != [
            "macos-arm64",
            "macos-x64",
            "ubuntu-glibc-arm64",
            "ubuntu-glibc-x64",
        ]:
            errors.append("build/manifest.json: supported host ids mismatch")
        if platform_support.get("unsupported_categories") != [
            "windows",
            "non-ubuntu-linux",
            "linux-musl",
            "unsupported-architecture",
        ]:
            errors.append("build/manifest.json: unsupported host categories mismatch")
        if platform_support.get("official_unsupported_platforms") != {
            "windows": ["windows_arm64", "windows_amd64"]
        }:
            errors.append("build/manifest.json: official unsupported platforms mismatch")
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
        launch = contract.get("runtime_launch", {})
        validate_launch_scope("config/nddev-contract.json", launch, errors)
        if launch.get("direct_command") is not None:
            errors.append("config/nddev-contract.json: runtime_launch.direct_command must be null")
        for key in (
            "target_lock_held_through_child",
            "immediate_executable_digest_recheck",
            "lifecycle_mutations_blocked_while_child_runs",
        ):
            if launch.get(key) is not True:
                errors.append(f"config/nddev-contract.json: runtime_launch.{key} must be true")
        if launch.get("target_lock_mechanism") != "persistent-target-internal-flock-file":
            errors.append("config/nddev-contract.json: target lock mechanism mismatch")
        if (
            launch.get("authoritative_lock_mechanism")
            != "monotonic-product-and-canonical-target-bootstrap-flock-files"
        ):
            errors.append("config/nddev-contract.json: authoritative lock mechanism mismatch")
        if (
            launch.get("read_only_cold_product_namespace_must_be_empty_without_global_lock")
            is not True
        ):
            errors.append(
                "config/nddev-contract.json: read-only cold product namespace policy missing"
            )
        if launch.get("external_lock_binding") != "atomic-no-replace-product-namespaced-json":
            errors.append("config/nddev-contract.json: external lock binding mismatch")
        if launch.get("external_lock_persistent") is not True:
            errors.append("config/nddev-contract.json: external lock persistence must be true")
        if launch.get("external_lock_exposed_to_child") is not False:
            errors.append("config/nddev-contract.json: external lock must not be exposed to child")
        if launch.get("target_internal_lock_role") != "target-local-state":
            errors.append("config/nddev-contract.json: target internal lock role mismatch")
        if launch.get("executable_handoff") != "write-protected-verified-path":
            errors.append("config/nddev-contract.json: executable handoff mismatch")
        if launch.get("protected_path_scope") != "lock-and-artifact-directories-only":
            errors.append("config/nddev-contract.json: protected path scope mismatch")
        if launch.get("runtime_state_writable_during_child") is not True:
            errors.append("config/nddev-contract.json: runtime state writability must be true")
        if launch.get("portable_fd_execution") is not False:
            errors.append("config/nddev-contract.json: portable fd execution claim must be false")
        if launch.get("same_uid_chmod_resistance") is not False:
            errors.append(
                "config/nddev-contract.json: same-UID chmod resistance claim must be false"
            )
        safety = contract.get("safety", {})
        if safety.get("target_lock") != ".nddev-antigravity-cli-lock":
            errors.append("config/nddev-contract.json: target lock must be target-internal")
        if safety.get("read_only_cold_orphan_target_anchors_fail_closed") is not True:
            errors.append(
                "config/nddev-contract.json: read-only cold orphan target anchor policy missing"
            )
        if (
            safety.get("read_only_cold_product_namespace_must_be_empty_without_global_lock")
            is not True
        ):
            errors.append(
                "config/nddev-contract.json: read-only cold product namespace policy missing"
            )
        if safety.get("backup_pool_location") != ".nddev-antigravity-cli-backups":
            errors.append("config/nddev-contract.json: backup pool must be target-internal")
        if safety.get("backup_pool_lock") != ".nddev-antigravity-cli-backups-lock":
            errors.append("config/nddev-contract.json: backup pool lock must be target-internal")
        cleanup = contract.get("cleanup_policy", {})
        if cleanup.get("immutable_pending_journal") is not True:
            errors.append("config/nddev-contract.json: cleanup journal must be immutable pending")
        if cleanup.get("read_only_repairs") is not False:
            errors.append("config/nddev-contract.json: read-only cleanup repair must be false")
        platform_support = contract.get("platform_support", {})
        if platform_support.get("supported_hosts") != [
            "macos-arm64",
            "macos-x64",
            "ubuntu-glibc-arm64",
            "ubuntu-glibc-x64",
        ]:
            errors.append("config/nddev-contract.json: supported host ids mismatch")
        if platform_support.get("official_unsupported_platforms") != {
            "windows": ["windows_arm64", "windows_amd64"]
        }:
            errors.append("config/nddev-contract.json: official unsupported platforms mismatch")
    if baseline is not None:
        if baseline.get("schema_version") != 2:
            errors.append("baseline schema_version must be 2")
        if baseline.get("verified_date") != "2026-07-28":
            errors.append("baseline verified_date mismatch")
        if version is not None:
            release = baseline.get("release", {})
            if release.get("tag") != version.get("antigravity_cli_release_tag"):
                errors.append("baseline release tag mismatch")
        forbidden_observation_fields = {
            "published_at",
            "latest_api",
        }
        if forbidden_observation_fields.intersection(baseline.get("release", {})):
            errors.append("baseline release contains observation-only metadata")
        if "observed_flags" in baseline.get("install_script", {}):
            errors.append("baseline install script contains observation-only flags")
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
        expected_assets = {
            "agy_cli_linux_arm64.tar.gz": (
                "linux_arm64",
                "supported-vendor-artifact-for-ubuntu-glibc-arm64",
                49147372,
                "e75cebb03fce0fcad7d3bb682eb84c356a3c50ff8fb3dc4a89d2051f34fca0ab",
            ),
            "agy_cli_linux_x64.tar.gz": (
                "linux_amd64",
                "supported-vendor-artifact-for-ubuntu-glibc-x64",
                52535983,
                "e92e6215532b3ce84455e341944067753ad90f6d24cebcec8002ce137e5162ce",
            ),
            "agy_cli_mac_arm64.tar.gz": (
                "darwin_arm64",
                "supported-vendor-artifact-for-macos-arm64",
                46268913,
                "622d85db88bcfbf060aa4cbeaadcf2a287420f31236c1efb287409a949ccab25",
            ),
            "agy_cli_mac_x64.tar.gz": (
                "darwin_amd64",
                "supported-vendor-artifact-for-macos-x64",
                50542433,
                "76afe4622132596f68557ef4531ec2e2dcd40e8025f6fb4435a273ce2eec0027",
            ),
        }
        assets = baseline.get("release_assets")
        if not isinstance(assets, dict) or sorted(assets) != sorted(expected_assets):
            errors.append("baseline release assets must cover supported product artifacts only")
        else:
            for name, (platform_id, support, size, digest) in expected_assets.items():
                meta = assets.get(name, {})
                if meta.get("platform") != platform_id:
                    errors.append(f"baseline {name}: platform mismatch")
                if meta.get("support") != support:
                    errors.append(f"baseline {name}: support mismatch")
                if meta.get("size") != size:
                    errors.append(f"baseline {name}: size mismatch")
                if meta.get("sha256") != digest:
                    errors.append(f"baseline {name}: sha256 mismatch")
        script = baseline.get("install_script", {})
        if not re.fullmatch(r"[0-9a-f]{64}", str(script.get("sha256", ""))):
            errors.append("baseline install_script sha256 missing")
    for relative in (
        "README.md",
        "AGENTS.md",
        CLAUDE_BRIDGE_PATH,
        "CHANGELOG.md",
        "docs/software-lifecycle.md",
        "SECURITY.md",
        "cli-tools/nddev_antigravity_cli.py",
    ):
        read_text(relative, errors)
    for workflow in WORKFLOWS:
        read_text(f".github/workflows/{workflow}", errors)
    check_release_workflow(errors, manifest, contract)


def check_claude_bridge(errors: list[str]) -> None:
    bridge_dir = ROOT / CLAUDE_BRIDGE_DIR
    try:
        dir_info = bridge_dir.lstat()
    except OSError as exc:
        errors.append(f"{CLAUDE_BRIDGE_DIR}: cannot inspect Claude bridge directory: {exc}")
        return
    if not stat.S_ISDIR(dir_info.st_mode):
        errors.append(f"{CLAUDE_BRIDGE_DIR}: Claude bridge directory must be a real directory")
        return
    entries = sorted(path.name for path in bridge_dir.iterdir())
    if entries != ["CLAUDE.md"]:
        errors.append(f"{CLAUDE_BRIDGE_DIR}: must contain only CLAUDE.md")
    bridge = ROOT / CLAUDE_BRIDGE_PATH
    try:
        info = bridge.lstat()
    except OSError as exc:
        errors.append(f"{CLAUDE_BRIDGE_PATH}: cannot inspect Claude bridge: {exc}")
        return
    if not stat.S_ISREG(info.st_mode):
        errors.append(f"{CLAUDE_BRIDGE_PATH}: Claude bridge must be a regular file")
        return
    try:
        content = bridge.read_bytes()
    except OSError as exc:
        errors.append(f"{CLAUDE_BRIDGE_PATH}: cannot read Claude bridge: {exc}")
        return
    if content != CLAUDE_BRIDGE_BYTES:
        errors.append(f"{CLAUDE_BRIDGE_PATH}: exact bridge bytes mismatch")


def check_no_production_test_switches(errors: list[str]) -> None:
    source = read_text("cli-tools/nddev_antigravity_cli.py", errors)
    if source is None:
        return
    forbidden_patterns = {
        r"NDDEV_[A-Z0-9_]*TEST[A-Z0-9_]*": "NDDEV test environment switch",
        r"NDDEV_[A-Z0-9_]*(?:BOOTSTRAP|LOCK|ROOT|TEMP|TMP|OVERRIDE)[A-Z0-9_]*": "NDDEV public lock/root override",
        r"ANTIGRAVITY_[A-Z0-9_]*(?:BOOTSTRAP|LOCK|ROOT|TEMP|TMP|OVERRIDE)[A-Z0-9_]*": "Antigravity public lock/root override",
        r"\bALLOW_TEST[A-Z0-9_]*\b": "ALLOW_TEST switch",
        r"\bTEST_(?:ARTIFACT|FAIL|TIMEOUT|SOURCE)[A-Z0-9_]*\b": "test behavior switch",
        r"\b(?:FIXTURE|SOURCE)_OVERRIDE[A-Z0-9_]*\b": "fixture/source override",
        r"file://": "local fixture source support",
        r"injected failure": "artificial failure hook",
    }
    for pattern, label in forbidden_patterns.items():
        if re.search(pattern, source):
            errors.append(f"manager exposes forbidden production test path: {label}")


def check_runtime_lock_source(errors: list[str]) -> None:
    source = read_text("cli-tools/nddev_antigravity_cli.py", errors)
    if source is None:
        return
    required_fragments = (
        "fcntl.flock",
        "fcntl.LOCK_EX | fcntl.LOCK_NB",
        "O_NOFOLLOW",
        "TARGET_LOCK_FILE_NAME",
        "EXTERNAL_LOCK_POOL_PREFIX",
        "external_target_lock",
        "system_temp_root",
        "external_lock_binding",
        "require_external_lock_file_identity",
        "validate_external_lock_binding",
        "atomic_rename_no_replace",
        "BOOTSTRAP_GLOBAL_LOCK_NAME",
        "protected_launch_handoff",
        "subprocess.Popen",
        "caller_workspace = resolve_caller_workspace()",
        "cwd=str(workspace)",
        '"launch_scope": launch_scope_status()',
    )
    for fragment in required_fragments:
        if fragment not in source:
            errors.append(f"manager runtime lock source missing {fragment}")
    forbidden_claims = ("fexecve", "execveat")
    for fragment in forbidden_claims:
        if fragment in source:
            errors.append(f"manager source must not claim portable fd execution: {fragment}")


def check_read_only_cold_bootstrap_source(errors: list[str]) -> None:
    source = read_text("cli-tools/nddev_antigravity_cli.py", errors)
    if source is None:
        return
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        errors.append(f"manager source syntax error: {exc}")
        return
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    target_lock = functions.get("target_lock")
    read_only_payload = functions.get("read_only_target_payload")
    cold_snapshot = functions.get("cold_read_external_namespace_snapshot")
    namespace_scan = functions.get("scan_external_lock_namespace")
    if target_lock is None:
        errors.append("manager source missing target_lock")
        return
    if read_only_payload is None:
        errors.append("manager source missing read_only_target_payload")
        return
    if cold_snapshot is None:
        errors.append("manager source missing cold read external namespace snapshot")
        return
    if namespace_scan is None:
        errors.append("manager source missing cold read external namespace scanner")
        return

    target_names = {node.id for node in ast.walk(target_lock) if isinstance(node, ast.Name)}
    for required in (
        "cold_read_external_namespace_snapshot",
        "body_completed",
        "BootstrapColdReadRace",
    ):
        if required not in target_names:
            errors.append(f"target_lock missing read-only cold bootstrap guard: {required}")
    target_calls = {
        node.func.id
        for node in ast.walk(target_lock)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    if "external_global_anchor_exists" in target_calls:
        errors.append("target_lock must not use stale global-only cold-read retry checks")
    payload_names = {node.id for node in ast.walk(read_only_payload) if isinstance(node, ast.Name)}
    for required in ("BootstrapColdReadRace", "callback", "target_lock"):
        if required not in payload_names:
            errors.append(f"read_only_target_payload missing stale-result retry guard: {required}")

    snapshot_calls = {
        node.func.id
        for node in ast.walk(cold_snapshot)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for required in (
        "open_owner_directory_fd",
        "scan_external_lock_namespace",
    ):
        if required not in snapshot_calls:
            errors.append(f"cold read snapshot missing bounded no-create validation: {required}")
    scan_calls = {
        node.func.id
        for node in ast.walk(namespace_scan)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for required in (
        "external_lock_namespace_entry_role",
        "external_lock_file_state_token",
    ):
        if required not in scan_calls:
            errors.append(f"cold read scanner missing product namespace validation: {required}")
    for forbidden in (
        "open_external_global_lock",
        "create_external_lock_file_atomic",
        "fsync_directory",
        "unlink_path",
        "unlink_path_if_exists",
        "mkdir_owner_private",
    ):
        if forbidden in snapshot_calls:
            errors.append(f"cold read snapshot must not mutate or repair namespace: {forbidden}")
        if forbidden in scan_calls:
            errors.append(f"cold read scanner must not mutate or repair namespace: {forbidden}")


def check_no_current_forbidden_surfaces(errors: list[str]) -> None:
    for forbidden_path in (
        "setups/safe",
        "setups/full-auto",
        "setups/" + "bal" + "anced",
    ):
        if (ROOT / forbidden_path).exists():
            errors.append(f"retired setup path must be absent: {forbidden_path}")
    for relative in ("README.md", "docs/software-lifecycle.md"):
        text = read_text(relative, errors)
        if text is None:
            continue
        unsupported_platform = "Win" + "dows"
        lower_text = text.lower()
        if (
            unsupported_platform in text or unsupported_platform.lower() in lower_text
        ) and "unsupported" not in lower_text:
            errors.append(f"{relative}: Windows text must be explicitly unsupported")
        retired_profile = "bal" + "anced"
        if retired_profile in text:
            errors.append(f"{relative}: retired setup/profile text must be absent")


def main() -> int:
    errors: list[str] = []
    build_version = read_build_version(errors)
    check_profiles(errors)
    check_setup_toolkit(errors)
    check_contracts(errors, build_version)
    check_claude_bridge(errors)
    check_no_production_test_switches(errors)
    check_runtime_lock_source(errors)
    check_read_only_cold_bootstrap_source(errors)
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
