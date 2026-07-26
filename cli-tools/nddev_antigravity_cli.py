#!/usr/bin/env python3
"""Target-explicit Antigravity CLI setup manager for NDDev.

The manager writes one selected setup into an explicit isolated HOME target. It
never infers or mutates the caller's live ``~/.gemini/antigravity-cli`` state.
Only selected settings keys, the native NDDev builder plugin projection, and
the target-bound stamp are owned; sibling settings keys and unrelated files are
preserved.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from io import BytesIO
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-antigravity-cli-app"
STAMP_NAME = "NDDEV-ANTIGRAVITY-CLI-SETUP.json"
BACKUP_NAME = "NDDEV-ANTIGRAVITY-CLI-BACKUP.json"
SOFTWARE_STAMP_NAME = "NDDEV-ANTIGRAVITY-CLI-SOFTWARE.json"
STAMP_SCHEMA = 1
BACKUP_SCHEMA = 1
SOFTWARE_STAMP_SCHEMA = 1
MAX_BACKUPS = 10
OWNER_FILE_MODE = 0o600
OWNER_DIR_MODE = 0o700
OWNER_EXEC_MODE = 0o700
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 1024 * 1024
SOFTWARE_ARTIFACT_MAX_BYTES = 300 * 1024 * 1024
CLI_VERSION = "1.1.7"
CLI_COMMAND = "agy"
RELEASE_BASE_URL = (
    "https://github.com/google-antigravity/antigravity-cli/releases/download/1.1.7"
)
OFFICIAL_ASSETS = {
    ("linux", "aarch64"): (
        "agy_cli_linux_arm64.tar.gz",
        "0d6d488851745e80e69b8935d063e742945811b47111994b1a6dbd27df3010d5",
    ),
    ("linux", "x86_64"): (
        "agy_cli_linux_x64.tar.gz",
        "946cd06258d0ede72d0311550c914315798821f6a397f53ac760919826a19af4",
    ),
    ("darwin", "aarch64"): (
        "agy_cli_mac_arm64.tar.gz",
        "1ed31957d30e2d9735b1ce545a1e9106233bf7ce07739ea1f883957f5d240bed",
    ),
    ("darwin", "x86_64"): (
        "agy_cli_mac_x64.tar.gz",
        "67924f137f1ab884415fa5ab45de592d1d037eacb45be90f67d0bc6dd181498d",
    ),
}
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
SETTINGS = ".gemini/antigravity-cli/settings.json"
BUILDER_PLUGIN = ".gemini/antigravity-cli/plugins/nddev-builder/plugin.json"
BUILDER_SKILL = ".gemini/antigravity-cli/plugins/nddev-builder/skills/nddev-builder/SKILL.md"
BUILDER_AGENT = ".gemini/antigravity-cli/plugins/nddev-builder/agents/nddev-builder.md"
BUILDER_RULE = ".gemini/antigravity-cli/plugins/nddev-builder/rules/nddev-builder.md"
MANAGED_FILES = (SETTINGS, BUILDER_PLUGIN, BUILDER_SKILL, BUILDER_AGENT, BUILDER_RULE)
SETTINGS_MANAGED_KEYS = (
    "toolPermission",
    "artifactReviewPolicy",
    "enableTerminalSandbox",
    "allowNonWorkspaceAccess",
)
STAMP_KEYS = {
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
    "source_setup_id",
    "managed_files",
    "stamp_sha256",
}
SECRET_ENV_PREFIXES = ("GOOGLE_", "GEMINI_", "ANTHROPIC_", "OPENAI_", "AWS_", "AZURE_")
SECRET_ENV_NAMES = {
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
}
INTERNAL_ARTIFACT_ENV = "NDDEV_ANTIGRAVITY_CLI_TEST_ARTIFACT_URL"
INTERNAL_FAIL_AFTER_VERSION_SWAP_ENV = "NDDEV_ANTIGRAVITY_CLI_TEST_FAIL_AFTER_VERSION_SWAP"


class ManagerError(Exception):
    """A structured user-facing lifecycle failure."""


class ConcurrentTargetChange(ManagerError):
    """A fail-closed target race or identity change."""


@dataclass(frozen=True)
class Setup:
    setup_id: str
    description: str
    managed_settings: dict[str, Any]
    managed_files: tuple[str, ...]
    builder_enabled: bool
    files: dict[str, bytes]


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


def identity_of(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def owner_of(info: os.stat_result) -> int | None:
    return info.st_uid if hasattr(info, "st_uid") else None


def is_owner_only_file(info: os.stat_result) -> bool:
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        return False
    if hasattr(os, "geteuid") and owner_of(info) != os.geteuid():
        return False
    return True


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
        if opened.st_size > max_bytes:
            fail(f"{label} exceeds the {max_bytes}-byte size limit")
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


def validate_setup_id(setup_id: str) -> None:
    if not SETUP_ID_PATTERN.fullmatch(setup_id):
        fail(f"invalid setup id: {setup_id!r}")


def expected_settings_for(setup_id: str) -> dict[str, Any]:
    if setup_id == "safe":
        return {
            "toolPermission": "strict",
            "artifactReviewPolicy": "asks-for-review",
            "enableTerminalSandbox": True,
            "allowNonWorkspaceAccess": False,
        }
    if setup_id == "balanced":
        return {
            "toolPermission": "proceed-in-sandbox",
            "artifactReviewPolicy": "agent-decides",
            "enableTerminalSandbox": True,
            "allowNonWorkspaceAccess": False,
        }
    if setup_id == "full-auto":
        return {
            "toolPermission": "always-proceed",
            "artifactReviewPolicy": "always-proceed",
            "enableTerminalSandbox": True,
            "allowNonWorkspaceAccess": True,
        }
    fail(f"unsupported setup id: {setup_id}")


def render_setup(setup_id: str) -> Setup:
    validate_setup_id(setup_id)
    setup_root = CATALOG_ROOT / setup_id
    if not setup_root.is_dir() or setup_root.is_symlink():
        fail(f"unknown setup: {setup_id}")
    metadata = read_json_file(setup_root / "setup.json", f"setup {setup_id} metadata")
    expected_keys = {
        "schema_version",
        "id",
        "description",
        "managed_files",
        "managed_settings",
        "builder_enabled",
    }
    if set(metadata) != expected_keys:
        fail(f"setup {setup_id} metadata has invalid keys")
    if metadata["schema_version"] != 1 or metadata["id"] != setup_id:
        fail(f"setup {setup_id} metadata identity or schema is invalid")
    if metadata["managed_files"] != list(MANAGED_FILES):
        fail(f"setup {setup_id} managed file declaration is invalid")
    if metadata["managed_settings"] != expected_settings_for(setup_id):
        fail(f"setup {setup_id} managed settings declaration is invalid")
    if metadata["builder_enabled"] is not True:
        fail(f"setup {setup_id} must enable the native nddev-builder plugin")
    if not isinstance(metadata["description"], str) or not metadata["description"].strip():
        fail(f"setup {setup_id} description must be non-empty")

    source_paths = {
        SETTINGS: "settings.json",
        BUILDER_PLUGIN: "plugins/nddev-builder/plugin.json",
        BUILDER_SKILL: "plugins/nddev-builder/skills/nddev-builder/SKILL.md",
        BUILDER_AGENT: "plugins/nddev-builder/agents/nddev-builder.md",
        BUILDER_RULE: "plugins/nddev-builder/rules/nddev-builder.md",
    }
    files: dict[str, bytes] = {}
    for relative, source in source_paths.items():
        path = setup_root / safe_relative_path(source)
        content, _ = read_regular_file(path, f"setup {setup_id}/{source}")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            fail(f"setup {setup_id}/{source} must be UTF-8: {exc}")
        if not content or not content.endswith(b"\n") or b"\r" in content:
            fail(f"setup {setup_id}/{source} must be non-empty LF-terminated text")
        files[relative] = content

    settings = parse_json_object(files[SETTINGS], f"setup {setup_id}/settings.json")
    if settings != expected_settings_for(setup_id):
        fail(f"setup {setup_id}/settings.json does not match the product permission model")
    plugin = parse_json_object(files[BUILDER_PLUGIN], f"setup {setup_id}/plugin.json")
    if plugin != {
        "$schema": "https://antigravity.google/schemas/v1/plugin.json",
        "name": "nddev-builder",
        "description": "NDDev setup-module builder capabilities for Antigravity CLI.",
    }:
        fail(f"setup {setup_id}/plugin.json is not a compliant nddev-builder plugin")
    return Setup(
        setup_id=setup_id,
        description=metadata["description"],
        managed_settings=metadata["managed_settings"],
        managed_files=tuple(metadata["managed_files"]),
        builder_enabled=True,
        files=files,
    )


def list_setups() -> list[dict[str, Any]]:
    if not CATALOG_ROOT.is_dir() or CATALOG_ROOT.is_symlink():
        fail("setup catalog is missing or unsafe")
    result: list[dict[str, Any]] = []
    for candidate in sorted(CATALOG_ROOT.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or candidate.is_symlink():
            fail(f"catalog entry must be a real directory: {candidate.name}")
        setup = render_setup(candidate.name)
        result.append(
            {
                "id": setup.setup_id,
                "description": setup.description,
                "managed_files": list(setup.managed_files),
                "managed_settings": setup.managed_settings,
                "builder_enabled": setup.builder_enabled,
            }
        )
    if not result:
        fail("setup catalog is empty")
    return result


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
        target.mkdir(mode=OWNER_DIR_MODE)
        os.chmod(target, OWNER_DIR_MODE)
        return True
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("--target must be a real directory")
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


def software_stamp_path(target: Path) -> Path:
    return software_root(target) / SOFTWARE_STAMP_NAME


def expected_official_source(asset_name: str) -> str:
    return f"{RELEASE_BASE_URL}/{asset_name}"


def software_tree_binary_path(target: Path, version: str = CLI_VERSION) -> Path:
    return software_version_dir(target, version) / CLI_COMMAND


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


def compose_settings(current: dict[str, Any], setup_settings: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for key in SETTINGS_MANAGED_KEYS:
        result[key] = setup_settings[key]
    return result


def strip_managed_settings(current: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for key in SETTINGS_MANAGED_KEYS:
        result.pop(key, None)
    return result


def desired_for_setup(target: Path, setup: Setup) -> dict[str, bytes | None]:
    current = read_target_settings_if_present(target) if target.exists() else {}
    setup_settings = parse_json_object(setup.files[SETTINGS], "setup settings.json")
    desired = dict(setup.files)
    desired[SETTINGS] = canonical_json(compose_settings(current, setup_settings))
    return desired


def stamp_payload(target: Path, setup_id: str, desired: dict[str, bytes | None]) -> dict[str, Any]:
    managed_files: dict[str, str | None] = {}
    for relative in MANAGED_FILES:
        content = desired.get(relative)
        managed_files[relative] = None if content is None else managed_digest(relative, content)
    return {
        "schema_version": STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "setup_id": setup_id,
        "canonical_target": str(target),
        "managed_files": managed_files,
        "builder": {
            "projection": "native-plugin",
            "enabled": True,
            "marketplace": None,
            "files": [BUILDER_PLUGIN, BUILDER_SKILL, BUILDER_AGENT, BUILDER_RULE],
        },
    }


def validate_digest_map(value: Any, label: str) -> dict[str, str | None]:
    if not isinstance(value, dict) or set(value) != set(MANAGED_FILES):
        fail(f"{label} must declare exactly {list(MANAGED_FILES)}")
    result: dict[str, str | None] = {}
    for name in MANAGED_FILES:
        digest = value[name]
        if digest is not None and (
            not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest)
        ):
            fail(f"{label}.{name} must be null or a lowercase SHA-256 digest")
        result[name] = digest
    return result


def load_stamp(target: Path) -> dict[str, Any] | None:
    if not ensure_target_directory(target, create=False):
        return None
    if not target_file_exists(target, STAMP_NAME):
        return None
    content = read_target_file(target, STAMP_NAME, max_bytes=METADATA_MAX_BYTES)
    stamp = parse_json_object(content, f"managed stamp {target / STAMP_NAME}")
    if set(stamp) != STAMP_KEYS:
        fail("managed stamp has invalid keys")
    if stamp["schema_version"] != STAMP_SCHEMA or stamp["product_name"] != PRODUCT_NAME:
        fail("managed stamp identity or schema is invalid")
    if stamp["canonical_target"] != str(target):
        fail("managed stamp is bound to a different canonical target")
    if not isinstance(stamp["setup_id"], str):
        fail("managed stamp setup_id must be a string")
    validate_setup_id(stamp["setup_id"])
    validate_digest_map(stamp["managed_files"], "managed stamp managed_files")
    builder = stamp["builder"]
    if not isinstance(builder, dict) or builder.get("projection") != "native-plugin":
        fail("managed stamp builder projection is invalid")
    if builder.get("enabled") is not True or builder.get("marketplace") is not None:
        fail("managed stamp builder state is invalid")
    return stamp


def detect_drift(target: Path, stamp: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    expected = validate_digest_map(stamp["managed_files"], "managed stamp managed_files")
    for relative in MANAGED_FILES:
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
    try:
        os.chmod(path.parent, OWNER_DIR_MODE)
    except OSError:
        pass


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


def current_platform_asset() -> tuple[str, str]:
    system = sys.platform
    if system.startswith("linux"):
        os_id = "linux"
    elif system == "darwin":
        os_id = "darwin"
    else:
        fail(f"unsupported Antigravity CLI installer platform: {system}")
    machine = os.uname().machine.lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        arch = "aarch64"
    else:
        fail(f"unsupported Antigravity CLI installer architecture: {machine}")
    return OFFICIAL_ASSETS[(os_id, arch)]


def read_artifact(source: str) -> bytes:
    if source.startswith("file://"):
        path = Path(source[7:])
        content, _ = read_regular_file(
            path,
            f"software artifact {path}",
            max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
        )
        return content
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


def extract_cli_binary(archive: bytes, asset_name: str) -> bytes:
    if asset_name.endswith(".tar.gz"):
        return extract_cli_binary_from_tar(archive)
    if asset_name.endswith(".zip"):
        return extract_cli_binary_from_zip(archive)
    fail(f"unsupported Antigravity CLI artifact type: {asset_name}")


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
    return path.name in {CLI_COMMAND, "agy.exe"}


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


def zip_member_file_type(info: zipfile.ZipInfo) -> int:
    mode = (info.external_attr >> 16) & 0o170000
    return mode


def extract_cli_binary_from_zip(archive: bytes) -> bytes:
    candidates: list[bytes] = []
    seen: set[str] = set()
    with zipfile.ZipFile(BytesIO(archive)) as archive_file:
        for info in archive_file.infolist():
            path = validate_archive_member_path(info.filename, "zip")
            normalized = path.as_posix()
            if normalized in seen:
                fail("software artifact contains duplicate zip member paths")
            seen.add(normalized)
            if info.is_dir():
                continue
            file_type = zip_member_file_type(info)
            if file_type == stat.S_IFLNK:
                if is_cli_candidate(path):
                    fail("software artifact CLI candidate must not be a zip symlink")
                continue
            if file_type not in {0, stat.S_IFREG} and is_cli_candidate(path):
                fail("software artifact CLI candidate must be a regular zip file")
            if info.file_size > SOFTWARE_ARTIFACT_MAX_BYTES:
                fail("software artifact CLI binary exceeds the decompressed size limit")
            if not is_cli_candidate(path):
                continue
            with archive_file.open(info, "r") as handle:
                content = handle.read(SOFTWARE_ARTIFACT_MAX_BYTES + 1)
            if len(content) > SOFTWARE_ARTIFACT_MAX_BYTES or len(content) != info.file_size:
                fail("software artifact CLI binary size changed while reading")
            candidates.append(content)
            if len(candidates) > 1:
                fail("software artifact contains duplicate CLI binary candidates")
    if len(candidates) != 1:
        fail(f"software artifact must contain exactly one {CLI_COMMAND} binary")
    return candidates[0]


def software_stamp(
    target: Path,
    *,
    asset_name: str,
    artifact_sha256: str,
    binary_sha256: str,
    source_url: str,
) -> dict[str, Any]:
    return {
        "schema_version": SOFTWARE_STAMP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(target),
        "command": CLI_COMMAND,
        "version": CLI_VERSION,
        "official_source": source_url,
        "asset_name": asset_name,
        "artifact_sha256": artifact_sha256,
        "binary_sha256": binary_sha256,
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
        "official_source",
        "asset_name",
        "artifact_sha256",
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
    for key in ("build_version", "version", "official_source", "asset_name"):
        if not isinstance(stamp[key], str) or not stamp[key]:
            fail(f"software stamp {key} must be a non-empty string")
    for key in ("artifact_sha256", "binary_sha256"):
        if not isinstance(stamp[key], str) or not SHA256_PATTERN.fullmatch(stamp[key]):
            fail(f"software stamp {key} must be a lowercase SHA-256 digest")
    if not isinstance(stamp["installed_at"], int):
        fail("software stamp installed_at must be an integer")
    return stamp


def read_optional_software_file(path: Path, label: str) -> bytes | None:
    if not path.exists() and not path.is_symlink():
        return None
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
        binary_content = read_optional_software_file(binary, f"managed software binary {binary}")
        version_binary_content = read_optional_software_file(
            version_binary, f"managed software version binary {version_binary}"
        )
        if binary_content is None:
            drift.append("bin/agy")
        else:
            if sha256_bytes(binary_content) != stamp["binary_sha256"]:
                drift.append("bin/agy")
        if version_binary_content is None:
            drift.append(
                str(
                    Path(".nddev-software/antigravity-cli/versions")
                    / CLI_VERSION
                    / CLI_COMMAND
                )
            )
        elif sha256_bytes(version_binary_content) != stamp["binary_sha256"]:
            drift.append(
                str(
                    Path(".nddev-software/antigravity-cli/versions")
                    / CLI_VERSION
                    / CLI_COMMAND
                )
            )
        installed = (
            binary_content is not None
            and version_binary_content is not None
            and sha256_bytes(binary_content) == stamp["binary_sha256"]
            and sha256_bytes(version_binary_content) == stamp["binary_sha256"]
        )
        expected_asset, expected_artifact_sha = current_platform_asset()
        expected_source = expected_official_source(expected_asset)
        expected_identity = {
            "build_version": VERSION,
            "version": CLI_VERSION,
            "asset_name": expected_asset,
            "artifact_sha256": expected_artifact_sha,
            "official_source": expected_source,
        }
        for key, expected in expected_identity.items():
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
            and any(
                path.is_file() or path.is_symlink()
                for path in software_root(target).rglob("*")
            )
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
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"{label} must be a real directory")
        return
    path.mkdir(mode=OWNER_DIR_MODE, parents=True)
    os.chmod(path, OWNER_DIR_MODE)


def prepare_cli_artifact() -> dict[str, Any]:
    asset_name, expected_sha = current_platform_asset()
    test_artifact_url = os.environ.get(INTERNAL_ARTIFACT_ENV)
    source_url = test_artifact_url or expected_official_source(asset_name)
    archive = read_artifact(source_url)
    artifact_digest = sha256_bytes(archive)
    if test_artifact_url is None and artifact_digest != expected_sha:
        fail(f"official artifact digest mismatch for {asset_name}")
    binary = extract_cli_binary(archive, asset_name)
    binary_digest = sha256_bytes(binary)
    return {
        "asset_name": asset_name,
        "artifact_sha256": artifact_digest,
        "binary": binary,
        "binary_sha256": binary_digest,
        "source_url": source_url,
    }


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
    before_binary = None
    before_stamp = None
    binary_path = managed_cli_path(target)
    stamp_path = software_stamp_path(target)
    version_dir = software_version_dir(target)
    version_binary = software_tree_binary_path(target)
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
    before_version_exists = False
    root = software_root(target)
    versions = root / "versions"
    ensure_real_directory_path(root, "software root")
    ensure_real_directory_path(versions, "software versions directory")
    if version_dir.exists() or version_dir.is_symlink():
        info = version_dir.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail("software version path is unsafe")
        before_version_exists = True
    reject_symlink_ancestors(target, "bin/agy")
    reject_symlink_ancestors(
        target, ".nddev-software/antigravity-cli/versions/1.1.7/agy"
    )
    staging = versions / f".stage-{os.getpid()}-{time.time_ns()}"
    rollback_version = versions / f".rollback-{os.getpid()}-{time.time_ns()}"
    changed = []
    if before_binary != artifact["binary"]:
        changed.append("bin/agy")
    before_version_binary = read_optional_software_file(
        version_binary, f"managed software version binary {version_binary}"
    )
    if before_version_binary != artifact["binary"]:
        changed.append(str(Path(".nddev-software/antigravity-cli/versions/1.1.7") / CLI_COMMAND))
    stamp_bytes = canonical_json(
        software_stamp(
            target,
            asset_name=artifact["asset_name"],
            artifact_sha256=artifact["artifact_sha256"],
            binary_sha256=artifact["binary_sha256"],
            source_url=artifact["source_url"],
        )
    )
    if before_stamp != stamp_bytes:
        changed.append(str(Path(".nddev-software/antigravity-cli") / SOFTWARE_STAMP_NAME))
    try:
        staging.mkdir(mode=OWNER_DIR_MODE)
        atomic_write_executable(staging / CLI_COMMAND, artifact["binary"])
        if before_version_exists:
            version_dir.rename(rollback_version)
        staging.rename(version_dir)
        if os.environ.get(INTERNAL_FAIL_AFTER_VERSION_SWAP_ENV) == "1":
            fail("injected failure after software version swap")
        atomic_write_executable(binary_path, artifact["binary"])
        atomic_write(stamp_path, stamp_bytes)
    except BaseException:
        if version_dir.exists() or version_dir.is_symlink():
            if version_dir.is_dir() and not version_dir.is_symlink():
                shutil.rmtree(version_dir)
            else:
                version_dir.unlink()
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
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(staging)
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(rollback_version)
        raise
    finally:
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(staging)
    with contextlib.suppress(FileNotFoundError):
        shutil.rmtree(rollback_version)
    final_status = software_status(target)
    return {
        "schema_version": 1,
        "command": command,
        "operation": "install" if command == "install-cli" else "update",
        "target": str(target),
        "version": CLI_VERSION,
        "current": final_status["current"],
        "changed": changed,
        "asset_name": artifact["asset_name"],
        "artifact_sha256": artifact["artifact_sha256"],
        "binary_sha256": artifact["binary_sha256"],
        "managed_command": str(binary_path),
    }


def install_cli(target: Path, command: str) -> dict[str, Any]:
    with target_lock(target):
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
        for relative in (*MANAGED_FILES, STAMP_NAME):
            target_file_exists(target, relative)


def restore_snapshot(target: Path, snapshot: dict[str, FileSnapshot]) -> None:
    desired = {relative: item.content for relative, item in snapshot.items()}
    replace_managed_state(target, desired, None)


@contextlib.contextmanager
def target_lock(target: Path) -> Iterator[None]:
    lock = target.parent / f".{target.name}.nddev-antigravity-cli-lock"
    try:
        lock.mkdir(mode=OWNER_DIR_MODE)
    except FileExistsError:
        fail(f"target is already locked: {lock}")
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock.rmdir()


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-antigravity-cli-backups"


def choose_backup_slot(pool: Path) -> int:
    if not pool.exists():
        return 0
    slots = sorted(
        int(path.name)
        for path in pool.iterdir()
        if path.is_dir() and path.name.isdigit() and 0 <= int(path.name) < MAX_BACKUPS
    )
    if not slots:
        return 0
    return (slots[-1] + 1) % MAX_BACKUPS


def write_backup(target: Path, stamp: dict[str, Any]) -> int:
    pool = backup_pool(target)
    if pool.exists() and pool.is_symlink():
        fail("backup pool must not be a symlink")
    pool.mkdir(mode=OWNER_DIR_MODE, exist_ok=True)
    os.chmod(pool, OWNER_DIR_MODE)
    slot = choose_backup_slot(pool)
    slot_dir = pool / str(slot)
    if slot_dir.exists():
        shutil.rmtree(slot_dir)
    files_dir = slot_dir / "files"
    files_dir.mkdir(parents=True, mode=OWNER_DIR_MODE)
    managed_files: dict[str, str | None] = {}
    for relative in MANAGED_FILES:
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
        "source_setup_id": stamp["setup_id"],
        "managed_files": managed_files,
        "stamp_sha256": sha256_bytes(stamp_content),
    }
    atomic_write(slot_dir / BACKUP_NAME, canonical_json(envelope))
    return slot


def load_backup(target: Path, slot: int) -> tuple[dict[str, Any], dict[str, bytes | None]]:
    if slot < 0 or slot >= MAX_BACKUPS:
        fail("--backup must be between 0 and 9")
    slot_dir = backup_pool(target) / str(slot)
    envelope_path = slot_dir / BACKUP_NAME
    if envelope_path.is_symlink() or not envelope_path.is_file():
        fail(f"backup slot is missing: {slot}")
    envelope = read_json_file(envelope_path, f"backup slot {slot}", owner_only=False)
    if set(envelope) != BACKUP_KEYS:
        fail("backup envelope has invalid keys")
    if envelope["schema_version"] != BACKUP_SCHEMA or envelope["product_name"] != PRODUCT_NAME:
        fail("backup envelope identity or schema is invalid")
    if envelope["canonical_target"] != str(target):
        fail("backup belongs to a different canonical target")
    validate_digest_map(envelope["managed_files"], "backup managed_files")
    files: dict[str, bytes | None] = {}
    files_dir = slot_dir / "files"
    for relative in MANAGED_FILES:
        expected = envelope["managed_files"][relative]
        path = files_dir / safe_relative_path(relative)
        if expected is None:
            files[relative] = None
            continue
        content, _ = read_regular_file(path, f"backup file {relative}", owner_only=False)
        if managed_digest(relative, content) != expected:
            fail(f"backup file digest mismatch: {relative}")
        files[relative] = content
    files[STAMP_NAME] = canonical_json(stamp_payload(target, envelope["source_setup_id"], files))
    return envelope, files


def current_status(target: Path) -> dict[str, Any]:
    if not ensure_target_directory(target, create=False):
        return {
            "state": "missing",
            "target": str(target),
            "setup_id": None,
            "drift": [],
            "builder": {"projection": "native-plugin", "enabled": False},
        }
    stamp = load_stamp(target)
    if stamp is None:
        return {
            "state": "unmanaged",
            "target": str(target),
            "setup_id": None,
            "drift": [],
            "builder": {"projection": "native-plugin", "enabled": False},
        }
    drift = detect_drift(target, stamp)
    return {
        "state": "managed",
        "target": str(target),
        "setup_id": stamp["setup_id"],
        "build_version": stamp["build_version"],
        "drift": drift,
        "builder": {
            "projection": "native-plugin",
            "enabled": not any(
                item in drift
                for item in (BUILDER_PLUGIN, BUILDER_SKILL, BUILDER_AGENT, BUILDER_RULE)
            ),
        },
    }


def plan_setup(target: Path, setup_id: str) -> dict[str, Any]:
    render_setup(setup_id)
    status = current_status(target)
    if status["state"] == "missing":
        operation = "install"
        backup_required = False
    elif status["state"] == "unmanaged":
        operation = "install"
        backup_required = False
    elif status["setup_id"] == setup_id:
        operation = "update"
        backup_required = False
    else:
        operation = "switch"
        backup_required = True
    return {
        "operation": operation,
        "target": str(target),
        "setup_id": setup_id,
        "mutates": False,
        "backup_required": backup_required,
        "state": status["state"],
        "current_setup_id": status["setup_id"],
        "drift": status["drift"],
    }


def require_clean_managed(target: Path) -> dict[str, Any]:
    stamp = load_stamp(target)
    if stamp is None:
        fail("target is not managed")
    drift = detect_drift(target, stamp)
    if drift:
        fail(f"managed target has drift: {drift}")
    return stamp


def mutate_setup(target: Path, setup_id: str, action: str) -> dict[str, Any]:
    setup = render_setup(setup_id)
    with target_lock(target):
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
        backup_slot: int | None = None
        if existing_stamp is not None and existing_stamp["setup_id"] != setup_id:
            backup_slot = write_backup(target, existing_stamp)
        before = snapshot_managed_files(target)
        desired = desired_for_setup(target, setup)
        desired[STAMP_NAME] = canonical_json(stamp_payload(target, setup_id, desired))
        try:
            replace_managed_state(target, desired, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        changed = [
            relative
            for relative in MANAGED_FILES
            if before[relative].digest != sha256_bytes(desired[relative] or b"")
        ]
        return {
            "operation": "install" if existing_stamp is None else action,
            "target": str(target),
            "setup_id": setup_id,
            "changed": changed,
            "backup_slot": backup_slot,
            "builder": {"projection": "native-plugin", "enabled": True},
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    with target_lock(target):
        stamp = require_clean_managed(target)
        _, files = load_backup(target, slot)
        backup_slot = write_backup(target, stamp)
        before = snapshot_managed_files(target)
        try:
            replace_managed_state(target, files, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        restored_stamp = load_stamp(target)
        assert restored_stamp is not None
        return {
            "operation": "restore",
            "target": str(target),
            "setup_id": restored_stamp["setup_id"],
            "backup_slot": backup_slot,
            "restored_backup": slot,
            "builder": {"projection": "native-plugin", "enabled": True},
        }


def remove_setup(target: Path) -> dict[str, Any]:
    with target_lock(target):
        stamp = require_clean_managed(target)
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
            "backup_slot": backup_slot,
            "builder": {"projection": "native-plugin", "enabled": False},
        }


def build_launch_env(target: Path) -> dict[str, str]:
    xdg = target / ".xdg"
    env: dict[str, str] = {
        "HOME": str(target),
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "XDG_CONFIG_HOME": str(xdg / "config"),
        "XDG_DATA_HOME": str(xdg / "data"),
        "XDG_STATE_HOME": str(xdg / "state"),
        "XDG_CACHE_HOME": str(xdg / "cache"),
    }
    if "TERM" in os.environ:
        env["TERM"] = os.environ["TERM"]
    for directory in (
        Path(env["XDG_CONFIG_HOME"]),
        Path(env["XDG_DATA_HOME"]),
        Path(env["XDG_STATE_HOME"]),
        Path(env["XDG_CACHE_HOME"]),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, OWNER_DIR_MODE)
    for key in list(os.environ):
        if key in SECRET_ENV_NAMES or key.startswith(SECRET_ENV_PREFIXES):
            env.pop(key, None)
    return env


def launch(target: Path, child_args: list[str]) -> int:
    require_clean_managed(target)
    status = software_status(target)
    if not status["installed"] or not status["current"]:
        fail("launch requires current target-owned Antigravity CLI software")
    executable = managed_cli_path(target)
    if not executable.is_absolute() or executable.is_symlink():
        fail("managed agy executable must be an absolute non-symlink path")
    return subprocess.call([str(executable), *child_args], env=build_launch_env(target))


def emit(payload: dict[str, Any] | list[Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list available setups")
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

    for name in ("plan", "install", "apply", "switch"):
        command = subparsers.add_parser(name)
        command.add_argument("--setup", required=True)
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
            emit({"setups": list_setups()}, as_json=args.json)
            return 0
        if args.command == "status":
            emit(current_status(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "software-status":
            emit(software_status(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command in {"install-cli", "update-cli"}:
            result = install_cli(resolve_target(args.target), args.command)
            emit(result, as_json=args.json)
            return 0
        if args.command == "plan":
            emit(plan_setup(resolve_target(args.target), args.setup), as_json=args.json)
            return 0
        if args.command in {"install", "apply", "switch"}:
            action = "install" if args.command == "apply" else args.command
            emit(mutate_setup(resolve_target(args.target), args.setup, action), as_json=args.json)
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
