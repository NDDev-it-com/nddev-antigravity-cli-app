#!/usr/bin/env python3
"""Validate public nddev-antigravity-cli-app contracts without private inputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SETUP_IDS = ["safe", "balanced", "full-auto"]
MANAGED_LAUNCH_OPTION_NAMES = [
    "--sandbox",
    "--dangerously-skip-permissions",
    "--mode",
    "--cwd",
]
MANAGED_FILES = [
    ".gemini/antigravity-cli/settings.json",
    ".gemini/antigravity-cli/plugins/nddev-builder/plugin.json",
    ".gemini/antigravity-cli/plugins/nddev-builder/skills/nddev-builder/SKILL.md",
    ".gemini/antigravity-cli/plugins/nddev-builder/agents/nddev-builder.md",
    ".gemini/antigravity-cli/plugins/nddev-builder/rules/nddev-builder.md",
]
WORKFLOWS = [
    "actionlint.yml",
    "codeql.yml",
    "dependency-review.yml",
    "release.yml",
    "scorecard.yml",
    "secret-scan.yml",
    "zizmor.yml",
]
EXPECTED_SETTINGS = {
    "safe": {
        "allowNonWorkspaceAccess": False,
        "artifactReviewPolicy": "asks-for-review",
        "enableTerminalSandbox": True,
        "toolPermission": "strict",
    },
    "balanced": {
        "allowNonWorkspaceAccess": False,
        "artifactReviewPolicy": "agent-decides",
        "enableTerminalSandbox": True,
        "toolPermission": "proceed-in-sandbox",
    },
    "full-auto": {
        "allowNonWorkspaceAccess": True,
        "artifactReviewPolicy": "always-proceed",
        "enableTerminalSandbox": True,
        "toolPermission": "always-proceed",
    },
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


def check_text(relative: str, errors: list[str]) -> None:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"missing required text file: {relative}")
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{relative}: unreadable text: {exc}")
        return
    if not text.strip() or not text.endswith("\n"):
        errors.append(f"{relative}: must be non-empty LF-terminated text")


def check_setup(setup_id: str, errors: list[str]) -> None:
    root = ROOT / "setups" / setup_id
    metadata = load_json(f"setups/{setup_id}/setup.json", errors)
    settings = load_json(f"setups/{setup_id}/settings.json", errors)
    plugin = load_json(f"setups/{setup_id}/plugins/nddev-builder/plugin.json", errors)
    if metadata is not None:
        if metadata.get("id") != setup_id:
            errors.append(f"setups/{setup_id}/setup.json: id mismatch")
        if metadata.get("managed_files") != MANAGED_FILES:
            errors.append(f"setups/{setup_id}/setup.json: managed_files mismatch")
        if metadata.get("managed_settings") != EXPECTED_SETTINGS[setup_id]:
            errors.append(f"setups/{setup_id}/setup.json: managed_settings mismatch")
        if metadata.get("builder_enabled") is not True:
            errors.append(f"setups/{setup_id}/setup.json: builder must be enabled")
    if settings != EXPECTED_SETTINGS[setup_id]:
        errors.append(f"setups/{setup_id}/settings.json: settings mismatch")
    if plugin is not None:
        if plugin.get("$schema") != "https://antigravity.google/schemas/v1/plugin.json":
            errors.append(f"setups/{setup_id}/plugin.json: official schema URL required")
        if plugin.get("name") != "nddev-builder":
            errors.append(f"setups/{setup_id}/plugin.json: name must be nddev-builder")
        if sorted(plugin) != ["$schema", "description", "name"]:
            errors.append(f"setups/{setup_id}/plugin.json: unsupported manifest keys")
    for relative in (
        "plugins/nddev-builder/skills/nddev-builder/SKILL.md",
        "plugins/nddev-builder/agents/nddev-builder.md",
        "plugins/nddev-builder/rules/nddev-builder.md",
    ):
        check_text(f"setups/{setup_id}/{relative}", errors)
    if not root.is_dir():
        errors.append(f"setups/{setup_id}: setup directory missing")


def main() -> int:
    errors: list[str] = []
    version_text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/antigravity-cli-baseline.json", errors)

    if version is not None:
        if version.get("build_version") != version_text:
            errors.append("VERSION disagrees with build/version.json:build_version")
        if version.get("antigravity_cli_tested") != "1.1.7":
            errors.append("build/version.json: antigravity_cli_tested must be 1.1.7")
    if manifest is not None:
        if manifest.get("build_version") != version_text:
            errors.append("build/manifest.json: build_version mismatch")
        if manifest.get("setup_ids") != SETUP_IDS:
            errors.append("build/manifest.json: setup_ids mismatch")
        policy = manifest.get("command_policy", {})
        for command in ("software-status", "install-cli", "update-cli"):
            if command not in policy.get("json_supported", []):
                errors.append(f"build/manifest.json: command_policy missing {command}")
        software = manifest.get("software_install")
        if not isinstance(software, dict):
            errors.append("build/manifest.json: software_install object required")
        elif software.get("mechanism") != "official-github-release-artifact":
            errors.append("build/manifest.json: official artifact software install required")
        elif software.get("npm") is not None or software.get("pip") is not None:
            errors.append("build/manifest.json: npm/pip software install must stay null")
        elif software.get("artifact_pin_fields") != ["sha256", "size"]:
            errors.append("build/manifest.json: artifact pins must include sha256 and size")
        builder = manifest.get("builder")
        if not isinstance(builder, dict) or builder.get("projection") != "native-plugin":
            errors.append("build/manifest.json: native-plugin builder projection required")
        elif builder.get("marketplace") is not None:
            errors.append("build/manifest.json: marketplace must be null")
    if contract is not None:
        if "skeleton" in contract:
            errors.append("config/nddev-contract.json: skeleton status is not allowed")
        if contract.get("manifest_ref") != "build/manifest.json":
            errors.append("config/nddev-contract.json: manifest_ref mismatch")
        if contract.get("managed_state", {}).get("target_model") != "isolated-home":
            errors.append("config/nddev-contract.json: isolated-home target model required")
        software = contract.get("software_install")
        if not isinstance(software, dict) or software.get("supported") is not True:
            errors.append("config/nddev-contract.json: software_install supported object required")
        elif software.get("mechanism") != "official-github-release-artifact":
            errors.append("config/nddev-contract.json: official artifact software install required")
        elif software.get("npm") is not None or software.get("pip") is not None:
            errors.append("config/nddev-contract.json: npm/pip software install must stay null")
        elif software.get("artifact_pin_fields") != ["sha256", "size"]:
            errors.append("config/nddev-contract.json: artifact pins must include sha256 and size")
        builder = contract.get("builder")
        if not isinstance(builder, dict) or builder.get("projection") != "native-plugin":
            errors.append("config/nddev-contract.json: native-plugin builder projection required")
        elif builder.get("marketplace") is not None:
            errors.append("config/nddev-contract.json: marketplace must be null")
    if baseline is not None:
        if version is not None:
            release = baseline.get("release", {})
            if release.get("tag") != version.get("antigravity_cli_release_tag"):
                errors.append("references/antigravity-cli-baseline.json: release tag mismatch")
            if release.get("published_at") != version.get("antigravity_cli_release_published_at"):
                errors.append(
                    "references/antigravity-cli-baseline.json: release timestamp mismatch"
                )
        if baseline.get("configuration", {}).get("marketplace") is not None:
            errors.append("references/antigravity-cli-baseline.json: marketplace must be null")
        if baseline.get("runtime", {}).get("executable") != "agy":
            errors.append("references/antigravity-cli-baseline.json: executable must be agy")
        software = baseline.get("software_install")
        if not isinstance(software, dict):
            errors.append("references/antigravity-cli-baseline.json: software_install required")
        elif software.get("mechanism") != "official-github-release-artifact":
            errors.append("references/antigravity-cli-baseline.json: official artifact install required")
        elif software.get("npm") is not None or software.get("pip") is not None:
            errors.append("references/antigravity-cli-baseline.json: npm/pip must stay null")
        assets = baseline.get("release", {}).get("assets")
        if not isinstance(assets, dict) or len(assets) != 6:
            errors.append("references/antigravity-cli-baseline.json: exact six release assets required")
        else:
            for name, meta in assets.items():
                if not name.startswith("agy_cli_"):
                    errors.append(f"references/antigravity-cli-baseline.json: unexpected asset {name}")
                if not isinstance(meta, dict) or len(str(meta.get("sha256", ""))) != 64:
                    errors.append(f"references/antigravity-cli-baseline.json: missing sha256 for {name}")
                if not isinstance(meta, dict) or not isinstance(meta.get("size"), int):
                    errors.append(f"references/antigravity-cli-baseline.json: missing size for {name}")

    for setup_id in SETUP_IDS:
        check_setup(setup_id, errors)
    for payload_name, payload in (("manifest", manifest), ("contract", contract)):
        if payload is None:
            continue
        launch = payload.get("runtime_launch", {})
        if launch.get("executable") != "agy":
            errors.append(f"{payload_name}: runtime_launch.executable must be agy")
        if launch.get("managed_executable") != "bin/agy":
            errors.append(f"{payload_name}: runtime_launch.managed_executable must be bin/agy")
        if launch.get("path_fallback") is not False:
            errors.append(f"{payload_name}: runtime launch PATH fallback must be false")
        if launch.get("requires_current_target_owned_software") is not True:
            errors.append(
                f"{payload_name}: launch must require current target-owned software"
            )
        if launch.get("managed_override_args_blocked") != MANAGED_LAUNCH_OPTION_NAMES:
            errors.append(f"{payload_name}: managed launch override flag policy mismatch")
    for relative in (
        "README.md",
        "AGENTS.md",
        "CHANGELOG.md",
        "docs/software-lifecycle.md",
        "SECURITY.md",
        "cli-tools/nddev_antigravity_cli.py",
    ):
        check_text(relative, errors)
    for workflow in WORKFLOWS:
        check_text(f".github/workflows/{workflow}", errors)

    if errors:
        print(f"validate_public_contracts.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
