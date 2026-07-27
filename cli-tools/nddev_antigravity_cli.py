#!/usr/bin/env python3
"""Target-explicit Antigravity CLI setup manager for NDDev.

The manager writes one content setup plus one permission profile into an
explicit isolated HOME target. It never infers or mutates the caller's live
``~/.gemini`` or Antigravity CLI state.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import platform as py_platform
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
PROFILE_ROOT = ROOT / "profiles"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()

PRODUCT_NAME = "nddev-antigravity-cli-app"
STAMP_NAME = "NDDEV-ANTIGRAVITY-CLI-SETUP.json"
BACKUP_NAME = "NDDEV-ANTIGRAVITY-CLI-BACKUP.json"
SOFTWARE_STAMP_NAME = "NDDEV-ANTIGRAVITY-CLI-SOFTWARE.json"

STAMP_SCHEMA = 2
LEGACY_STAMP_SCHEMA = 1
BACKUP_SCHEMA = 2
LEGACY_BACKUP_SCHEMA = 1
SOFTWARE_STAMP_SCHEMA = 2

MAX_BACKUPS = 10
OWNER_FILE_MODE = 0o600
OWNER_DIR_MODE = 0o700
OWNER_READ_EXEC_DIR_MODE = 0o500
OWNER_EXEC_MODE = 0o700
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 1024 * 1024
SOFTWARE_ARTIFACT_MAX_BYTES = 300 * 1024 * 1024
DEFAULT_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
TARGET_LOCK_DIR_NAME = ".nddev-antigravity-cli-lock"
TARGET_LOCK_FILE_NAME = "lock"

CLI_VERSION = "1.1.7"
CLI_COMMAND = "agy"
UPSTREAM_CLI_MEMBER_NAMES = frozenset({CLI_COMMAND, "antigravity"})

INSTALL_SCRIPT_URL = "https://antigravity.google/cli/install.sh"
INSTALL_SCRIPT_SHA256 = (
    "ee1ea43ce4e9e56356c4ab6dad907ef357ae4bdfcaadb682735909fb57c9c640"
)
MANIFEST_URL_TEMPLATE = (
    "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/"
    "manifests/{platform}.json"
)
OFFICIAL_MANIFESTS: dict[str, dict[str, str]] = {
    "darwin_amd64": {
        "version": "1.1.7",
        "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.1.7-5951805767680000/darwin-x64/cli_mac_x64.tar.gz",
        "sha512": "40ab64cd0f25febd4f48762d3fab619c23f0b4af30d7c95a83ebd34a7ad37b346ca2cd7d593b5d60aeaf838acdf3ee061e747d7ca1398e5fad9ffc567781ba31",
    },
    "darwin_arm64": {
        "version": "1.1.7",
        "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.1.7-5951805767680000/darwin-arm/cli_mac_arm64.tar.gz",
        "sha512": "712ff022a40616414b44a9044b09c7662a45b61fe5bada08bd00af97b66f1baa0a9374bb98137ed559e93a7499f8fa832d6558bfa37b20a9f612b5be245f31b7",
    },
    "linux_amd64": {
        "version": "1.1.7",
        "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.1.7-5951805767680000/linux-x64/cli_linux_x64.tar.gz",
        "sha512": "720d5a7ff256aa5dd6712513cd5eb6fe031cf9e7523a33bcbda7755120ced53bb64ff985b402ce068e5895e0ffb348c2632545039a1dde6daad591f164d5852f",
    },
    "linux_arm64": {
        "version": "1.1.7",
        "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.1.7-5951805767680000/linux-arm/cli_linux_arm64.tar.gz",
        "sha512": "6b42366c3926994785301af43e01f595c5b8e43eb521166d98478539368b0daafb3211000fb2280ade6a37da0a6c438ef28abc2c82b6c8263017b245878fc506",
    },
}

DEFAULT_SETUP_ID = "nddev-builder"
SETUP_IDS = (DEFAULT_SETUP_ID,)
DEFAULT_PROFILE_ID = "full-auto"
PROFILE_IDS = ("full-auto", "safe")
LEGACY_SETUP_IDS = frozenset({"safe", "bal" + "anced", "full-auto"})

SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
SHA512_PATTERN = re.compile(r"[0-9a-f]{128}\Z")

SETTINGS = ".gemini/antigravity-cli/settings.json"
BUILDER_ROOT = ".gemini/antigravity-cli/plugins/nddev-builder"
BUILDER_MANAGED_FILES = (
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
)
LEGACY_BUILDER_MANAGED_FILES = (
    f"{BUILDER_ROOT}/plugin.json",
    f"{BUILDER_ROOT}/skills/nddev-builder/SKILL.md",
    f"{BUILDER_ROOT}/agents/nddev-builder.md",
    f"{BUILDER_ROOT}/rules/nddev-builder.md",
)
MANAGED_FILES = (SETTINGS, *BUILDER_MANAGED_FILES)
LEGACY_MANAGED_FILES = (SETTINGS, *LEGACY_BUILDER_MANAGED_FILES)
SETTINGS_MANAGED_KEYS = (
    "toolPermission",
    "artifactReviewPolicy",
    "enableTerminalSandbox",
    "allowNonWorkspaceAccess",
    "permissions",
)

MANAGED_LAUNCH_OPTION_NAMES = (
    "--sandbox",
    "--dangerously-skip-permissions",
    "--permission-mode",
    "--mode",
    "--cwd",
    "--agent",
)

CURRENT_STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "profile_id",
    "canonical_target",
    "managed_files",
    "builder",
}
LEGACY_STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "canonical_target",
    "managed_files",
    "builder",
}
BACKUP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_stamp_schema",
    "source_build_version",
    "source_setup_id",
    "source_profile_id",
    "managed_files",
    "stamp_sha256",
}
LEGACY_BACKUP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_setup_id",
    "managed_files",
    "stamp_sha256",
}

SECRET_ENV_PREFIXES = (
    "GOOGLE_",
    "GEMINI_",
    "ANTIGRAVITY_",
    "AGY_",
    "ANTHROPIC_",
    "OPENAI_",
    "AWS_",
    "AZURE_",
)
SECRET_ENV_EXACT = {
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GIT_ASKPASS",
    "SSH_ASKPASS",
    "SSH_AUTH_SOCK",
    "BASH_ENV",
    "ENV",
    "PYTHONPATH",
    "NODE_OPTIONS",
}
SECRET_ENV_SUBSTRINGS = (
    "TOKEN",
    "API_KEY",
    "ACCESS_KEY",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
)
LOADER_ENV_PREFIXES = ("LD_", "DYLD_")


class ManagerError(Exception):
    """A structured user-facing lifecycle failure."""


class ConcurrentTargetChange(ManagerError):
    """A fail-closed target race or identity change."""


@dataclass(frozen=True)
class Setup:
    setup_id: str
    description: str
    managed_files: tuple[str, ...]
    builder_enabled: bool
    files: dict[str, bytes]


@dataclass(frozen=True)
class Profile:
    profile_id: str
    description: str
    default: bool
    settings: dict[str, Any]


@dataclass(frozen=True)
class FileSnapshot:
    content: bytes | None
    digest: str | None


def fail(message: str) -> NoReturn:
    raise ManagerError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha512_bytes(value: bytes) -> str:
    return hashlib.sha512(value).hexdigest()


def identity_of(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def owner_of(info: os.stat_result) -> int | None:
    return info.st_uid if hasattr(info, "st_uid") else None


def is_owner_only_file(info: os.stat_result) -> bool:
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        return False
    return not hasattr(os, "geteuid") or owner_of(info) == os.geteuid()


def is_owner_only_executable(info: os.stat_result) -> bool:
    if stat.S_IMODE(info.st_mode) != OWNER_EXEC_MODE:
        return False
    return not hasattr(os, "geteuid") or owner_of(info) == os.geteuid()


def safe_relative_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        fail(f"managed path is not safe: {relative}")
    return path


def reject_symlink_ancestors(root: Path, relative: str) -> None:
    current = root
    for part in safe_relative_path(relative).parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"managed parent must be a real directory: {current}")


def require_directory(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    return info


def require_regular_file(path: Path, label: str, *, owner_only: bool) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    if info.st_nlink != 1:
        fail(f"{label} must not have hard-link aliases")
    if owner_only and not is_owner_only_file(info):
        fail(f"{label} must be owned by the current user with mode 0600")
    return info


def require_executable_file(path: Path, label: str) -> os.stat_result:
    info = require_regular_file(path, label, owner_only=False)
    if not is_owner_only_executable(info):
        fail(f"{label} must be owned by the current user with mode 0700")
    return info


def read_regular_file(
    path: Path,
    label: str,
    *,
    owner_only: bool = False,
    max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES,
) -> tuple[bytes, os.stat_result]:
    before = require_regular_file(path, label, owner_only=owner_only)
    if before.st_size > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(before):
            raise ConcurrentTargetChange(f"{label} changed while it was opened")
        blocks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, 65536)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                fail(f"{label} exceeds the {max_bytes}-byte size limit")
            blocks.append(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    final = require_regular_file(path, label, owner_only=owner_only)
    if identity_of(final) != identity_of(before) or identity_of(after) != identity_of(before):
        raise ConcurrentTargetChange(f"{label} changed while it was read")
    return b"".join(blocks), final


def parse_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid JSON from {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def read_json_file(path: Path, label: str, *, owner_only: bool = False) -> dict[str, Any]:
    content, _ = read_regular_file(
        path,
        label,
        owner_only=owner_only,
        max_bytes=METADATA_MAX_BYTES,
    )
    return parse_json_object(content, label)


def validate_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        fail(f"{label} must be a non-empty string")
    return value


def validate_exact_int(value: Any, label: str) -> int:
    if type(value) is not int:
        fail(f"{label} must be an integer")
    return value


def validate_sha256_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        fail(f"{label} must be a lowercase SHA-256 digest")
    return value


def validate_id(value: Any, label: str) -> str:
    if not isinstance(value, str):
        fail(f"{label} must be a string")
    if not SETUP_ID_PATTERN.fullmatch(value):
        fail(f"invalid {label}: {value!r}")
    return value


def expected_settings_for_profile(profile_id: str) -> dict[str, Any]:
    if profile_id == "full-auto":
        return {
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
    if profile_id == "safe":
        return {
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
    fail(f"unsupported profile id: {profile_id}")


def source_for_builder_target(relative: str) -> str:
    prefix = f"{BUILDER_ROOT}/"
    if not relative.startswith(prefix):
        fail(f"builder file is outside the plugin root: {relative}")
    return f"plugins/nddev-builder/{relative[len(prefix):]}"


def validate_text_payload(content: bytes, label: str) -> None:
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail(f"{label} must be UTF-8: {exc}")
    if not content or not content.endswith(b"\n") or b"\r" in content:
        fail(f"{label} must be non-empty LF-terminated text")


def render_setup(setup_id: str) -> Setup:
    validate_id(setup_id, "setup id")
    if setup_id not in SETUP_IDS:
        fail(f"unknown setup: {setup_id}")
    setup_root = CATALOG_ROOT / setup_id
    if not setup_root.is_dir() or setup_root.is_symlink():
        fail(f"setup catalog entry is missing or unsafe: {setup_id}")
    metadata = read_json_file(setup_root / "setup.json", f"setup {setup_id} metadata")
    expected_keys = {"schema_version", "id", "description", "managed_files", "builder_enabled"}
    if set(metadata) != expected_keys:
        fail(f"setup {setup_id} metadata has invalid keys")
    if metadata["schema_version"] != 1 or metadata["id"] != setup_id:
        fail(f"setup {setup_id} metadata identity or schema is invalid")
    if metadata["managed_files"] != list(BUILDER_MANAGED_FILES):
        fail(f"setup {setup_id} managed file declaration is invalid")
    if metadata["builder_enabled"] is not True:
        fail(f"setup {setup_id} must enable the native nddev-builder plugin")
    if not isinstance(metadata["description"], str) or not metadata["description"].strip():
        fail(f"setup {setup_id} description must be non-empty")
    files: dict[str, bytes] = {}
    for relative in BUILDER_MANAGED_FILES:
        source = source_for_builder_target(relative)
        path = setup_root / safe_relative_path(source)
        content, _ = read_regular_file(path, f"setup {setup_id}/{source}")
        validate_text_payload(content, f"setup {setup_id}/{source}")
        files[relative] = content
    plugin = parse_json_object(files[f"{BUILDER_ROOT}/plugin.json"], "nddev-builder plugin.json")
    if plugin != {
        "$schema": "https://antigravity.google/schemas/v1/plugin.json",
        "name": "nddev-builder",
        "description": "NDDev setup-module builder toolkit for Antigravity CLI.",
    }:
        fail("nddev-builder plugin.json is not a compliant native plugin manifest")
    return Setup(
        setup_id=setup_id,
        description=metadata["description"],
        managed_files=tuple(metadata["managed_files"]),
        builder_enabled=True,
        files=files,
    )


def render_profile(profile_id: str) -> Profile:
    validate_id(profile_id, "profile id")
    if profile_id not in PROFILE_IDS:
        fail(f"unknown profile: {profile_id}")
    profile_root = PROFILE_ROOT / profile_id
    if not profile_root.is_dir() or profile_root.is_symlink():
        fail(f"profile catalog entry is missing or unsafe: {profile_id}")
    metadata = read_json_file(profile_root / "profile.json", f"profile {profile_id} metadata")
    expected_keys = {"schema_version", "id", "description", "default"}
    if set(metadata) != expected_keys:
        fail(f"profile {profile_id} metadata has invalid keys")
    if metadata["schema_version"] != 1 or metadata["id"] != profile_id:
        fail(f"profile {profile_id} metadata identity or schema is invalid")
    if metadata["default"] is not (profile_id == DEFAULT_PROFILE_ID):
        fail(f"profile {profile_id} default flag is invalid")
    if not isinstance(metadata["description"], str) or not metadata["description"].strip():
        fail(f"profile {profile_id} description must be non-empty")
    content, _ = read_regular_file(profile_root / "settings.json", f"profile {profile_id} settings")
    settings = parse_json_object(content, f"profile {profile_id} settings")
    if settings != expected_settings_for_profile(profile_id):
        fail(f"profile {profile_id}/settings.json does not match the product permission model")
    return Profile(
        profile_id=profile_id,
        description=metadata["description"],
        default=metadata["default"],
        settings=settings,
    )


def list_setups() -> list[dict[str, Any]]:
    return [
        {
            "id": setup.setup_id,
            "description": setup.description,
            "managed_files": list(setup.managed_files),
            "builder_enabled": setup.builder_enabled,
        }
        for setup in (render_setup(setup_id) for setup_id in SETUP_IDS)
    ]


def list_profiles() -> list[dict[str, Any]]:
    return [
        {
            "id": profile.profile_id,
            "description": profile.description,
            "default": profile.default,
            "managed_settings": profile.settings,
        }
        for profile in (render_profile(profile_id) for profile_id in PROFILE_IDS)
    ]


def resolve_target(raw_target: str | None) -> Path:
    if not raw_target:
        fail("--target is required")
    expanded = Path(raw_target).expanduser()
    if not expanded.is_absolute():
        fail("--target must be an absolute path")
    try:
        raw_info = expanded.lstat()
    except FileNotFoundError:
        raw_info = None
    if raw_info is not None and stat.S_ISLNK(raw_info.st_mode):
        fail("--target must not be a symlink")
    target = expanded.resolve(strict=False)
    if target == Path(target.anchor):
        fail("filesystem root cannot be a target")
    parent_info = require_directory(target.parent, "canonical --target parent")
    if stat.S_ISLNK(parent_info.st_mode):
        fail("canonical --target parent must be a real directory")
    if target.exists():
        require_directory(target, "--target")
    return target


def ensure_target_directory(target: Path, *, create: bool) -> bool:
    try:
        info = target.lstat()
    except FileNotFoundError:
        if not create:
            return False
        created = False
        try:
            target.mkdir(mode=OWNER_DIR_MODE)
            created = True
        except FileExistsError:
            pass
        info = target.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail("--target must be a real directory")
        if created:
            os.chmod(target, OWNER_DIR_MODE)
            info = target.lstat()
        if not is_private_directory(info):
            fail("--target must be owned by the current user with mode 0700")
        return True
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("--target must be a real directory")
    return True


def is_private_directory(info: os.stat_result) -> bool:
    if not stat.S_ISDIR(info.st_mode):
        return False
    if stat.S_IMODE(info.st_mode) != OWNER_DIR_MODE:
        return False
    return not hasattr(os, "geteuid") or owner_of(info) == os.geteuid()


def require_private_directory(path: Path, label: str) -> os.stat_result:
    info = require_directory(path, label)
    if not is_private_directory(info):
        fail(f"{label} must be owned by the current user with mode 0700")
    return info


def is_owner_directory_with_mode(info: os.stat_result, modes: set[int]) -> bool:
    if not stat.S_ISDIR(info.st_mode):
        return False
    if stat.S_IMODE(info.st_mode) not in modes:
        return False
    return not hasattr(os, "geteuid") or owner_of(info) == os.geteuid()


def require_owner_directory_modes(
    path: Path,
    label: str,
    modes: set[int],
) -> os.stat_result:
    info = require_directory(path, label)
    if not is_owner_directory_with_mode(info, modes):
        rendered = ", ".join(f"{mode:04o}" for mode in sorted(modes))
        fail(f"{label} must be owned by the current user with mode {rendered}")
    return info


def nofollow_flag(label: str) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        fail(f"{label} requires O_NOFOLLOW support")
    return os.O_NOFOLLOW


def open_owner_directory_fd(
    path: Path,
    label: str,
    modes: set[int],
) -> tuple[int, os.stat_result]:
    before = require_owner_directory_modes(path, label, modes)
    flags = os.O_RDONLY | nofollow_flag(label)
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} cannot be opened safely: {exc}")
    try:
        opened = os.fstat(descriptor)
        if identity_of(opened) != identity_of(before):
            raise ConcurrentTargetChange(f"{label} changed while it was opened")
        if not is_owner_directory_with_mode(opened, modes):
            rendered = ", ".join(f"{mode:04o}" for mode in sorted(modes))
            fail(f"{label} fd must be owned by the current user with mode {rendered}")
        return descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def set_directory_fd_mode(
    descriptor: int,
    path: Path,
    label: str,
    mode: int,
) -> None:
    os.fchmod(descriptor, mode)
    opened = os.fstat(descriptor)
    if not is_owner_directory_with_mode(opened, {mode}):
        fail(f"{label} fd mode did not become {mode:04o}")
    current = require_owner_directory_modes(path, label, {mode})
    if identity_of(current) != identity_of(opened):
        raise ConcurrentTargetChange(f"{label} changed while its mode was adjusted")


def require_private_target(target: Path) -> None:
    require_private_directory(target, "--target")


def require_owner_directory(path: Path, label: str) -> os.stat_result:
    info = require_directory(path, label)
    if hasattr(os, "geteuid") and owner_of(info) != os.geteuid():
        fail(f"{label} must be owned by the current user")
    return info


def ensure_private_target(target: Path, *, create: bool) -> bool:
    if not ensure_target_directory(target, create=create):
        return False
    require_private_target(target)
    return True


def target_path(target: Path, relative: str) -> Path:
    reject_symlink_ancestors(target, relative)
    return target / safe_relative_path(relative)


def software_root(target: Path) -> Path:
    return target / ".nddev-software" / "antigravity-cli"


def software_version_dir(target: Path, version: str = CLI_VERSION) -> Path:
    return software_root(target) / "versions" / version


def managed_cli_path(target: Path) -> Path:
    return target / "bin" / CLI_COMMAND


def software_tree_binary_path(target: Path, version: str = CLI_VERSION) -> Path:
    return software_version_dir(target, version) / CLI_COMMAND


def software_stamp_path(target: Path) -> Path:
    return software_root(target) / SOFTWARE_STAMP_NAME


def target_file_exists(target: Path, relative: str) -> bool:
    path = target_path(target, relative)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"managed path {path} must be a regular non-symlink file")
    if info.st_nlink != 1:
        fail(f"managed path {path} must not have hard-link aliases")
    return True


def read_target_file(
    target: Path,
    relative: str,
    *,
    owner_only: bool = False,
    max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES,
) -> bytes:
    path = target_path(target, relative)
    content, _ = read_regular_file(
        path,
        f"managed path {path}",
        owner_only=owner_only,
        max_bytes=max_bytes,
    )
    return content


def read_target_settings_if_present(target: Path) -> dict[str, Any]:
    path = target_path(target, SETTINGS)
    if not path.exists():
        return {}
    content, _ = read_regular_file(
        path,
        f"Antigravity settings {path}",
        owner_only=False,
        max_bytes=METADATA_MAX_BYTES,
    )
    return parse_json_object(content, f"Antigravity settings {path}")


def settings_managed_fragment(settings: dict[str, Any]) -> dict[str, Any]:
    return {key: settings[key] for key in SETTINGS_MANAGED_KEYS if key in settings}


def managed_digest(relative: str, content: bytes) -> str:
    if relative != SETTINGS:
        return sha256_bytes(content)
    settings = parse_json_object(content, "managed settings.json")
    return sha256_bytes(canonical_json(settings_managed_fragment(settings)))


def compose_settings(current: dict[str, Any], profile_settings: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for key in SETTINGS_MANAGED_KEYS:
        result[key] = profile_settings[key]
    return result


def strip_managed_settings(current: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for key in SETTINGS_MANAGED_KEYS:
        result.pop(key, None)
    return result


def desired_for(target: Path, setup: Setup, profile: Profile) -> dict[str, bytes | None]:
    current = read_target_settings_if_present(target) if target.exists() else {}
    desired: dict[str, bytes | None] = dict(setup.files)
    desired[SETTINGS] = canonical_json(compose_settings(current, profile.settings))
    return desired


def digest_map_for(files: tuple[str, ...], desired: dict[str, bytes | None]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for relative in files:
        content = desired.get(relative)
        result[relative] = None if content is None else managed_digest(relative, content)
    return result


def stamp_payload(
    target: Path,
    setup_id: str,
    profile_id: str,
    desired: dict[str, bytes | None],
    build_version: str = VERSION,
) -> dict[str, Any]:
    return {
        "schema_version": STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": build_version,
        "setup_id": setup_id,
        "profile_id": profile_id,
        "canonical_target": str(target),
        "managed_files": digest_map_for(MANAGED_FILES, desired),
        "builder": {
            "projection": "native-plugin",
            "enabled": True,
            "marketplace": None,
            "files": list(BUILDER_MANAGED_FILES),
        },
    }


def legacy_stamp_payload(
    target: Path,
    setup_id: str,
    build_version: str,
    desired: dict[str, bytes | None],
) -> dict[str, Any]:
    return {
        "schema_version": LEGACY_STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": build_version,
        "setup_id": setup_id,
        "canonical_target": str(target),
        "managed_files": digest_map_for(LEGACY_MANAGED_FILES, desired),
        "builder": {
            "projection": "native-plugin",
            "enabled": True,
            "marketplace": None,
            "files": list(LEGACY_BUILDER_MANAGED_FILES),
        },
    }


def stamp_managed_files(stamp: dict[str, Any]) -> tuple[str, ...]:
    return LEGACY_MANAGED_FILES if is_legacy_stamp(stamp) else MANAGED_FILES


def validate_digest_map(
    value: Any,
    label: str,
    files: tuple[str, ...],
) -> dict[str, str | None]:
    if not isinstance(value, dict) or set(value) != set(files):
        fail(f"{label} must declare exactly {list(files)}")
    result: dict[str, str | None] = {}
    for name in files:
        digest = value[name]
        if digest is not None and (
            not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest)
        ):
            fail(f"{label}.{name} must be null or a lowercase SHA-256 digest")
        result[name] = digest
    return result


def is_legacy_stamp(stamp: dict[str, Any]) -> bool:
    return stamp.get("schema_version") == LEGACY_STAMP_SCHEMA


def validate_current_stamp(stamp: dict[str, Any], target: Path) -> None:
    if set(stamp) != CURRENT_STAMP_KEYS:
        fail("managed stamp has invalid keys")
    if (
        stamp["schema_version"] != STAMP_SCHEMA
        or stamp["product_name"] != PRODUCT_NAME
        or stamp["canonical_target"] != str(target)
    ):
        fail("managed stamp identity or schema is invalid")
    setup_id = validate_id(stamp["setup_id"], "managed stamp setup_id")
    if setup_id not in SETUP_IDS:
        fail("managed stamp setup_id is not supported by this build")
    profile_id = validate_id(stamp["profile_id"], "managed stamp profile_id")
    if profile_id not in PROFILE_IDS:
        fail("managed stamp profile_id is not supported by this build")
    validate_non_empty_string(stamp["build_version"], "managed stamp build_version")
    validate_digest_map(stamp["managed_files"], "managed stamp managed_files", MANAGED_FILES)
    builder = stamp["builder"]
    if not isinstance(builder, dict) or builder.get("projection") != "native-plugin":
        fail("managed stamp builder projection is invalid")
    if builder.get("enabled") is not True or builder.get("marketplace") is not None:
        fail("managed stamp builder state is invalid")
    if builder.get("files") != list(BUILDER_MANAGED_FILES):
        fail("managed stamp builder files are invalid")


def validate_legacy_stamp(stamp: dict[str, Any], target: Path) -> None:
    if set(stamp) != LEGACY_STAMP_KEYS:
        fail("legacy managed stamp has invalid keys")
    if (
        stamp["schema_version"] != LEGACY_STAMP_SCHEMA
        or stamp["product_name"] != PRODUCT_NAME
        or stamp["canonical_target"] != str(target)
    ):
        fail("legacy managed stamp identity or schema is invalid")
    setup_id = validate_id(stamp["setup_id"], "legacy managed stamp setup_id")
    if setup_id not in LEGACY_SETUP_IDS:
        fail("legacy managed stamp setup_id is not recognized")
    validate_non_empty_string(stamp["build_version"], "legacy managed stamp build_version")
    validate_digest_map(
        stamp["managed_files"],
        "legacy managed stamp managed_files",
        LEGACY_MANAGED_FILES,
    )
    builder = stamp["builder"]
    if not isinstance(builder, dict) or builder.get("projection") != "native-plugin":
        fail("legacy managed stamp builder projection is invalid")
    if builder.get("enabled") is not True or builder.get("marketplace") is not None:
        fail("legacy managed stamp builder state is invalid")


def load_stamp(target: Path) -> dict[str, Any] | None:
    if not ensure_target_directory(target, create=False):
        return None
    if not target_file_exists(target, STAMP_NAME):
        return None
    content = read_target_file(target, STAMP_NAME, max_bytes=METADATA_MAX_BYTES)
    stamp = parse_json_object(content, f"managed stamp {target / STAMP_NAME}")
    schema = stamp.get("schema_version")
    if schema == STAMP_SCHEMA:
        validate_current_stamp(stamp, target)
    elif schema == LEGACY_STAMP_SCHEMA:
        validate_legacy_stamp(stamp, target)
    else:
        fail("managed stamp schema is not supported")
    return stamp


def detect_drift(target: Path, stamp: dict[str, Any]) -> list[str]:
    files = stamp_managed_files(stamp)
    expected = validate_digest_map(stamp["managed_files"], "managed stamp managed_files", files)
    drift: list[str] = []
    for relative in files:
        if not target_file_exists(target, relative):
            drift.append(relative)
            continue
        content = read_target_file(target, relative, owner_only=True)
        if managed_digest(relative, content) != expected[relative]:
            drift.append(relative)
    return drift


def snapshot_managed_files(target: Path) -> dict[str, FileSnapshot]:
    snapshot: dict[str, FileSnapshot] = {}
    for relative in (*MANAGED_FILES, STAMP_NAME):
        if ensure_target_directory(target, create=False) and target_file_exists(target, relative):
            content = read_target_file(target, relative, owner_only=False)
            snapshot[relative] = FileSnapshot(content=content, digest=sha256_bytes(content))
        else:
            snapshot[relative] = FileSnapshot(content=None, digest=None)
    return snapshot


def assert_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    for relative, expected in snapshot.items():
        exists = ensure_target_directory(target, create=False) and target_file_exists(
            target, relative
        )
        if not exists:
            actual = FileSnapshot(content=None, digest=None)
        else:
            content = read_target_file(target, relative, owner_only=False)
            actual = FileSnapshot(content=content, digest=sha256_bytes(content))
        if actual.digest != expected.digest:
            raise ConcurrentTargetChange(f"managed path changed concurrently: {relative}")


def preflight_unmanaged_target(target: Path) -> None:
    if not ensure_target_directory(target, create=False):
        return
    for relative in MANAGED_FILES:
        if relative == SETTINGS:
            continue
        if target_file_exists(target, relative):
            fail(f"unmanaged target already has managed path: {relative}")
    settings_path = target_path(target, SETTINGS)
    if settings_path.exists():
        settings = read_target_settings_if_present(target)
        managed = set(SETTINGS_MANAGED_KEYS) & set(settings)
        if managed:
            fail(
                f"unmanaged target already has managed Antigravity settings keys: {sorted(managed)}"
            )


def make_parent_directories(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, OWNER_DIR_MODE)


def atomic_write(path: Path, content: bytes) -> None:
    make_parent_directories(path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.chmod(temporary, OWNER_FILE_MODE)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_executable(path: Path, content: bytes) -> None:
    make_parent_directories(path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.chmod(temporary, OWNER_EXEC_MODE)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def current_platform_key() -> str:
    if sys.platform == "darwin":
        os_id = "darwin"
    elif sys.platform.startswith("linux"):
        libc_name = py_platform.libc_ver()[0].lower()
        if libc_name == "musl":
            fail("musl Linux is not supported by the pinned Antigravity CLI manifests")
        os_id = "linux"
    else:
        fail(f"unsupported Antigravity CLI installer platform: {sys.platform}")
    machine = os.uname().machine.lower()
    if machine in {"x86_64", "amd64"}:
        arch = "amd64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        fail(f"unsupported Antigravity CLI installer architecture: {machine}")
    platform_key = f"{os_id}_{arch}"
    if platform_key not in OFFICIAL_MANIFESTS:
        fail(f"unsupported Antigravity CLI installer platform: {platform_key}")
    return platform_key


def pinned_manifest(platform_key: str | None = None) -> dict[str, str]:
    key = current_platform_key() if platform_key is None else platform_key
    manifest = dict(OFFICIAL_MANIFESTS[key])
    manifest["platform"] = key
    manifest["manifest_url"] = MANIFEST_URL_TEMPLATE.format(platform=key)
    return manifest


def read_artifact(source: str) -> bytes:
    if not source.startswith("https://"):
        fail("software artifact source must be an HTTPS official source")
    request = urllib.request.Request(
        source,
        headers={"User-Agent": f"{PRODUCT_NAME}/{VERSION}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        expected = response.headers.get("Content-Length")
        blocks: list[bytes] = []
        total = 0
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > SOFTWARE_ARTIFACT_MAX_BYTES:
                fail("software artifact exceeds the bounded download limit")
            blocks.append(block)
    content = b"".join(blocks)
    if expected is not None and int(expected) != len(content):
        fail("software artifact download length changed while reading")
    return content


def read_official_manifest(manifest_url: str) -> dict[str, Any]:
    content = read_artifact(manifest_url)
    if len(content) > METADATA_MAX_BYTES:
        fail("official manifest exceeds the bounded metadata limit")
    manifest = parse_json_object(content, f"official manifest {manifest_url}")
    if set(manifest) != {"version", "url", "sha512"}:
        fail("official manifest has invalid fields")
    if not isinstance(manifest["version"], str) or not manifest["version"]:
        fail("official manifest version must be a non-empty string")
    if not isinstance(manifest["url"], str) or not manifest["url"].startswith("https://"):
        fail("official manifest url must be an HTTPS URL")
    if not isinstance(manifest["sha512"], str) or not SHA512_PATTERN.fullmatch(
        manifest["sha512"]
    ):
        fail("official manifest sha512 must be a lowercase SHA-512 digest")
    return manifest


def validate_archive_member_path(raw_name: str, label: str) -> Path:
    if "\x00" in raw_name:
        fail(f"software artifact contains a NUL byte in a {label} path")
    normalized = raw_name.replace("\\", "/")
    if normalized.startswith("//"):
        fail(f"software artifact contains an unsafe {label} path")
    path = PurePosixPath(normalized)
    first_part = path.parts[0] if path.parts else ""
    if (
        path.is_absolute()
        or not path.parts
        or ":" in first_part
        or re.fullmatch(r"[A-Za-z]:.*", first_part) is not None
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        fail(f"software artifact contains an unsafe {label} path")
    return Path(*path.parts)


def is_cli_candidate(path: Path) -> bool:
    return path.name in UPSTREAM_CLI_MEMBER_NAMES


def extract_cli_binary_from_tar(archive: bytes) -> bytes:
    candidates: list[bytes] = []
    with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            path = validate_archive_member_path(member.name, "tar")
            if member.issym() or member.islnk() or member.isdev() or member.isdir():
                if is_cli_candidate(path):
                    fail("software artifact CLI candidate must be a regular tar file")
                continue
            if not member.isfile():
                if is_cli_candidate(path):
                    fail("software artifact CLI candidate must be a regular tar file")
                continue
            if member.size > SOFTWARE_ARTIFACT_MAX_BYTES:
                fail("software artifact CLI binary exceeds the decompressed size limit")
            if not is_cli_candidate(path):
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                fail("software artifact CLI binary could not be read")
            content = extracted.read(SOFTWARE_ARTIFACT_MAX_BYTES + 1)
            if len(content) > SOFTWARE_ARTIFACT_MAX_BYTES or len(content) != member.size:
                fail("software artifact CLI binary size changed while reading")
            candidates.append(content)
            if len(candidates) > 1:
                fail("software artifact contains duplicate CLI binary candidates")
    if len(candidates) != 1:
        fail(f"software artifact must contain exactly one {CLI_COMMAND} binary")
    return candidates[0]


def prepare_cli_artifact() -> dict[str, Any]:
    manifest = pinned_manifest()
    observed = read_official_manifest(manifest["manifest_url"])
    expected = {key: manifest[key] for key in ("version", "url", "sha512")}
    if observed != expected:
        fail("official Antigravity CLI manifest no longer matches the pinned baseline")
    source_url = manifest["url"]
    archive = read_artifact(source_url)
    artifact_sha512 = sha512_bytes(archive)
    if artifact_sha512 != manifest["sha512"]:
        fail("official Antigravity CLI artifact SHA-512 mismatch")
    binary = extract_cli_binary_from_tar(archive)
    binary_sha256 = sha256_bytes(binary)
    return {
        "platform": manifest["platform"],
        "manifest_url": manifest["manifest_url"],
        "manifest_version": manifest["version"],
        "artifact_url": source_url,
        "artifact_sha512": artifact_sha512,
        "artifact_size": len(archive),
        "binary": binary,
        "binary_sha256": binary_sha256,
    }


def software_stamp(
    target: Path,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SOFTWARE_STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(target),
        "command": CLI_COMMAND,
        "version": CLI_VERSION,
        "platform": artifact["platform"],
        "installer_url": INSTALL_SCRIPT_URL,
        "installer_sha256": INSTALL_SCRIPT_SHA256,
        "manifest_url": artifact["manifest_url"],
        "manifest_version": artifact["manifest_version"],
        "artifact_url": artifact["artifact_url"],
        "artifact_size": artifact["artifact_size"],
        "artifact_sha512": artifact["artifact_sha512"],
        "binary_sha256": artifact["binary_sha256"],
        "installed_at": int(time.time()),
    }


def load_software_stamp(target: Path) -> dict[str, Any] | None:
    path = software_stamp_path(target)
    if not path.exists() and not path.is_symlink():
        return None
    stamp = read_json_file(path, f"software stamp {path}", owner_only=True)
    expected = {
        "schema_version",
        "product_name",
        "build_version",
        "canonical_target",
        "command",
        "version",
        "platform",
        "installer_url",
        "installer_sha256",
        "manifest_url",
        "manifest_version",
        "artifact_url",
        "artifact_size",
        "artifact_sha512",
        "binary_sha256",
        "installed_at",
    }
    if set(stamp) != expected:
        fail("software stamp has invalid keys")
    if (
        stamp["schema_version"] != SOFTWARE_STAMP_SCHEMA
        or stamp["product_name"] != PRODUCT_NAME
        or stamp["canonical_target"] != str(target)
        or stamp["command"] != CLI_COMMAND
    ):
        fail("software stamp identity is invalid")
    for key in (
        "build_version",
        "version",
        "platform",
        "installer_url",
        "installer_sha256",
        "manifest_url",
        "manifest_version",
        "artifact_url",
    ):
        if not isinstance(stamp[key], str) or not stamp[key]:
            fail(f"software stamp {key} must be a non-empty string")
    if not SHA256_PATTERN.fullmatch(stamp["installer_sha256"]):
        fail("software stamp installer_sha256 must be a lowercase SHA-256 digest")
    if not SHA512_PATTERN.fullmatch(stamp["artifact_sha512"]):
        fail("software stamp artifact_sha512 must be a lowercase SHA-512 digest")
    if not SHA256_PATTERN.fullmatch(stamp["binary_sha256"]):
        fail("software stamp binary_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(stamp["artifact_size"], int) or stamp["artifact_size"] <= 0:
        fail("software stamp artifact_size must be a positive integer")
    if not isinstance(stamp["installed_at"], int):
        fail("software stamp installed_at must be an integer")
    return stamp


def read_optional_software_executable(path: Path, label: str) -> bytes | None:
    if not path.exists() and not path.is_symlink():
        return None
    require_executable_file(path, label)
    return read_regular_file(
        path,
        label,
        owner_only=False,
        max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
    )[0]


def reject_existing_software_ancestor_links(target: Path, path: Path, label: str) -> None:
    try:
        relative = path.relative_to(target)
    except ValueError:
        fail(f"{label} is outside the canonical target")
    current = target
    for part in relative.parts[:-1]:
        current = current / part
        if not current.exists() and not current.is_symlink():
            return
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"{label} parent is unsafe: {current}")


def expected_software_identity() -> dict[str, Any]:
    manifest = pinned_manifest()
    return {
        "build_version": VERSION,
        "version": CLI_VERSION,
        "platform": manifest["platform"],
        "installer_url": INSTALL_SCRIPT_URL,
        "installer_sha256": INSTALL_SCRIPT_SHA256,
        "manifest_url": manifest["manifest_url"],
        "manifest_version": manifest["version"],
        "artifact_url": manifest["url"],
        "artifact_sha512": manifest["sha512"],
    }


def software_status(target: Path) -> dict[str, Any]:
    if not ensure_target_directory(target, create=False):
        return {
            "schema_version": 1,
            "command": "software-status",
            "target": str(target),
            "installed": False,
            "version": None,
            "expected_version": CLI_VERSION,
            "managed_command": str(managed_cli_path(target)),
            "stamp": None,
            "drift": [],
            "current": False,
        }
    require_private_target(target)
    stamp = load_software_stamp(target)
    binary = managed_cli_path(target)
    version_binary = None if stamp is None else software_tree_binary_path(target, CLI_VERSION)
    installed = False
    drift: list[str] = []
    if stamp is not None:
        reject_existing_software_ancestor_links(target, binary, "managed software binary")
        reject_existing_software_ancestor_links(
            target, version_binary, "managed software version binary"
        )
        binary_content = read_optional_software_executable(
            binary, f"managed software binary {binary}"
        )
        version_binary_content = read_optional_software_executable(
            version_binary, f"managed software version binary {version_binary}"
        )
        for label, content in (
            ("bin/agy", binary_content),
            (
                str(
                    Path(".nddev-software/antigravity-cli/versions")
                    / CLI_VERSION
                    / CLI_COMMAND
                ),
                version_binary_content,
            ),
        ):
            if content is None or sha256_bytes(content) != stamp["binary_sha256"]:
                drift.append(label)
        installed = binary_content is not None and version_binary_content is not None and not any(
            item.startswith(".nddev-software") or item == "bin/agy" for item in drift
        )
        for key, expected in expected_software_identity().items():
            if stamp[key] != expected:
                drift.append(key)
    else:
        root = software_root(target)
        if root.is_symlink():
            fail("software root must be a real directory")
    if stamp is None and (
        binary.exists()
        or binary.is_symlink()
        or (
            software_root(target).exists()
            and any(path.is_file() or path.is_symlink() for path in software_root(target).rglob("*"))
        )
    ):
        drift.append("software-stamp")
    current = installed and not drift
    return {
        "schema_version": 1,
        "command": "software-status",
        "target": str(target),
        "installed": installed,
        "current": current,
        "version": None if stamp is None else stamp["version"],
        "expected_version": CLI_VERSION,
        "managed_command": str(binary),
        "stamp": None if stamp is None else str(software_stamp_path(target)),
        "drift": drift,
    }


def ensure_real_directory_path(path: Path, label: str) -> None:
    if path.exists() or path.is_symlink():
        descriptor, _ = open_owner_directory_fd(
            path,
            label,
            {OWNER_DIR_MODE, OWNER_READ_EXEC_DIR_MODE},
        )
        try:
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != OWNER_DIR_MODE:
                set_directory_fd_mode(descriptor, path, label, OWNER_DIR_MODE)
        finally:
            os.close(descriptor)
        return
    path.mkdir(mode=OWNER_DIR_MODE, parents=True)
    descriptor, _ = open_owner_directory_fd(path, label, {OWNER_DIR_MODE})
    try:
        set_directory_fd_mode(descriptor, path, label, OWNER_DIR_MODE)
    finally:
        os.close(descriptor)


def install_cli_unlocked(target: Path, command: str) -> dict[str, Any]:
    ensure_target_directory(target, create=True)
    status = software_status(target)
    if command == "install-cli" and (status["version"] is not None or status["drift"]):
        fail("install-cli requires absent managed software; use update-cli for existing state")
    if command == "update-cli" and status["version"] is None:
        fail("update-cli requires existing managed software")
    if command == "update-cli" and status["current"]:
        return {
            "schema_version": 1,
            "command": command,
            "operation": "current",
            "target": str(target),
            "version": CLI_VERSION,
            "current": True,
            "changed": [],
            "managed_command": str(managed_cli_path(target)),
        }

    artifact = prepare_cli_artifact()
    binary_path = managed_cli_path(target)
    stamp_path = software_stamp_path(target)
    version_dir = software_version_dir(target)
    version_binary = software_tree_binary_path(target)
    before_binary = None
    before_stamp = None
    if binary_path.exists() or binary_path.is_symlink():
        before_binary = read_regular_file(
            binary_path,
            f"managed software binary {binary_path}",
            owner_only=False,
            max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
        )[0]
    if stamp_path.exists() or stamp_path.is_symlink():
        before_stamp = read_regular_file(
            stamp_path,
            f"software stamp {stamp_path}",
            owner_only=False,
            max_bytes=METADATA_MAX_BYTES,
        )[0]
    root = software_root(target)
    software_base = root.parent
    versions = root / "versions"
    for guarded_path, label in (
        (software_base, "software base directory"),
        (root, "software root"),
        (versions, "software versions directory"),
        (version_dir, "software version path"),
    ):
        reject_existing_software_ancestor_links(target, guarded_path, label)
    ensure_real_directory_path(software_base, "software base directory")
    ensure_real_directory_path(root, "software root")
    ensure_real_directory_path(versions, "software versions directory")
    before_version_exists = False
    if version_dir.exists() or version_dir.is_symlink():
        info = version_dir.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail("software version path is unsafe")
        require_private_directory(version_dir, "software version path")
        before_version_exists = True
    reject_symlink_ancestors(target, "bin/agy")
    reject_symlink_ancestors(
        target, ".nddev-software/antigravity-cli/versions/1.1.7/agy"
    )
    staging = versions / f".stage-{os.getpid()}-{time.time_ns()}"
    rollback_version = versions / f".rollback-{os.getpid()}-{time.time_ns()}"
    changed: list[str] = []
    if before_binary != artifact["binary"]:
        changed.append("bin/agy")
    before_version_binary = read_optional_software_executable(
        version_binary, f"managed software version binary {version_binary}"
    )
    version_relative = str(Path(".nddev-software/antigravity-cli/versions/1.1.7") / CLI_COMMAND)
    if before_version_binary != artifact["binary"]:
        changed.append(version_relative)
    stamp_bytes = canonical_json(software_stamp(target, artifact))
    if before_stamp != stamp_bytes:
        changed.append(str(Path(".nddev-software/antigravity-cli") / SOFTWARE_STAMP_NAME))
    try:
        staging.mkdir(mode=OWNER_DIR_MODE)
        os.chmod(staging, OWNER_DIR_MODE)
        require_private_directory(staging, "software staging directory")
        atomic_write_executable(staging / CLI_COMMAND, artifact["binary"])
        if before_version_exists:
            version_dir.rename(rollback_version)
        staging.rename(version_dir)
        atomic_write_executable(binary_path, artifact["binary"])
        atomic_write(stamp_path, stamp_bytes)
    except BaseException:
        if version_dir.exists() or version_dir.is_symlink():
            remove_private_tree_if_present(version_dir, "software version directory")
        if rollback_version.exists():
            rollback_version.rename(version_dir)
        if before_binary is None:
            with contextlib.suppress(FileNotFoundError):
                binary_path.unlink()
        else:
            atomic_write_executable(binary_path, before_binary)
        if before_stamp is None:
            with contextlib.suppress(FileNotFoundError):
                stamp_path.unlink()
        else:
            atomic_write(stamp_path, before_stamp)
        with contextlib.suppress(FileNotFoundError, ManagerError):
            remove_private_tree_if_present(staging, "software staging directory")
        with contextlib.suppress(FileNotFoundError, ManagerError):
            remove_private_tree_if_present(rollback_version, "software rollback directory")
        raise
    finally:
        with contextlib.suppress(FileNotFoundError, ManagerError):
            remove_private_tree_if_present(staging, "software staging directory")
    with contextlib.suppress(FileNotFoundError, ManagerError):
        remove_private_tree_if_present(rollback_version, "software rollback directory")
    final_status = software_status(target)
    return {
        "schema_version": 1,
        "command": command,
        "operation": "install" if command == "install-cli" else "update",
        "target": str(target),
        "version": CLI_VERSION,
        "current": final_status["current"],
        "changed": changed,
        "platform": artifact["platform"],
        "manifest_url": artifact["manifest_url"],
        "artifact_url": artifact["artifact_url"],
        "artifact_sha512": artifact["artifact_sha512"],
        "artifact_size": artifact["artifact_size"],
        "binary_sha256": artifact["binary_sha256"],
        "managed_command": str(binary_path),
    }


def install_cli(target: Path, command: str) -> dict[str, Any]:
    with target_lock(target, create=command == "install-cli"):
        return install_cli_unlocked(target, command)


def remove_empty_managed_parents(target: Path, relative: str) -> None:
    current = (target / safe_relative_path(relative)).parent
    while current != target and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def replace_managed_state(
    target: Path,
    desired: dict[str, bytes | None],
    expected: dict[str, FileSnapshot] | None,
    *,
    remove_empty_parents: bool = True,
) -> None:
    ensure_target_directory(target, create=True)
    if expected is not None:
        assert_snapshot(target, expected)
    for relative in (*MANAGED_FILES, STAMP_NAME):
        path = target_path(target, relative)
        content = desired.get(relative)
        if content is None:
            if path.exists():
                require_regular_file(path, f"managed path {path}", owner_only=False)
                path.unlink()
                if remove_empty_parents:
                    remove_empty_managed_parents(target, relative)
            continue
        atomic_write(path, content)
    if expected is not None:
        for relative, content in desired.items():
            if relative == STAMP_NAME or relative in MANAGED_FILES:
                if content is not None:
                    target_file_exists(target, relative)


def restore_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    desired = {relative: item.content for relative, item in snapshot.items()}
    replace_managed_state(target, desired, None)


@contextlib.contextmanager
def target_lock(target: Path, *, create: bool) -> Iterator[None]:
    if not ensure_private_target(target, create=create):
        fail("--target is missing")
    lock_parent = target / TARGET_LOCK_DIR_NAME
    lock_file = lock_parent / TARGET_LOCK_FILE_NAME
    parent_descriptor: int | None = None
    lock_descriptor: int | None = None
    lock_acquired = False
    try:
        lock_parent.mkdir(mode=OWNER_DIR_MODE)
    except FileExistsError:
        pass
    parent_descriptor, parent_info = open_owner_directory_fd(
        lock_parent,
        "target lock parent",
        {OWNER_DIR_MODE, OWNER_READ_EXEC_DIR_MODE},
    )
    try:
        lock_file_missing = False
        try:
            lock_file.lstat()
        except FileNotFoundError:
            lock_file_missing = True
        if (
            lock_file_missing
            and stat.S_IMODE(parent_info.st_mode) == OWNER_READ_EXEC_DIR_MODE
        ):
            set_directory_fd_mode(
                parent_descriptor,
                lock_parent,
                "target lock parent",
                OWNER_DIR_MODE,
            )
        flags = os.O_RDWR | os.O_CREAT | nofollow_flag("target lock file")
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            lock_descriptor = os.open(lock_file, flags, OWNER_FILE_MODE)
        except OSError as exc:
            fail(f"target lock file cannot be opened safely: {exc}")
        lock_info = os.fstat(lock_descriptor)
        if not stat.S_ISREG(lock_info.st_mode):
            fail("target lock file must be a regular file")
        if lock_info.st_nlink != 1:
            fail("target lock file must not have hard-link aliases")
        if hasattr(os, "geteuid") and owner_of(lock_info) != os.geteuid():
            fail("target lock file must be owned by the current user")
        if stat.S_IMODE(lock_info.st_mode) != OWNER_FILE_MODE:
            if lock_file_missing:
                os.fchmod(lock_descriptor, OWNER_FILE_MODE)
                lock_info = os.fstat(lock_descriptor)
            if stat.S_IMODE(lock_info.st_mode) != OWNER_FILE_MODE:
                fail("target lock file must be owned by the current user with mode 0600")
        try:
            path_info = lock_file.lstat()
        except FileNotFoundError as exc:
            raise ConcurrentTargetChange("target lock file disappeared while opening") from exc
        if (
            stat.S_ISLNK(path_info.st_mode)
            or not stat.S_ISREG(path_info.st_mode)
            or identity_of(path_info) != identity_of(lock_info)
        ):
            raise ConcurrentTargetChange("target lock file changed while opening")
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail(f"target is already locked: {lock_file}")
        lock_acquired = True
        set_directory_fd_mode(
            parent_descriptor,
            lock_parent,
            "target lock parent",
            OWNER_READ_EXEC_DIR_MODE,
        )
        yield
    finally:
        if parent_descriptor is not None and lock_acquired:
            with contextlib.suppress(FileNotFoundError, OSError, ManagerError):
                set_directory_fd_mode(
                    parent_descriptor,
                    lock_parent,
                    "target lock parent",
                    OWNER_DIR_MODE,
                )
        if lock_descriptor is not None:
            if lock_acquired:
                with contextlib.suppress(OSError):
                    fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def backup_pool(target: Path) -> Path:
    return target / ".nddev-antigravity-cli-backups"


@contextlib.contextmanager
def backup_pool_lock(target: Path) -> Iterator[None]:
    require_private_target(target)
    lock = target / ".nddev-antigravity-cli-backups-lock"
    created = False
    try:
        lock.mkdir(mode=OWNER_DIR_MODE)
        created = True
        os.chmod(lock, OWNER_DIR_MODE)
        require_private_directory(lock, "backup pool lock")
    except FileExistsError:
        if lock.is_symlink():
            fail("backup pool lock path must not be a symlink")
        require_private_directory(lock, "backup pool lock")
        fail(f"backup pool is already locked: {lock}")
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError, OSError):
            if created:
                require_private_directory(lock, "backup pool lock")
            lock.rmdir()


def choose_backup_slot(pool: Path) -> int:
    if not pool.exists():
        return 0
    require_private_directory(pool, "backup pool")
    slots: list[int] = []
    for path in pool.iterdir():
        if path.name == BACKUP_NAME:
            fail("backup pool contains an invalid envelope at pool root")
        if path.is_symlink():
            fail(f"backup pool entry must not be a symlink: {path.name}")
        if not path.name.isdigit():
            fail(f"backup pool entry has an invalid name: {path.name}")
        slot = int(path.name)
        if slot < 0 or slot >= MAX_BACKUPS:
            fail(f"backup pool entry has an out-of-range slot: {path.name}")
        require_private_directory(path, f"backup slot {path.name}")
        slots.append(slot)
    slots.sort()
    if not slots:
        return 0
    return (slots[-1] + 1) % MAX_BACKUPS


def remove_private_tree(path: Path, label: str, *, private_root: bool = True) -> None:
    if private_root:
        require_private_directory(path, label)
    else:
        require_owner_directory(path, label)
    for child in path.iterdir():
        child_info = child.lstat()
        if stat.S_ISLNK(child_info.st_mode):
            fail(f"{label} contains a symlink and will not be removed: {child.name}")
        if stat.S_ISDIR(child_info.st_mode):
            remove_private_tree(child, f"{label}/{child.name}", private_root=False)
            continue
        if not stat.S_ISREG(child_info.st_mode):
            fail(f"{label} contains a non-regular file: {child.name}")
        if hasattr(os, "geteuid") and owner_of(child_info) != os.geteuid():
            fail(f"{label} contains a foreign-owned file: {child.name}")
        child.unlink()
    path.rmdir()


def remove_private_tree_if_present(path: Path, label: str) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        fail(f"{label} must not be a symlink")
    remove_private_tree(path, label)


def write_backup(target: Path, stamp: dict[str, Any]) -> int:
    with backup_pool_lock(target):
        pool = backup_pool(target)
        if pool.exists() or pool.is_symlink():
            require_private_directory(pool, "backup pool")
        else:
            pool.mkdir(mode=OWNER_DIR_MODE)
            os.chmod(pool, OWNER_DIR_MODE)
            require_private_directory(pool, "backup pool")
        slot = choose_backup_slot(pool)
        slot_dir = pool / str(slot)
        if slot_dir.exists() or slot_dir.is_symlink():
            remove_private_tree(slot_dir, f"backup slot {slot}")
        files_dir = slot_dir / "files"
        files_dir.mkdir(parents=True, mode=OWNER_DIR_MODE)
        os.chmod(slot_dir, OWNER_DIR_MODE)
        os.chmod(files_dir, OWNER_DIR_MODE)
        source_files = stamp_managed_files(stamp)
        managed_files: dict[str, str | None] = {}
        for relative in source_files:
            if target_file_exists(target, relative):
                content = read_target_file(target, relative, owner_only=False)
                backup_path = files_dir / safe_relative_path(relative)
                atomic_write(backup_path, content)
                managed_files[relative] = managed_digest(relative, content)
            else:
                managed_files[relative] = None
        stamp_content = read_target_file(target, STAMP_NAME, max_bytes=METADATA_MAX_BYTES)
        envelope = {
            "schema_version": BACKUP_SCHEMA,
            "product_name": PRODUCT_NAME,
            "build_version": VERSION,
            "slot": slot,
            "canonical_target": str(target),
            "source_stamp_schema": stamp["schema_version"],
            "source_build_version": stamp["build_version"],
            "source_setup_id": stamp["setup_id"],
            "source_profile_id": None if is_legacy_stamp(stamp) else stamp["profile_id"],
            "managed_files": managed_files,
            "stamp_sha256": sha256_bytes(stamp_content),
        }
        atomic_write(slot_dir / BACKUP_NAME, canonical_json(envelope))
        return slot


def read_backup_files(
    slot_dir: Path,
    managed_files: dict[str, str | None],
    files: tuple[str, ...],
) -> dict[str, bytes | None]:
    result: dict[str, bytes | None] = {relative: None for relative in MANAGED_FILES}
    require_private_directory(slot_dir, "backup slot")
    files_dir = slot_dir / "files"
    require_private_directory(files_dir, "backup files directory")
    for relative in files:
        expected = managed_files[relative]
        path = files_dir / safe_relative_path(relative)
        if expected is None:
            result[relative] = None
            continue
        content, _ = read_regular_file(path, f"backup file {relative}", owner_only=True)
        if managed_digest(relative, content) != expected:
            fail(f"backup file digest mismatch: {relative}")
        result[relative] = content
    return result


def validate_common_backup_envelope(
    envelope: dict[str, Any],
    target: Path,
    slot: int,
    schema: int,
) -> str:
    if validate_exact_int(envelope["schema_version"], "backup schema_version") != schema:
        fail("backup envelope schema is invalid")
    if validate_non_empty_string(envelope["product_name"], "backup product_name") != PRODUCT_NAME:
        fail("backup envelope product identity is invalid")
    build_version = validate_non_empty_string(envelope["build_version"], "backup build_version")
    if validate_exact_int(envelope["slot"], "backup slot") != slot:
        fail("backup slot identity is invalid")
    if validate_non_empty_string(envelope["canonical_target"], "backup canonical_target") != str(target):
        fail("backup belongs to a different canonical target")
    validate_sha256_digest(envelope["stamp_sha256"], "backup stamp_sha256")
    return build_version


def validate_restored_stamp_bytes(
    target: Path,
    stamp: dict[str, Any],
    expected_sha256: str,
) -> bytes:
    content = canonical_json(stamp)
    if sha256_bytes(content) != expected_sha256:
        fail("backup stamp digest mismatch")
    parsed = parse_json_object(content, "restored backup stamp")
    if is_legacy_stamp(parsed):
        validate_legacy_stamp(parsed, target)
    else:
        validate_current_stamp(parsed, target)
    return content


def load_backup(target: Path, slot: int) -> tuple[dict[str, Any], dict[str, bytes | None]]:
    require_private_target(target)
    if slot < 0 or slot >= MAX_BACKUPS:
        fail("--backup must be between 0 and 9")
    require_private_directory(backup_pool(target), "backup pool")
    slot_dir = backup_pool(target) / str(slot)
    require_private_directory(slot_dir, f"backup slot {slot}")
    envelope_path = slot_dir / BACKUP_NAME
    if envelope_path.is_symlink() or not envelope_path.is_file():
        fail(f"backup slot is missing: {slot}")
    envelope = read_json_file(envelope_path, f"backup slot {slot}", owner_only=True)
    if envelope.get("schema_version") == LEGACY_BACKUP_SCHEMA:
        if set(envelope) != LEGACY_BACKUP_KEYS:
            fail("legacy backup envelope has invalid keys")
        source_build_version = validate_common_backup_envelope(
            envelope,
            target,
            slot,
            LEGACY_BACKUP_SCHEMA,
        )
        source_setup_id = validate_id(envelope["source_setup_id"], "legacy backup setup id")
        if source_setup_id not in LEGACY_SETUP_IDS:
            fail("legacy backup setup id is not recognized")
        managed = validate_digest_map(
            envelope["managed_files"],
            "legacy backup managed_files",
            LEGACY_MANAGED_FILES,
        )
        files = read_backup_files(slot_dir, managed, LEGACY_MANAGED_FILES)
        files[STAMP_NAME] = validate_restored_stamp_bytes(
            target,
            legacy_stamp_payload(target, source_setup_id, source_build_version, files),
            envelope["stamp_sha256"],
        )
        return envelope, files
    if set(envelope) != BACKUP_KEYS:
        fail("backup envelope has invalid keys")
    validate_common_backup_envelope(envelope, target, slot, BACKUP_SCHEMA)
    source_schema = validate_exact_int(
        envelope["source_stamp_schema"],
        "backup source_stamp_schema",
    )
    source_build_version = validate_non_empty_string(
        envelope["source_build_version"],
        "backup source_build_version",
    )
    source_setup_id = validate_id(envelope["source_setup_id"], "backup source_setup_id")
    if source_schema == LEGACY_STAMP_SCHEMA:
        source_files = LEGACY_MANAGED_FILES
        source_profile_id = None
        if source_setup_id not in LEGACY_SETUP_IDS or envelope["source_profile_id"] is not None:
            fail("backup legacy source identity is invalid")
    elif source_schema == STAMP_SCHEMA:
        source_files = MANAGED_FILES
        source_profile_id = validate_id(
            envelope["source_profile_id"],
            "backup source_profile_id",
        )
        if source_setup_id not in SETUP_IDS or source_profile_id not in PROFILE_IDS:
            fail("backup current source identity is invalid")
    else:
        fail("backup source stamp schema is unsupported")
    managed = validate_digest_map(envelope["managed_files"], "backup managed_files", source_files)
    files = read_backup_files(slot_dir, managed, source_files)
    if source_schema == LEGACY_STAMP_SCHEMA:
        files[STAMP_NAME] = validate_restored_stamp_bytes(
            target,
            legacy_stamp_payload(
                target,
                source_setup_id,
                source_build_version,
                files,
            ),
            envelope["stamp_sha256"],
        )
    else:
        files[STAMP_NAME] = validate_restored_stamp_bytes(
            target,
            stamp_payload(target, source_setup_id, source_profile_id, files, source_build_version),
            envelope["stamp_sha256"],
        )
    return envelope, files


def current_status(target: Path) -> dict[str, Any]:
    if not ensure_target_directory(target, create=False):
        return {
            "state": "missing",
            "target": str(target),
            "setup_id": None,
            "profile_id": None,
            "legacy": False,
            "launch_allowed": False,
            "drift": [],
            "builder": {"projection": "native-plugin", "enabled": False},
        }
    require_private_target(target)
    stamp = load_stamp(target)
    if stamp is None:
        return {
            "state": "unmanaged",
            "target": str(target),
            "setup_id": None,
            "profile_id": None,
            "legacy": False,
            "launch_allowed": False,
            "drift": [],
            "builder": {"projection": "native-plugin", "enabled": False},
        }
    drift = detect_drift(target, stamp)
    legacy = is_legacy_stamp(stamp)
    builder_files = LEGACY_BUILDER_MANAGED_FILES if legacy else BUILDER_MANAGED_FILES
    launch_allowed = False
    if not legacy and not drift:
        software = software_status(target)
        launch_allowed = software["installed"] and software["current"]
    return {
        "state": "legacy-managed" if legacy else "managed",
        "target": str(target),
        "setup_id": stamp["setup_id"],
        "profile_id": None if legacy else stamp["profile_id"],
        "build_version": stamp["build_version"],
        "legacy": legacy,
        "launch_allowed": launch_allowed,
        "drift": drift,
        "builder": {
            "projection": "native-plugin",
            "enabled": not any(item in drift for item in builder_files),
        },
    }


def plan_setup(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    render_setup(setup_id)
    render_profile(profile_id)
    status = current_status(target)
    if status["state"] in {"missing", "unmanaged"}:
        operation = "install"
        backup_required = False
    elif status["state"] == "legacy-managed":
        operation = "migrate"
        backup_required = True
    elif status["setup_id"] == setup_id and status["profile_id"] == profile_id:
        operation = "update"
        backup_required = False
    else:
        operation = "switch"
        backup_required = True
    return {
        "operation": operation,
        "target": str(target),
        "setup_id": setup_id,
        "profile_id": profile_id,
        "mutates": False,
        "backup_required": backup_required,
        "state": status["state"],
        "current_setup_id": status["setup_id"],
        "current_profile_id": status["profile_id"],
        "drift": status["drift"],
    }


def require_clean_managed_any(target: Path) -> dict[str, Any]:
    stamp = load_stamp(target)
    if stamp is None:
        fail("target is not managed")
    drift = detect_drift(target, stamp)
    if drift:
        fail(f"managed target has drift: {drift}")
    return stamp


def require_clean_current(target: Path) -> dict[str, Any]:
    stamp = require_clean_managed_any(target)
    if is_legacy_stamp(stamp):
        fail("legacy managed Antigravity CLI targets cannot launch; migrate first")
    return stamp


def mutate_setup(target: Path, setup_id: str, profile_id: str, action: str) -> dict[str, Any]:
    setup = render_setup(setup_id)
    profile = render_profile(profile_id)
    with target_lock(target, create=action != "switch"):
        ensure_target_directory(target, create=True)
        existing_stamp = load_stamp(target)
        if existing_stamp is None:
            if action == "switch":
                fail("switch requires a managed target")
            preflight_unmanaged_target(target)
        else:
            drift = detect_drift(target, existing_stamp)
            if drift:
                fail(f"managed target has drift: {drift}")
            if is_legacy_stamp(existing_stamp):
                fail("target has legacy managed state; use migrate, restore, or remove")
        backup_slot: int | None = None
        if existing_stamp is not None and (
            existing_stamp["setup_id"] != setup_id or existing_stamp["profile_id"] != profile_id
        ):
            backup_slot = write_backup(target, existing_stamp)
        before = snapshot_managed_files(target)
        desired = desired_for(target, setup, profile)
        desired[STAMP_NAME] = canonical_json(stamp_payload(target, setup_id, profile_id, desired))
        try:
            replace_managed_state(target, desired, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        changed = []
        for relative in MANAGED_FILES:
            desired_content = desired[relative]
            desired_digest = None if desired_content is None else sha256_bytes(desired_content)
            if before[relative].digest != desired_digest:
                changed.append(relative)
        return {
            "operation": "install" if existing_stamp is None else action,
            "target": str(target),
            "setup_id": setup_id,
            "profile_id": profile_id,
            "changed": changed,
            "backup_slot": backup_slot,
            "builder": {"projection": "native-plugin", "enabled": True},
        }


def migrate_setup(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    setup = render_setup(setup_id)
    profile = render_profile(profile_id)
    with target_lock(target, create=False):
        existing_stamp = require_clean_managed_any(target)
        if not is_legacy_stamp(existing_stamp):
            fail("migrate requires a legacy managed target")
        backup_slot = write_backup(target, existing_stamp)
        before = snapshot_managed_files(target)
        desired = desired_for(target, setup, profile)
        desired[STAMP_NAME] = canonical_json(stamp_payload(target, setup_id, profile_id, desired))
        try:
            replace_managed_state(target, desired, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        return {
            "operation": "migrate",
            "target": str(target),
            "legacy_setup_id": existing_stamp["setup_id"],
            "setup_id": setup_id,
            "profile_id": profile_id,
            "backup_slot": backup_slot,
            "builder": {"projection": "native-plugin", "enabled": True},
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    with target_lock(target, create=False):
        stamp = require_clean_managed_any(target)
        _, files = load_backup(target, slot)
        backup_slot = write_backup(target, stamp)
        before = snapshot_managed_files(target)
        try:
            replace_managed_state(target, files, before)
            restored_stamp = load_stamp(target)
            if restored_stamp is None:
                fail("restore did not produce a managed stamp")
            restored_drift = detect_drift(target, restored_stamp)
            if restored_drift:
                fail(f"restored backup has drift: {restored_drift}")
        except BaseException:
            restore_snapshot(target, before)
            raise
        return {
            "operation": "restore",
            "target": str(target),
            "setup_id": restored_stamp["setup_id"],
            "profile_id": None if is_legacy_stamp(restored_stamp) else restored_stamp["profile_id"],
            "legacy": is_legacy_stamp(restored_stamp),
            "backup_slot": backup_slot,
            "restored_backup": slot,
            "builder": {"projection": "native-plugin", "enabled": True},
        }


def remove_setup(target: Path) -> dict[str, Any]:
    with target_lock(target, create=False):
        stamp = require_clean_managed_any(target)
        backup_slot = write_backup(target, stamp)
        before = snapshot_managed_files(target)
        desired: dict[str, bytes | None] = {relative: None for relative in MANAGED_FILES}
        if target_file_exists(target, SETTINGS):
            current = read_target_settings_if_present(target)
            stripped = strip_managed_settings(current)
            desired[SETTINGS] = canonical_json(stripped) if stripped else None
        desired[STAMP_NAME] = None
        try:
            replace_managed_state(target, desired, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        return {
            "operation": "remove",
            "target": str(target),
            "removed_setup_id": stamp["setup_id"],
            "removed_profile_id": None if is_legacy_stamp(stamp) else stamp["profile_id"],
            "removed_legacy": is_legacy_stamp(stamp),
            "backup_slot": backup_slot,
            "builder": {"projection": "native-plugin", "enabled": False},
        }


def is_sensitive_env_key(key: str) -> bool:
    upper = key.upper()
    if upper in SECRET_ENV_EXACT:
        return True
    if upper.startswith(SECRET_ENV_PREFIXES) or upper.startswith(LOADER_ENV_PREFIXES):
        return True
    return any(fragment in upper for fragment in SECRET_ENV_SUBSTRINGS)


def build_launch_env(target: Path) -> dict[str, str]:
    xdg = target / ".xdg"
    tmp = target / ".tmp"
    env: dict[str, str] = {
        "HOME": str(target),
        "PATH": DEFAULT_PATH,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", os.environ.get("LANG", "C.UTF-8")),
        "TMPDIR": str(tmp),
        "XDG_CONFIG_HOME": str(xdg / "config"),
        "XDG_DATA_HOME": str(xdg / "data"),
        "XDG_STATE_HOME": str(xdg / "state"),
        "XDG_CACHE_HOME": str(xdg / "cache"),
    }
    if "TERM" in os.environ and not is_sensitive_env_key("TERM"):
        env["TERM"] = os.environ["TERM"]
    for directory in (
        tmp,
        Path(env["XDG_CONFIG_HOME"]),
        Path(env["XDG_DATA_HOME"]),
        Path(env["XDG_STATE_HOME"]),
        Path(env["XDG_CACHE_HOME"]),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, OWNER_DIR_MODE)
    return env


def validate_launch_args(child_args: list[str]) -> None:
    for argument in child_args:
        if argument == "--":
            continue
        for option in MANAGED_LAUNCH_OPTION_NAMES:
            if argument == option or argument.startswith(f"{option}="):
                fail(
                    "launch argument overrides managed Antigravity CLI setup scope: "
                    f"{argument}"
                )


def launch_handoff_directories(target: Path) -> tuple[Path, ...]:
    return (
        managed_cli_path(target).parent,
        software_root(target).parent,
        software_root(target),
        software_root(target) / "versions",
        software_version_dir(target),
    )


@contextlib.contextmanager
def protected_launch_handoff(target: Path) -> Iterator[None]:
    opened: list[tuple[Path, int]] = []
    try:
        for path in launch_handoff_directories(target):
            descriptor, _ = open_owner_directory_fd(
                path,
                f"launch handoff directory {path}",
                {OWNER_DIR_MODE, OWNER_READ_EXEC_DIR_MODE},
            )
            opened.append((path, descriptor))
        for path, descriptor in opened:
            set_directory_fd_mode(
                descriptor,
                path,
                f"launch handoff directory {path}",
                OWNER_READ_EXEC_DIR_MODE,
            )
        yield
    finally:
        for path, descriptor in reversed(opened):
            with contextlib.suppress(FileNotFoundError, OSError, ManagerError):
                set_directory_fd_mode(
                    descriptor,
                    path,
                    f"launch handoff directory {path}",
                    OWNER_DIR_MODE,
                )
            os.close(descriptor)


def recheck_launch_executable(target: Path, stamp: dict[str, Any]) -> Path:
    executable = managed_cli_path(target)
    version_executable = software_tree_binary_path(target)
    if not executable.is_absolute() or executable.is_symlink():
        fail("managed agy executable must be an absolute non-symlink path")
    executable_info = require_executable_file(
        executable,
        f"managed agy executable {executable}",
    )
    executable_content, executable_read_info = read_regular_file(
        executable,
        f"managed agy executable {executable}",
        owner_only=False,
        max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
    )
    if identity_of(executable_info) != identity_of(executable_read_info):
        raise ConcurrentTargetChange("managed agy executable changed before launch")
    if sha256_bytes(executable_content) != stamp["binary_sha256"]:
        fail("managed agy executable digest mismatch before launch")
    version_info = require_executable_file(
        version_executable,
        f"managed software version binary {version_executable}",
    )
    version_content, version_read_info = read_regular_file(
        version_executable,
        f"managed software version binary {version_executable}",
        owner_only=False,
        max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
    )
    if identity_of(version_info) != identity_of(version_read_info):
        raise ConcurrentTargetChange("managed software version binary changed before launch")
    if sha256_bytes(version_content) != stamp["binary_sha256"]:
        fail("managed software version binary digest mismatch before launch")
    return executable


def launch_ready_stamp_unlocked(target: Path, child_args: list[str]) -> dict[str, Any]:
    validate_launch_args(child_args)
    require_clean_current(target)
    status = software_status(target)
    if not status["installed"] or not status["current"]:
        fail("launch requires current target-owned Antigravity CLI software")
    stamp = load_software_stamp(target)
    if stamp is None:
        fail("launch requires target-owned Antigravity CLI software stamp")
    return stamp


def validate_launch_ready_unlocked(target: Path, child_args: list[str]) -> Path:
    stamp = launch_ready_stamp_unlocked(target, child_args)
    return recheck_launch_executable(target, stamp)


def validate_launch_ready(target: Path, child_args: list[str]) -> Path:
    with target_lock(target, create=False):
        return validate_launch_ready_unlocked(target, child_args)


def launch(target: Path, child_args: list[str]) -> int:
    with target_lock(target, create=False):
        stamp = launch_ready_stamp_unlocked(target, child_args)
        env = build_launch_env(target)
        with protected_launch_handoff(target):
            executable = recheck_launch_executable(target, stamp)
            process = subprocess.Popen([str(executable), *child_args], env=env)
            return process.wait()


def emit(payload: dict[str, Any] | list[Any], *, as_json: bool) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list available setups and profiles")
    list_parser.add_argument("--json", action="store_true")

    for name in ("status", "remove"):
        command = subparsers.add_parser(name)
        command.add_argument("--target")
        command.add_argument("--json", action="store_true")

    software_status_parser = subparsers.add_parser("software-status")
    software_status_parser.add_argument("--target")
    software_status_parser.add_argument("--json", action="store_true")

    for name in ("install-cli", "update-cli"):
        command = subparsers.add_parser(name)
        command.add_argument("--target")
        command.add_argument("--json", action="store_true")

    for name in ("plan", "install", "apply", "switch", "migrate"):
        command = subparsers.add_parser(name)
        command.add_argument("--setup", default=DEFAULT_SETUP_ID)
        command.add_argument("--profile", default=DEFAULT_PROFILE_ID)
        command.add_argument("--target")
        command.add_argument("--json", action="store_true")

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", required=True, type=int)
    restore_parser.add_argument("--target")
    restore_parser.add_argument("--json", action="store_true")

    launch_parser = subparsers.add_parser("launch")
    launch_parser.add_argument("--target")
    launch_parser.add_argument("child_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def wants_json(argv: list[str]) -> bool:
    return "--json" in argv


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(raw_argv)
        if args.command == "list":
            emit(
                {
                    "default_setup_id": DEFAULT_SETUP_ID,
                    "default_profile_id": DEFAULT_PROFILE_ID,
                    "setups": list_setups(),
                    "profiles": list_profiles(),
                },
                as_json=args.json,
            )
            return 0
        if args.command == "status":
            emit(current_status(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "software-status":
            emit(software_status(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command in {"install-cli", "update-cli"}:
            emit(install_cli(resolve_target(args.target), args.command), as_json=args.json)
            return 0
        if args.command == "plan":
            emit(
                plan_setup(resolve_target(args.target), args.setup, args.profile),
                as_json=args.json,
            )
            return 0
        if args.command in {"install", "apply", "switch"}:
            action = "install" if args.command == "apply" else args.command
            emit(
                mutate_setup(resolve_target(args.target), args.setup, args.profile, action),
                as_json=args.json,
            )
            return 0
        if args.command == "migrate":
            emit(
                migrate_setup(resolve_target(args.target), args.setup, args.profile),
                as_json=args.json,
            )
            return 0
        if args.command == "restore":
            emit(restore_backup(resolve_target(args.target), args.backup), as_json=args.json)
            return 0
        if args.command == "remove":
            emit(remove_setup(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "launch":
            child_args = list(args.child_args)
            if child_args and child_args[0] == "--":
                child_args = child_args[1:]
            return launch(resolve_target(args.target), child_args)
        fail(f"unsupported command: {args.command}")
    except ManagerError as exc:
        if wants_json(raw_argv):
            print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        else:
            print(f"nddev-antigravity-cli: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
