#!/usr/bin/env python3
"""Target-explicit Antigravity CLI setup manager for NDDev.

The manager writes one content setup plus one permission profile into an
explicit isolated HOME target. It never infers or mutates the caller's live
``~/.gemini`` or Antigravity CLI state.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
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
NATIVE_PLATFORM_SYSTEM = py_platform.system()
NATIVE_PLATFORM_MACHINE = py_platform.machine().lower()

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
EXTERNAL_LOCK_POOL_PREFIX = "nddev-antigravity-cli-app-bootstrap-locks"
BOOTSTRAP_GLOBAL_LOCK_NAME = "global.lock"
EXTERNAL_LOCK_FILE_SCHEMA = 1
CLEANUP_DIR_NAME = ".nddev-antigravity-cli-cleanup"
CLEANUP_JOURNAL_NAME = "NDDEV-ANTIGRAVITY-CLI-CLEANUP.json"
CLEANUP_STAGE_NAME = "NDDEV-ANTIGRAVITY-CLI-CLEANUP-STAGE.json"
CLEANUP_DRAIN_NAME = "NDDEV-ANTIGRAVITY-CLI-CLEANUP-DRAIN.json"
CLEANUP_SCHEMA = 1
CLEANUP_STAGE_SCHEMA = 1
CLEANUP_DRAIN_SCHEMA = 1
CLEANUP_MAX_PAYLOADS = 6
CLEANUP_DIGEST_MAX_ENTRIES = 20_000
CLEANUP_DIGEST_MAX_BYTES = 2 * 1024 * 1024 * 1024
CLEANUP_JOURNAL_MAX_BYTES = 16 * 1024 * 1024
CLEANUP_STAGE_MAX_BYTES = 2 * CLEANUP_JOURNAL_MAX_BYTES
OS_RELEASE_MAX_BYTES = 128 * 1024
OS_RELEASE_PATHS = (Path("/etc/os-release"), Path("/usr/lib/os-release"))
AT_FDCWD = -100
DARWIN_RENAME_EXCL = 0x00000004
LINUX_RENAME_NOREPLACE = 1
LINUX_RENAMEAT2_SYSCALLS = {
    "x86_64": 316,
    "amd64": 316,
    "aarch64": 276,
    "arm64": 276,
}

CLI_VERSION = "1.1.8"
CLI_COMMAND = "agy"
UPSTREAM_CLI_MEMBER_NAMES = frozenset({CLI_COMMAND, "antigravity"})
SUPPORTED_PUBLIC_HOSTS = (
    "macos-arm64",
    "macos-x64",
    "ubuntu-glibc-arm64",
    "ubuntu-glibc-x64",
)
OFFICIAL_PLATFORM_BY_HOST = {
    "macos-arm64": "darwin_arm64",
    "macos-x64": "darwin_amd64",
    "ubuntu-glibc-arm64": "linux_arm64",
    "ubuntu-glibc-x64": "linux_amd64",
}
OFFICIAL_UNSUPPORTED_PLATFORMS = {
    "windows": ("windows_arm64", "windows_amd64"),
}

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
        "version": "1.1.8",
        "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.1.8-5636713813508096/darwin-x64/cli_mac_x64.tar.gz",
        "sha512": "4431a79007106ebca77ba6d0f109345078554d0e44af69bd6976bddf16d2e4d6974ac88944e5f109be26dc602f2f80dd00f589700bc9da1753a07627422f36c7",
    },
    "darwin_arm64": {
        "version": "1.1.8",
        "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.1.8-5636713813508096/darwin-arm/cli_mac_arm64.tar.gz",
        "sha512": "4bc264e7dc670d238b62abf70f72f3b0dd4ee66f15c96b160fa2d3a6de0e02f6cb965861337735fd7fcfa221549e34ee4e58f9d1132b44f2fae0b42081686649",
    },
    "linux_amd64": {
        "version": "1.1.8",
        "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.1.8-5636713813508096/linux-x64/cli_linux_x64.tar.gz",
        "sha512": "da42fec700805feb25c37339df9ed3a2129ead93be3c324a468ed1f536c1158eb6ba228ec3ee36f9f211cb0fe56e9fe06a7fdad034d59c35f940ec270b313840",
    },
    "linux_arm64": {
        "version": "1.1.8",
        "url": "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.1.8-5636713813508096/linux-arm/cli_linux_arm64.tar.gz",
        "sha512": "4f945d28ce04cd1158c107d238f881dd7efadd591b793a768d40af582402876e1c30bf503544081084cb6b559b7796553ee6accd28376b45e1de84b4518bd9e3",
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


class BootstrapColdReadRace(Exception):
    """A cold read raced with bootstrap anchor publication and must retry."""


class CleanupJournalPublicationError(ManagerError):
    """A cleanup journal reached its final path before a later durable step failed."""


class AntigravityArgumentError(Exception):
    """Argument parser error that can be emitted as one JSON object."""


class AntigravityArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise AntigravityArgumentError(message)


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


@dataclass
class DirectorySnapshot:
    exists: bool
    mode: int | None = None
    mtime_ns: int | None = None
    device: int | None = None
    inode: int | None = None


@dataclass
class ExactFileSnapshot:
    exists: bool
    data: bytes | None = None
    mode: int | None = None
    device: int | None = None
    inode: int | None = None
    mtime_ns: int | None = None
    preserved_path: Path | None = None


@dataclass
class CleanupPromotion:
    target: Path
    journal_path: Path
    stage_path: Path
    journal: dict[str, Any]
    stage: dict[str, Any]
    originals: dict[str, Path]
    promoted: list[str]
    journal_published: bool = False
    journal_durable: bool = False
    stage_published: bool = False


@dataclass
class BootstrapGlobalLockHandle:
    product_root: Path
    global_lock_path: Path
    fd: int


@dataclass
class BootstrapLockHandle:
    path: Path
    fd: int
    binding: dict[str, Any]
    product_root: Path


def fail(message: str) -> NoReturn:
    raise ManagerError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha512_bytes(value: bytes) -> str:
    return hashlib.sha512(value).hexdigest()


def sha256_file_bounded(path: Path, *, max_bytes: int, label: str) -> str:
    digest = hashlib.sha256()
    total = 0
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        fail(f"{label} cannot be opened safely: {exc}")
    try:
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                fail(f"{label} exceeds the {max_bytes}-byte size limit")
            digest.update(block)
    finally:
        os.close(fd)
    return digest.hexdigest()


def identity_of(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def owner_of(info: os.stat_result) -> int | None:
    return info.st_uid if hasattr(info, "st_uid") else None


def current_uid() -> int:
    if not hasattr(os, "geteuid"):
        fail("lifecycle coordination requires current-user ownership support")
    return os.geteuid()


def require_current_owner(info: os.stat_result, label: str) -> None:
    if hasattr(os, "geteuid") and owner_of(info) != os.geteuid():
        fail(f"{label} must be owned by the current user")


def lstat_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


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


def relative_to_target(target: Path, path: Path) -> str:
    try:
        relative = path.relative_to(target)
    except ValueError:
        fail(f"path escaped managed target: {path}")
    if not relative.parts:
        return "."
    safe_relative_path(relative.as_posix())
    return relative.as_posix()


def safe_target_path(target: Path, relative: str) -> Path:
    if relative == ".":
        return target
    return target / safe_relative_path(relative)


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


def stat_existing(path: Path, label: str) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        fail(f"{label} must not be a symlink")
    return info


def backup_directory_snapshot(path: Path) -> DirectorySnapshot:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return DirectorySnapshot(exists=False)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return DirectorySnapshot(exists=False)
    return DirectorySnapshot(
        exists=True,
        mode=stat.S_IMODE(info.st_mode),
        mtime_ns=info.st_mtime_ns,
        device=info.st_dev,
        inode=info.st_ino,
    )


def restore_backup_directory_metadata(
    path: Path | None, snapshot: DirectorySnapshot | None
) -> None:
    if path is None or snapshot is None or not snapshot.exists:
        return
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return
    if snapshot.mode is not None and stat.S_IMODE(info.st_mode) != snapshot.mode:
        os.chmod(path, snapshot.mode)
    if snapshot.mtime_ns is not None:
        current = path.lstat()
        os.utime(path, ns=(current.st_atime_ns, snapshot.mtime_ns), follow_symlinks=False)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_all_fd(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            fail("bounded write made no progress")
        offset += written


def unlink_path(path: Path) -> None:
    path.unlink()
    fsync_directory(path.parent)


def unlink_path_if_exists(path: Path) -> None:
    try:
        unlink_path(path)
    except FileNotFoundError:
        return


def rmdir_path(path: Path) -> None:
    path.rmdir()
    fsync_directory(path.parent)


def ensure_real_parent(path: Path, target: Path) -> None:
    if target not in path.parents and path != target:
        fail("managed path escaped target")
    parent = path.parent
    if parent == path:
        fail("managed path parent is invalid")
    parent.mkdir(parents=True, mode=OWNER_DIR_MODE, exist_ok=True)
    info = parent.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("managed path parent must be a real directory")
    if hasattr(os, "geteuid") and owner_of(info) != os.geteuid():
        fail("managed path parent must be owned by the current user")


def read_existing_file(path: Path, *, max_bytes: int, label: str) -> bytes | None:
    try:
        content, _ = read_regular_file(path, label, owner_only=True, max_bytes=max_bytes)
    except ManagerError:
        if not lstat_exists(path):
            return None
        raise
    return content


def atomic_rename_no_replace(source: Path, destination: Path) -> None:
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    libc = ctypes.CDLL(None, use_errno=True)
    if NATIVE_PLATFORM_SYSTEM == "Darwin":
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is None:
            fail("atomic no-replace rename is unavailable on this macOS host")
        renameatx_np.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameatx_np.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = renameatx_np(
            ctypes.c_int(AT_FDCWD),
            ctypes.c_char_p(source_bytes),
            ctypes.c_int(AT_FDCWD),
            ctypes.c_char_p(destination_bytes),
            ctypes.c_uint(DARWIN_RENAME_EXCL),
        )
    elif NATIVE_PLATFORM_SYSTEM == "Linux":
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is not None:
            renameat2.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            renameat2.restype = ctypes.c_int
            ctypes.set_errno(0)
            result = renameat2(
                ctypes.c_int(AT_FDCWD),
                ctypes.c_char_p(source_bytes),
                ctypes.c_int(AT_FDCWD),
                ctypes.c_char_p(destination_bytes),
                ctypes.c_uint(LINUX_RENAME_NOREPLACE),
            )
        else:
            syscall = getattr(libc, "syscall", None)
            syscall_number = LINUX_RENAMEAT2_SYSCALLS.get(NATIVE_PLATFORM_MACHINE)
            if syscall is None or syscall_number is None:
                fail("atomic no-replace rename is unavailable on this Linux host")
            syscall.restype = ctypes.c_long
            ctypes.set_errno(0)
            result = syscall(
                ctypes.c_long(syscall_number),
                ctypes.c_int(AT_FDCWD),
                ctypes.c_char_p(source_bytes),
                ctypes.c_int(AT_FDCWD),
                ctypes.c_char_p(destination_bytes),
                ctypes.c_uint(LINUX_RENAME_NOREPLACE),
            )
    else:
        fail("atomic no-replace rename supports only macOS and Linux")
    if result != 0:
        error = ctypes.get_errno()
        if error == 0 and result > 0:
            error = int(result)
        if error == errno.EEXIST:
            raise FileExistsError(error, os.strerror(error), str(destination))
        raise OSError(error, os.strerror(error), str(destination))


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
    normalized = Path(os.path.normpath(str(expanded)))
    if normalized == Path(normalized.anchor):
        fail("filesystem root cannot be a target")
    return normalized


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


def path_contains(container: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(container)
    except ValueError:
        return False
    return True


def resolve_parent_allowing_missing(path: Path) -> Path:
    missing: list[str] = []
    current = path
    while True:
        try:
            resolved = current.resolve(strict=True)
        except FileNotFoundError:
            if current.parent == current:
                fail(f"path parent is missing: {path}")
            missing.append(current.name)
            current = current.parent
            continue
        result = resolved
        for part in reversed(missing):
            result = result / part
        return result


def validate_target_identity_for_lock(target: Path) -> Path:
    canonical = resolve_parent_allowing_missing(target.parent) / target.name
    current = canonical.parent
    while True:
        info = stat_existing(current, "target lock identity ancestor")
        if info is not None:
            if not stat.S_ISDIR(info.st_mode):
                fail("target lock identity ancestor must be a directory")
            return canonical
        parent = current.parent
        if parent == current:
            fail("target lock identity ancestor is missing")
        current = parent


def canonical_target_identity(target: Path) -> Path:
    if not target.is_absolute():
        fail("--target must be an absolute path")
    normalized = Path(os.path.normpath(str(target)))
    if normalized == Path(normalized.anchor):
        fail("filesystem root cannot be a target")
    try:
        parent = normalized.parent.resolve(strict=True)
    except FileNotFoundError as exc:
        fail(f"canonical --target parent is missing: {exc}")
    except OSError as exc:
        fail(f"canonical --target parent cannot be resolved: {exc}")
    parent_info = require_directory(parent, "canonical --target parent")
    if stat.S_ISLNK(parent_info.st_mode):
        fail("canonical --target parent must be a real directory")
    canonical = parent / normalized.name
    try:
        target_info = canonical.lstat()
    except FileNotFoundError:
        return canonical
    if stat.S_ISLNK(target_info.st_mode) or not stat.S_ISDIR(target_info.st_mode):
        fail("--target must be a real directory")
    return canonical


def mkdir_owner_private(path: Path) -> None:
    previous_umask = os.umask(0o077)
    try:
        path.mkdir(mode=OWNER_DIR_MODE)
    finally:
        os.umask(previous_umask)


def system_temp_root() -> Path:
    try:
        candidate = Path("/private/tmp") if NATIVE_PLATFORM_SYSTEM == "Darwin" else Path("/tmp")
        base = candidate.resolve(strict=True)
    except OSError as exc:
        fail(f"bootstrap lifecycle lock base is unavailable: {exc}")
    info = require_directory(base, "bootstrap lifecycle lock system temp root")
    if stat.S_ISLNK(info.st_mode):
        fail("bootstrap lifecycle lock system temp root must be a real directory")
    mode = stat.S_IMODE(info.st_mode)
    if not (mode & stat.S_ISVTX) or not (mode & 0o002):
        fail("bootstrap lifecycle lock system temp root must be sticky and writable")
    return base


def external_lock_pool_path() -> Path:
    return system_temp_root() / f"{EXTERNAL_LOCK_POOL_PREFIX}-uid-{current_uid()}"


def external_lock_digest_for(namespace: str, identity: str) -> str:
    return sha256_bytes(f"{PRODUCT_NAME}\0{namespace}\0{identity}".encode("utf-8"))


def external_lock_digest(target: Path) -> str:
    return external_lock_digest_for("target-lifecycle", str(target))


def lexical_external_lock_digest(target: Path) -> str:
    return external_lock_digest_for("target-lifecycle-precanonical", str(target))


def external_lock_file_path(target: Path) -> Path:
    return external_lock_pool_path() / f"{external_lock_digest(target)}.lock"


def lexical_external_lock_file_path(target: Path) -> Path:
    return external_lock_pool_path() / f"{lexical_external_lock_digest(target)}.lock"


def external_lock_binding(target: Path) -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_LOCK_FILE_SCHEMA,
        "product_name": PRODUCT_NAME,
        "namespace": "target-lifecycle",
        "canonical_target": str(target),
        "canonical_target_sha256": external_lock_digest(target),
        "uid": current_uid(),
    }


def lexical_external_lock_binding(target: Path) -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_LOCK_FILE_SCHEMA,
        "product_name": PRODUCT_NAME,
        "namespace": "target-lifecycle-precanonical",
        "lexical_target": str(target),
        "lexical_target_sha256": lexical_external_lock_digest(target),
        "uid": current_uid(),
    }


def external_global_lock_binding() -> dict[str, Any]:
    return {
        "schema_version": EXTERNAL_LOCK_FILE_SCHEMA,
        "product_name": PRODUCT_NAME,
        "namespace": "product-lifecycle-global",
        "uid": current_uid(),
    }


def ensure_external_lock_pool_with_state() -> tuple[Path, bool, DirectorySnapshot]:
    system_root = system_temp_root()
    system_before = backup_directory_snapshot(system_root)
    pool = external_lock_pool_path()
    created = False
    try:
        try:
            mkdir_owner_private(pool)
            created = True
            fsync_directory(system_root)
        except FileExistsError:
            created = False
        descriptor, _ = open_owner_directory_fd(
            pool,
            "bootstrap lifecycle lock pool",
            {OWNER_DIR_MODE},
        )
        os.close(descriptor)
    except BaseException:
        if created:
            with contextlib.suppress(OSError):
                pool.rmdir()
            restore_backup_directory_metadata(system_root, system_before)
        raise
    return pool, created, system_before


def read_lock_file_descriptor(descriptor: int, label: str) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        block = os.read(descriptor, 65536)
        if not block:
            break
        total += len(block)
        if total > METADATA_MAX_BYTES:
            fail(f"{label} exceeds the bounded metadata limit")
        chunks.append(block)
    return b"".join(chunks)


def validate_external_lock_binding(descriptor: int, binding: dict[str, Any]) -> None:
    content = read_lock_file_descriptor(descriptor, "external lifecycle lock binding")
    if not content:
        fail("external lifecycle lock binding is empty")
    observed = parse_json_object(content, "external lifecycle lock binding")
    if observed != binding:
        fail("external lifecycle lock binding mismatch")


def require_external_lock_file_identity(
    descriptor: int,
    lock_file: Path,
    label: str,
) -> os.stat_result:
    lock_info = os.fstat(descriptor)
    if not stat.S_ISREG(lock_info.st_mode):
        fail(f"{label} must be a regular file")
    if lock_info.st_nlink != 1:
        fail(f"{label} must not have hard-link aliases")
    if owner_of(lock_info) != current_uid():
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(lock_info.st_mode) != OWNER_FILE_MODE:
        fail(f"{label} must be owned by the current user with mode 0600")
    try:
        path_info = lock_file.lstat()
    except FileNotFoundError as exc:
        raise ConcurrentTargetChange(f"{label} disappeared while opening") from exc
    if (
        stat.S_ISLNK(path_info.st_mode)
        or not stat.S_ISREG(path_info.st_mode)
        or identity_of(path_info) != identity_of(lock_info)
    ):
        raise ConcurrentTargetChange(f"{label} changed while opening")
    return lock_info


def open_existing_external_lock_file(path: Path, binding: dict[str, Any]) -> int:
    flags = os.O_RDWR | nofollow_flag("external lifecycle lock file")
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        fail(f"external lifecycle lock file cannot be opened safely: {exc}")
    try:
        require_external_lock_file_identity(descriptor, path, "external lifecycle lock file")
        validate_external_lock_binding(descriptor, binding)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def create_external_lock_file_atomic(path: Path, binding: dict[str, Any], root: Path) -> int:
    if root not in path.parents:
        fail("external lifecycle lock escaped product root")
    data = canonical_json(binding)
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow_flag("external lifecycle lock file")
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    parent_before = backup_directory_snapshot(path.parent)
    published = False
    fd = os.open(temporary, flags, OWNER_FILE_MODE)
    try:
        os.fchmod(fd, OWNER_FILE_MODE)
        write_all_fd(fd, data)
        os.fsync(fd)
        if read_lock_file_descriptor(fd, "external lifecycle lock binding") != data:
            fail("external lifecycle lock binding failed pre-publication verification")
        fcntl.flock(fd, fcntl.LOCK_EX)
        atomic_rename_no_replace(temporary, path)
        published = True
        require_external_lock_file_identity(fd, path, "external lifecycle lock file")
        validate_external_lock_binding(fd, binding)
        fsync_directory(path.parent)
        require_external_lock_file_identity(fd, path, "external lifecycle lock file")
        validate_external_lock_binding(fd, binding)
        return fd
    except BaseException as exc:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        if not published:
            restore_backup_directory_metadata(path.parent, parent_before)
        else:
            raise ManagerError(
                f"external lifecycle lock publication failed after final visibility: {exc}"
            ) from exc
        raise


def open_external_lock_handle(
    product_root: Path,
    path: Path,
    binding: dict[str, Any],
    *,
    create: bool,
) -> BootstrapLockHandle | None:
    if lstat_exists(path):
        fd = open_existing_external_lock_file(path, binding)
    elif not create:
        return None
    else:
        try:
            fd = create_external_lock_file_atomic(path, binding, product_root)
        except FileExistsError:
            fd = open_existing_external_lock_file(path, binding)
    return BootstrapLockHandle(path=path, fd=fd, binding=binding, product_root=product_root)


def lock_external_handle(
    handle: BootstrapLockHandle,
    *,
    exclusive: bool,
    blocking: bool,
) -> None:
    require_external_lock_file_identity(handle.fd, handle.path, "external lifecycle lock file")
    validate_external_lock_binding(handle.fd, handle.binding)
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    if not blocking:
        mode |= fcntl.LOCK_NB
    try:
        fcntl.flock(handle.fd, mode)
    except BlockingIOError:
        fail(f"target is already locked: {handle.path}")
    require_external_lock_file_identity(handle.fd, handle.path, "external lifecycle lock file")
    validate_external_lock_binding(handle.fd, handle.binding)


def release_external_handle(handle: BootstrapLockHandle | BootstrapGlobalLockHandle) -> None:
    with contextlib.suppress(OSError):
        fcntl.flock(handle.fd, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(handle.fd)


def open_external_global_lock(*, create: bool, exclusive: bool) -> BootstrapGlobalLockHandle | None:
    if create:
        product_root, root_created, system_before = ensure_external_lock_pool_with_state()
    else:
        product_root = external_lock_pool_path()
        root_created = False
        system_before = backup_directory_snapshot(system_temp_root())
        if not lstat_exists(product_root):
            return None
        descriptor, _ = open_owner_directory_fd(
            product_root,
            "bootstrap lifecycle lock pool",
            {OWNER_DIR_MODE},
        )
        os.close(descriptor)
    path = product_root / BOOTSTRAP_GLOBAL_LOCK_NAME
    binding = external_global_lock_binding()
    try:
        if lstat_exists(path):
            fd = open_existing_external_lock_file(path, binding)
        elif not create:
            return None
        else:
            try:
                fd = create_external_lock_file_atomic(path, binding, product_root)
            except FileExistsError:
                fd = open_existing_external_lock_file(path, binding)
    except BaseException:
        if root_created and not lstat_exists(path):
            with contextlib.suppress(OSError):
                product_root.rmdir()
            restore_backup_directory_metadata(system_temp_root(), system_before)
        raise
    handle = BootstrapGlobalLockHandle(
        product_root=product_root,
        global_lock_path=path,
        fd=fd,
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        validate_external_lock_binding(fd, binding)
        return handle
    except BaseException:
        os.close(fd)
        raise


def acquire_external_target_handle(
    product_root: Path,
    canonical: Path,
    *,
    create: bool,
    exclusive: bool,
    blocking: bool,
) -> BootstrapLockHandle | None:
    handle = open_external_lock_handle(
        product_root,
        product_root / f"{external_lock_digest(canonical)}.lock",
        external_lock_binding(canonical),
        create=create,
    )
    if handle is None:
        return None
    try:
        lock_external_handle(handle, exclusive=exclusive, blocking=blocking)
        return handle
    except BaseException:
        release_external_handle(handle)
        raise


def acquire_lexical_external_handle(
    product_root: Path,
    target: Path,
    *,
    create: bool,
    exclusive: bool,
    blocking: bool,
) -> BootstrapLockHandle | None:
    handle = open_external_lock_handle(
        product_root,
        product_root / f"{lexical_external_lock_digest(target)}.lock",
        lexical_external_lock_binding(target),
        create=create,
    )
    if handle is None:
        return None
    try:
        lock_external_handle(handle, exclusive=exclusive, blocking=blocking)
        return handle
    except BaseException:
        release_external_handle(handle)
        raise


def external_global_anchor_exists() -> bool:
    try:
        return lstat_exists(external_lock_pool_path() / BOOTSTRAP_GLOBAL_LOCK_NAME)
    except ManagerError:
        return False


@contextlib.contextmanager
def external_target_lock(target: Path) -> Iterator[None]:
    canonical = canonical_target_identity(target)
    product_handle = open_external_global_lock(create=True, exclusive=True)
    if product_handle is None:
        fail("bootstrap product anchor could not be created")
    target_handle: BootstrapLockHandle | None = None
    try:
        target_handle = acquire_external_target_handle(
            product_handle.product_root,
            canonical,
            create=True,
            exclusive=True,
            blocking=False,
        )
        if target_handle is None:
            fail("bootstrap target anchor could not be created")
        release_external_handle(product_handle)
        product_handle = None
        yield
    finally:
        if target_handle is not None:
            release_external_handle(target_handle)
        if product_handle is not None:
            release_external_handle(product_handle)


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


def cleanup_root(target: Path) -> Path:
    return target / CLEANUP_DIR_NAME


def cleanup_journal_path(target: Path) -> Path:
    return target / CLEANUP_JOURNAL_NAME


def cleanup_stage_path(target: Path) -> Path:
    return target / CLEANUP_STAGE_NAME


def cleanup_drain_path(target: Path) -> Path:
    return target / CLEANUP_DRAIN_NAME


def cleanup_payload_name(index: int) -> str:
    return f"payload-{index}"


def cleanup_journal_temp_prefix() -> str:
    return f".{CLEANUP_JOURNAL_NAME}.nddev.tmp."


def cleanup_stage_temp_prefix() -> str:
    return f".{CLEANUP_STAGE_NAME}.nddev.tmp."


def cleanup_drain_temp_prefix() -> str:
    return f".{CLEANUP_DRAIN_NAME}.nddev.tmp."


def cleanup_object_metadata(path: Path, root: Path, label: str) -> tuple[dict[str, Any], int]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} changed while recording cleanup graph")
    require_current_owner(info, label)
    relative = "." if path == root else path.relative_to(root).as_posix()
    mode = stat.S_IMODE(info.st_mode)
    metadata: dict[str, Any] = {
        "relative": relative,
        "uid": info.st_uid,
        "mode": mode,
        "nlink": info.st_nlink,
        "dev": info.st_dev,
        "ino": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
    }
    if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
        metadata.update({"kind": "directory", "content_sha256": None, "link_target": None})
        return metadata, 0
    if stat.S_ISREG(info.st_mode):
        if info.st_nlink != 1:
            fail(f"{label} file must not be a hardlink")
        metadata.update(
            {
                "kind": "file",
                "content_sha256": sha256_file_bounded(
                    path,
                    max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
                    label=label,
                ),
                "link_target": None,
            }
        )
        return metadata, int(info.st_size)
    if stat.S_ISLNK(info.st_mode):
        if info.st_nlink != 1:
            fail(f"{label} link must not be a hardlink")
        try:
            link_target = os.readlink(path)
        except OSError as exc:
            fail(f"{label} symlink cannot be read: {exc}")
        metadata.update(
            {
                "kind": "symlink",
                "content_sha256": sha256_bytes(link_target.encode("utf-8", "surrogateescape")),
                "link_target": link_target,
            }
        )
        return metadata, len(link_target)
    fail(f"{label} contains an unsupported filesystem object: {relative}")


def cleanup_payload_graph(path: Path, label: str) -> tuple[list[dict[str, Any]], int]:
    root_info = stat_existing(path, label)
    if root_info is None:
        fail(f"{label} is missing")
    root_metadata, root_size = cleanup_object_metadata(path, path, label)
    if root_metadata["kind"] != "directory":
        return [root_metadata], root_size
    objects = [root_metadata]
    total_bytes = root_size
    stack = [Path(".")]
    while stack:
        relative_directory = stack.pop()
        directory = path if relative_directory.as_posix() == "." else path / relative_directory
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            fail(f"{label} could not be scanned: {exc}")
        for child in children:
            metadata, size = cleanup_object_metadata(child, path, label)
            objects.append(metadata)
            total_bytes += size
            if len(objects) > CLEANUP_DIGEST_MAX_ENTRIES:
                fail(f"{label} exceeds cleanup entry bound")
            if total_bytes > CLEANUP_DIGEST_MAX_BYTES:
                fail(f"{label} exceeds cleanup byte bound")
            if metadata["kind"] == "directory":
                stack.append(child.relative_to(path))
    return sorted(objects, key=lambda item: item["relative"]), total_bytes


def cleanup_graph_digest(objects: list[dict[str, Any]], total_bytes: int) -> str:
    return sha256_bytes(canonical_json({"objects": objects, "bytes": total_bytes}))


def cleanup_payload_metadata(path: Path, label: str) -> dict[str, Any]:
    objects, total_bytes = cleanup_payload_graph(path, label)
    root = objects[0]
    return {
        "kind": root["kind"],
        "uid": root["uid"],
        "mode": root["mode"],
        "nlink": root["nlink"],
        "dev": root["dev"],
        "ino": root["ino"],
        "size": root["size"],
        "mtime_ns": root["mtime_ns"],
        "entry_count": len(objects),
        "byte_count": total_bytes,
        "objects": objects,
        "graph_digest_sha256": cleanup_graph_digest(objects, total_bytes),
    }


def cleanup_directory_identity(path: Path, label: str) -> dict[str, Any]:
    info = require_private_directory(path, label)
    return {
        "kind": "directory",
        "uid": info.st_uid,
        "mode": stat.S_IMODE(info.st_mode),
        "dev": info.st_dev,
        "ino": info.st_ino,
    }


def cleanup_metadata_index(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if metadata.get("kind") not in ("directory", "file", "symlink"):
        fail("cleanup tombstone kind is invalid")
    objects = metadata.get("objects")
    if not isinstance(objects, list) or not objects:
        fail("cleanup tombstone object graph is invalid")
    if len(objects) > CLEANUP_DIGEST_MAX_ENTRIES:
        fail("cleanup tombstone object graph exceeds entry bound")
    if metadata.get("entry_count") != len(objects):
        fail("cleanup tombstone entry count binding is invalid")
    byte_count = metadata.get("byte_count")
    if type(byte_count) is not int or byte_count < 0 or byte_count > CLEANUP_DIGEST_MAX_BYTES:
        fail("cleanup tombstone byte count binding is invalid")
    index: dict[str, dict[str, Any]] = {}
    for item in objects:
        if not isinstance(item, dict):
            fail("cleanup tombstone object graph is invalid")
        relative = item.get("relative")
        if not isinstance(relative, str) or not relative:
            fail("cleanup tombstone object relative path is invalid")
        if relative != ".":
            safe_relative_path(relative)
        if relative in index:
            fail("cleanup tombstone object graph contains duplicate paths")
        if item.get("kind") not in ("directory", "file", "symlink"):
            fail("cleanup tombstone object kind is invalid")
        for key in ("uid", "mode", "nlink", "dev", "ino", "size", "mtime_ns"):
            if type(item.get(key)) is not int:
                fail(f"cleanup tombstone object {key} is invalid")
        content = item.get("content_sha256")
        if item.get("kind") == "directory":
            if content is not None or item.get("link_target") is not None:
                fail("cleanup tombstone directory content binding is invalid")
        else:
            if not isinstance(content, str) or not SHA256_PATTERN.fullmatch(content):
                fail("cleanup tombstone object digest is invalid")
        index[relative] = item
    if "." not in index or index["."].get("kind") != metadata.get("kind"):
        fail("cleanup tombstone object graph is missing its root")
    if metadata.get("graph_digest_sha256") != cleanup_graph_digest(objects, byte_count):
        fail("cleanup tombstone graph digest binding is invalid")
    return index


def cleanup_recorded_children(
    index: dict[str, dict[str, Any]], current_relatives: set[str]
) -> dict[str, set[str]]:
    children: dict[str, set[str]] = {}
    for relative in current_relatives:
        if relative == ".":
            continue
        parent = Path(relative).parent.as_posix()
        if parent == "":
            parent = "."
        children.setdefault(parent, set()).add(Path(relative).name)
    return children


def compare_cleanup_object(
    current: dict[str, Any],
    expected: dict[str, Any],
    *,
    strict_directory: bool,
) -> None:
    stable_keys = ("relative", "kind", "uid", "mode", "dev", "ino")
    strict_keys = (
        "relative",
        "kind",
        "uid",
        "mode",
        "nlink",
        "dev",
        "ino",
        "size",
        "mtime_ns",
        "content_sha256",
        "link_target",
    )
    keys = strict_keys if expected["kind"] != "directory" or strict_directory else stable_keys
    for key in keys:
        if current.get(key) != expected.get(key):
            fail(f"cleanup tombstone object identity changed: {expected.get('relative')}")


def validate_cleanup_payload_graph(
    path: Path,
    label: str,
    metadata: dict[str, Any],
    *,
    require_complete: bool,
) -> dict[str, dict[str, Any]]:
    expected = cleanup_metadata_index(metadata)
    if not lstat_exists(path):
        if require_complete:
            fail("cleanup tombstone payload is missing")
        return {}
    current_objects, current_bytes = cleanup_payload_graph(path, label)
    current = {str(item["relative"]): item for item in current_objects}
    current_relatives = set(current)
    expected_relatives = set(expected)
    if sorted(current_relatives - expected_relatives):
        fail("cleanup tombstone contains unknown entries")
    if require_complete and current_relatives != expected_relatives:
        fail("cleanup tombstone object graph is incomplete")
    if require_complete and current_bytes != metadata.get("byte_count"):
        fail("cleanup tombstone byte count binding is invalid")
    if "." not in current:
        fail("cleanup tombstone root is missing")
    for relative, item in current.items():
        compare_cleanup_object(
            item,
            expected[relative],
            strict_directory=require_complete,
        )
    current_children = cleanup_recorded_children(expected, current_relatives)
    for relative, item in current.items():
        if item["kind"] != "directory":
            continue
        directory = path if relative == "." else path / relative
        actual_names = set(child.name for child in directory.iterdir())
        expected_names = current_children.get(relative, set())
        if actual_names != expected_names:
            fail("cleanup tombstone directory children changed")
    if require_complete and cleanup_graph_digest(current_objects, current_bytes) != metadata.get(
        "graph_digest_sha256"
    ):
        fail("cleanup tombstone graph digest binding is invalid")
    return current


def cleanup_pending_payload(
    target: Path,
    reason: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    canonical = canonical_target_identity(target)
    return {
        "schema_version": CLEANUP_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(canonical),
        "canonical_target_sha256": sha256_bytes(str(canonical).encode("utf-8")),
        "cleanup_parent": CLEANUP_DIR_NAME,
        "journal_relative": CLEANUP_JOURNAL_NAME,
        "max_payloads": CLEANUP_MAX_PAYLOADS,
        "reason": reason,
        "entries": entries,
    }


def build_cleanup_journal_projection(
    target: Path,
    reason: str,
    pending: list[tuple[Path, str]],
) -> tuple[dict[str, Any], bytes]:
    entries = []
    target_info = require_private_directory(target, "managed target")
    for index, (path, label) in enumerate(pending):
        if path == target or target not in path.parents:
            fail("cleanup tombstone source escaped managed target")
        if cleanup_root(target) == path or cleanup_root(target) in path.parents:
            fail("cleanup tombstone source escaped cleanup envelope")
        source_info = stat_existing(path, label)
        if source_info is None:
            fail(f"{label} is missing")
        require_current_owner(source_info, label)
        if source_info.st_dev != target_info.st_dev:
            fail("cleanup tombstone source must be on the managed target filesystem")
        metadata = cleanup_payload_metadata(path, label)
        entries.append(
            {
                "name": cleanup_payload_name(index),
                "label": label,
                "source_relative": relative_to_target(target, path),
                "source_kind": metadata["kind"],
                "metadata": metadata,
            }
        )
    journal = cleanup_pending_payload(target, reason, entries)
    data = canonical_json(journal)
    if len(data) > CLEANUP_JOURNAL_MAX_BYTES:
        fail("cleanup journal is too large")
    return journal, data


def cleanup_stage_payload(
    target: Path,
    reason: str,
    pending: list[tuple[Path, str]],
    journal: dict[str, Any],
    journal_data: bytes,
) -> dict[str, Any]:
    entries = []
    for index, (path, label) in enumerate(pending):
        name = cleanup_payload_name(index)
        source_parent = path.parent
        entries.append(
            {
                "name": name,
                "label": label,
                "source_relative": relative_to_target(target, path),
                "source_parent_relative": relative_to_target(target, source_parent),
                "source_parent_identity": cleanup_directory_identity(source_parent, f"{label} parent"),
                "destination_relative": name,
            }
        )
    canonical = canonical_target_identity(target)
    return {
        "schema_version": CLEANUP_STAGE_SCHEMA,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(canonical),
        "canonical_target_sha256": sha256_bytes(str(canonical).encode("utf-8")),
        "cleanup_parent": CLEANUP_DIR_NAME,
        "stage_relative": CLEANUP_STAGE_NAME,
        "journal_relative": CLEANUP_JOURNAL_NAME,
        "max_payloads": CLEANUP_MAX_PAYLOADS,
        "reason": reason,
        "journal_size": len(journal_data),
        "journal_sha256": sha256_bytes(journal_data),
        "journal": journal,
        "entries": entries,
    }


def build_cleanup_stage_projection(
    target: Path,
    reason: str,
    pending: list[tuple[Path, str]],
    journal: dict[str, Any],
    journal_data: bytes,
) -> tuple[dict[str, Any], bytes]:
    stage = cleanup_stage_payload(target, reason, pending, journal, journal_data)
    data = canonical_json(stage)
    if len(data) > CLEANUP_STAGE_MAX_BYTES:
        fail("cleanup promotion stage is too large")
    return stage, data


def cleanup_pending_summary_from_journal(target: Path, journal: dict[str, Any] | None) -> dict[str, Any]:
    if journal is None:
        return {"state": "absent", "entries": 0}
    entries = journal.get("entries")
    entry_list = entries if isinstance(entries, list) else []
    root = cleanup_root(target)
    present_entries = 0
    for entry in entry_list:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            if lstat_exists(root / entry["name"]):
                present_entries += 1
    return {
        "state": "pending",
        "reason": journal.get("reason"),
        "entries": len(entry_list),
        "present_entries": present_entries,
        "completed_entries": len(entry_list) - present_entries,
        "max_payloads": CLEANUP_MAX_PAYLOADS,
    }


def validate_cleanup_journal_document(
    target: Path,
    payload: dict[str, Any],
    *,
    require_complete: bool,
    allow_sources: bool = False,
) -> dict[str, Any]:
    canonical = str(canonical_target_identity(target))
    if payload.get("schema_version") != CLEANUP_SCHEMA:
        fail("cleanup journal schema is unsupported")
    if payload.get("product_name") != PRODUCT_NAME:
        fail("cleanup journal belongs to another product")
    if payload.get("canonical_target") != canonical:
        fail("cleanup journal is bound to a different target")
    if payload.get("canonical_target_sha256") != sha256_bytes(canonical.encode("utf-8")):
        fail("cleanup journal target digest is invalid")
    if payload.get("cleanup_parent") != CLEANUP_DIR_NAME:
        fail("cleanup journal parent binding is invalid")
    if payload.get("journal_relative") != CLEANUP_JOURNAL_NAME:
        fail("cleanup journal path binding is invalid")
    if payload.get("max_payloads") != CLEANUP_MAX_PAYLOADS:
        fail("cleanup journal bound is invalid")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason:
        fail("cleanup journal reason is invalid")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries or len(entries) > CLEANUP_MAX_PAYLOADS:
        fail("cleanup journal entries are invalid or over bound")
    root = cleanup_root(target)
    names: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            fail("cleanup journal entry is invalid")
        name = entry.get("name")
        if name != cleanup_payload_name(index) or name in names:
            fail("cleanup journal payload binding is invalid")
        label = entry.get("label")
        source_relative = entry.get("source_relative")
        source_kind = entry.get("source_kind")
        metadata = entry.get("metadata")
        if not isinstance(label, str) or not label:
            fail("cleanup journal payload label is invalid")
        if not isinstance(source_relative, str) or not source_relative:
            fail("cleanup journal source binding is invalid")
        if source_kind not in ("directory", "file", "symlink"):
            fail("cleanup journal source kind is invalid")
        if not isinstance(metadata, dict):
            fail("cleanup journal payload metadata is invalid")
        if metadata.get("kind") != source_kind:
            fail("cleanup journal source kind binding changed")
        payload_path = root / name
        original_path = safe_target_path(target, source_relative)
        if lstat_exists(payload_path):
            validate_cleanup_payload_graph(
                payload_path,
                label,
                metadata,
                require_complete=require_complete,
            )
        elif require_complete:
            fail("cleanup tombstone payload is missing")
        if lstat_exists(original_path) and not allow_sources:
            fail("cleanup journal source still exists")
        names.add(name)
    if lstat_exists(root):
        require_private_directory(root, "cleanup tombstone")
        actual = sorted(path.name for path in root.iterdir())
        unknown = sorted(set(actual) - names)
        if unknown:
            fail("cleanup tombstone contains unknown entries")
        if require_complete and actual != sorted(names):
            fail("cleanup tombstone object graph is incomplete")
    return payload


def validate_cleanup_stage(target: Path) -> dict[str, Any] | None:
    path = cleanup_stage_path(target)
    if not lstat_exists(path):
        return None
    data = read_existing_file(path, max_bytes=CLEANUP_STAGE_MAX_BYTES, label=CLEANUP_STAGE_NAME)
    if data is None:
        fail("cleanup promotion stage is missing")
    try:
        stage = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cleanup promotion stage is invalid JSON: {exc}")
    if not isinstance(stage, dict) or canonical_json(stage) != data:
        fail("cleanup promotion stage canonical binding is invalid")
    expected_keys = {
        "schema_version",
        "product_name",
        "build_version",
        "canonical_target",
        "canonical_target_sha256",
        "cleanup_parent",
        "stage_relative",
        "journal_relative",
        "max_payloads",
        "reason",
        "journal_size",
        "journal_sha256",
        "journal",
        "entries",
    }
    if set(stage) != expected_keys:
        fail("cleanup promotion stage field set is invalid")
    canonical = str(canonical_target_identity(target))
    if (
        stage["schema_version"] != CLEANUP_STAGE_SCHEMA
        or stage["product_name"] != PRODUCT_NAME
        or stage["canonical_target"] != canonical
        or stage["canonical_target_sha256"] != sha256_bytes(canonical.encode("utf-8"))
        or stage["cleanup_parent"] != CLEANUP_DIR_NAME
        or stage["stage_relative"] != CLEANUP_STAGE_NAME
        or stage["journal_relative"] != CLEANUP_JOURNAL_NAME
        or stage["max_payloads"] != CLEANUP_MAX_PAYLOADS
    ):
        fail("cleanup promotion stage identity binding is invalid")
    journal = stage["journal"]
    if not isinstance(journal, dict):
        fail("cleanup promotion stage journal is invalid")
    journal_data = canonical_json(journal)
    if stage["journal_size"] != len(journal_data) or stage["journal_sha256"] != sha256_bytes(
        journal_data
    ):
        fail("cleanup promotion stage journal binding is invalid")
    entries = stage["entries"]
    journal_entries = journal.get("entries")
    if (
        not isinstance(entries, list)
        or not isinstance(journal_entries, list)
        or len(entries) != len(journal_entries)
        or not entries
        or len(entries) > CLEANUP_MAX_PAYLOADS
    ):
        fail("cleanup promotion stage entries are invalid")
    validate_cleanup_journal_document(target, journal, require_complete=False, allow_sources=True)
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            fail("cleanup promotion stage entry is invalid")
        expected = journal_entries[index]
        if entry.get("name") != expected.get("name") or entry.get("label") != expected.get("label"):
            fail("cleanup promotion stage entry binding is invalid")
        source = safe_target_path(target, str(entry.get("source_relative")))
        destination = cleanup_root(target) / str(entry.get("destination_relative"))
        if destination.parent != cleanup_root(target):
            fail("cleanup promotion stage destination path escaped cleanup parent")
        if lstat_exists(source) and lstat_exists(destination):
            fail("cleanup promotion stage has duplicate source and tombstone payload")
        if not lstat_exists(source) and not lstat_exists(destination):
            fail("cleanup promotion stage source and tombstone payload are both missing")
    return stage


def validate_cleanup_journal(target: Path, *, allow_stage: bool = False) -> dict[str, Any] | None:
    if not lstat_exists(target):
        return None
    temp_records = [
        path.name
        for path in target.iterdir()
        if path.name.startswith(cleanup_journal_temp_prefix())
        or path.name.startswith(cleanup_stage_temp_prefix())
        or path.name.startswith(cleanup_drain_temp_prefix())
    ]
    if temp_records:
        fail("cleanup journal has intermediate residue")
    journal_path = cleanup_journal_path(target)
    stage_exists = lstat_exists(cleanup_stage_path(target))
    journal_exists = lstat_exists(journal_path)
    root_exists = lstat_exists(cleanup_root(target))
    if not journal_exists:
        if root_exists:
            fail("cleanup tombstone is unjournaled")
        if stage_exists:
            fail("cleanup promotion stage requires mutation recovery")
        return None
    data = read_existing_file(
        journal_path,
        max_bytes=CLEANUP_JOURNAL_MAX_BYTES,
        label=CLEANUP_JOURNAL_NAME,
    )
    if data is None:
        fail("cleanup journal is missing")
    try:
        journal = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cleanup journal is invalid JSON: {exc}")
    if not isinstance(journal, dict) or canonical_json(journal) != data:
        fail("cleanup journal canonical binding is invalid")
    if stage_exists and not allow_stage:
        validate_cleanup_stage(target)
    return validate_cleanup_journal_document(target, journal, require_complete=False)


def cleanup_state(target: Path) -> dict[str, Any]:
    journal = validate_cleanup_journal(target)
    return {
        "pending": journal is not None,
        "metadata": cleanup_pending_summary_from_journal(target, journal),
    }


def cleanup_pending(target: Path) -> bool:
    return bool(cleanup_state(target)["pending"])


def publish_cleanup_record_no_replace(
    path: Path,
    data: bytes,
    target: Path,
    *,
    max_bytes: int,
    validator: Any,
    final_visible_error: type[Exception] | None = None,
) -> None:
    if len(data) > max_bytes:
        fail("cleanup record is too large")
    ensure_real_parent(path, target)
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    parent_before = backup_directory_snapshot(path.parent)
    fd = -1
    published = False
    final_validated = False
    try:
        fd = os.open(
            temporary,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow_flag("cleanup record"),
            OWNER_FILE_MODE,
        )
        os.fchmod(fd, OWNER_FILE_MODE)
        write_all_fd(fd, data)
        os.lseek(fd, 0, os.SEEK_SET)
        current = os.read(fd, len(data) + 1)
        if current != data:
            fail("cleanup record content verification failed")
        os.fsync(fd)
        os.close(fd)
        fd = -1
        atomic_rename_no_replace(temporary, path)
        published = True
        validator()
        final_validated = True
        fsync_directory(path.parent)
        validator()
    except BaseException as exc:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        if not published:
            restore_backup_directory_metadata(path.parent, parent_before)
        elif final_validated and final_visible_error is not None:
            raise final_visible_error(
                f"cleanup record publication failed after final visibility: {exc}"
            ) from exc
        raise


def publish_cleanup_stage_no_replace(path: Path, data: bytes, target: Path) -> None:
    publish_cleanup_record_no_replace(
        path,
        data,
        target,
        max_bytes=CLEANUP_STAGE_MAX_BYTES,
        validator=lambda: validate_cleanup_stage(target),
    )


def validate_published_cleanup_journal(path: Path, data: bytes, target: Path) -> None:
    current = read_existing_file(path, max_bytes=CLEANUP_JOURNAL_MAX_BYTES, label=CLEANUP_JOURNAL_NAME)
    if current != data:
        fail("cleanup journal publication failed content verification")
    journal = validate_cleanup_journal(target, allow_stage=True)
    if journal is None or canonical_json(journal) != data:
        fail("cleanup journal publication failed final validation")
    for entry in journal["entries"]:
        payload = cleanup_root(target) / entry["name"]
        validate_cleanup_payload_graph(
            payload,
            entry["label"],
            entry["metadata"],
            require_complete=True,
        )


def publish_cleanup_journal_no_replace(path: Path, data: bytes, target: Path) -> None:
    publish_cleanup_record_no_replace(
        path,
        data,
        target,
        max_bytes=CLEANUP_JOURNAL_MAX_BYTES,
        validator=lambda: validate_published_cleanup_journal(path, data, target),
        final_visible_error=CleanupJournalPublicationError,
    )


def rollback_cleanup_promotion(promotion: CleanupPromotion) -> None:
    root = cleanup_root(promotion.target)
    last_error: BaseException | None = None
    if promotion.journal_published:
        return
    if lstat_exists(promotion.journal_path):
        try:
            unlink_path(promotion.journal_path)
        except BaseException as exc:
            last_error = exc
    if lstat_exists(promotion.stage_path):
        try:
            unlink_path(promotion.stage_path)
        except BaseException as exc:
            if last_error is None:
                last_error = exc
    for name in reversed(promotion.promoted):
        payload = root / name
        original = promotion.originals[name]
        if lstat_exists(payload) and not lstat_exists(original):
            try:
                ensure_real_parent(original, promotion.target)
                payload.rename(original)
                fsync_directory(original.parent)
                fsync_directory(payload.parent)
            except BaseException as exc:
                if last_error is None:
                    last_error = exc
    if lstat_exists(root):
        with contextlib.suppress(OSError):
            rmdir_path(root)
    if last_error is not None:
        raise last_error


def promote_cleanup_items(
    target: Path,
    reason: str,
    items: list[tuple[Path | None, str]],
) -> CleanupPromotion | None:
    pending = [(path, label) for path, label in items if path is not None and lstat_exists(path)]
    if not pending:
        return None
    if len(pending) > CLEANUP_MAX_PAYLOADS:
        fail("cleanup tombstone would exceed its declared bound")
    if lstat_exists(cleanup_root(target)) or lstat_exists(cleanup_journal_path(target)):
        fail("cleanup tombstone already exists")
    if lstat_exists(cleanup_stage_path(target)):
        fail("cleanup promotion stage already exists")
    journal, journal_data = build_cleanup_journal_projection(target, reason, pending)
    stage, stage_data = build_cleanup_stage_projection(target, reason, pending, journal, journal_data)
    promotion = CleanupPromotion(
        target=target,
        journal_path=cleanup_journal_path(target),
        stage_path=cleanup_stage_path(target),
        journal=journal,
        stage=stage,
        originals={},
        promoted=[],
    )
    try:
        publish_cleanup_stage_no_replace(promotion.stage_path, stage_data, target)
        promotion.stage_published = True
        cleanup_root(target).mkdir(mode=OWNER_DIR_MODE)
        fsync_directory(target)
        require_private_directory(cleanup_root(target), "cleanup tombstone")
        for index, (path, _label) in enumerate(pending):
            name = cleanup_payload_name(index)
            destination = cleanup_root(target) / name
            promotion.originals[name] = path
            path.rename(destination)
            promotion.promoted.append(name)
            fsync_directory(path.parent)
            fsync_directory(cleanup_root(target))
        for entry in journal["entries"]:
            validate_cleanup_payload_graph(
                cleanup_root(target) / entry["name"],
                entry["label"],
                entry["metadata"],
                require_complete=True,
            )
        publish_cleanup_journal_no_replace(promotion.journal_path, journal_data, target)
        promotion.journal_published = True
        try:
            if lstat_exists(promotion.stage_path):
                unlink_path(promotion.stage_path)
        except BaseException:
            promotion.journal_durable = False
            return promotion
        promotion.journal_durable = True
        return promotion
    except CleanupJournalPublicationError:
        promotion.journal_published = True
        promotion.journal_durable = False
        return promotion
    except BaseException:
        rollback_cleanup_promotion(promotion)
        raise


def recover_cleanup_promotion_stage(target: Path) -> bool:
    stage = validate_cleanup_stage(target)
    if stage is None:
        return False
    if lstat_exists(cleanup_journal_path(target)):
        validate_cleanup_journal(target, allow_stage=True)
        unlink_path(cleanup_stage_path(target))
        return True
    root = cleanup_root(target)
    if not lstat_exists(root):
        root.mkdir(mode=OWNER_DIR_MODE)
        fsync_directory(target)
    require_private_directory(root, "cleanup tombstone")
    journal = stage["journal"]
    for entry in stage["entries"]:
        source = safe_target_path(target, entry["source_relative"])
        destination = root / entry["destination_relative"]
        journal_entry = next(item for item in journal["entries"] if item["name"] == entry["name"])
        if lstat_exists(source) and lstat_exists(destination):
            fail("cleanup promotion stage has duplicate source and tombstone payload")
        if not lstat_exists(source) and not lstat_exists(destination):
            fail("cleanup promotion stage source and tombstone payload are both missing")
        if lstat_exists(source):
            validate_cleanup_payload_graph(
                source,
                entry["label"],
                journal_entry["metadata"],
                require_complete=True,
            )
            source.rename(destination)
            fsync_directory(source.parent)
            fsync_directory(root)
        else:
            validate_cleanup_payload_graph(
                destination,
                entry["label"],
                journal_entry["metadata"],
                require_complete=True,
            )
    journal_data = canonical_json(journal)
    publish_cleanup_journal_no_replace(cleanup_journal_path(target), journal_data, target)
    unlink_path(cleanup_stage_path(target))
    return True


def validate_cleanup_object_before_delete(
    payload: Path,
    label: str,
    expected: dict[str, Any],
    present_relatives: set[str],
    expected_index: dict[str, dict[str, Any]],
) -> None:
    relative = str(expected["relative"])
    path = payload if relative == "." else payload / relative
    current, _ = cleanup_object_metadata(path, payload, label)
    compare_cleanup_object(
        current,
        expected,
        strict_directory=expected["kind"] != "directory",
    )
    if expected["kind"] != "directory":
        return
    actual_names = set(child.name for child in path.iterdir())
    expected_names = {
        Path(item).name
        for item in present_relatives
        if item != "." and Path(item).parent.as_posix() == relative
    }
    if actual_names != expected_names:
        fail("cleanup tombstone directory children changed")
    for child in actual_names:
        child_relative = child if relative == "." else f"{relative}/{child}"
        if child_relative not in expected_index:
            fail("cleanup tombstone contains unknown entries")


def delete_cleanup_payload_bottom_up(payload: Path, label: str, metadata: dict[str, Any]) -> None:
    expected_index = cleanup_metadata_index(metadata)
    present = set(validate_cleanup_payload_graph(payload, label, metadata, require_complete=False))
    ordered = sorted(
        present,
        key=lambda item: (len(Path(item).parts), item == "."),
        reverse=True,
    )
    for relative in ordered:
        expected = expected_index[relative]
        path = payload if relative == "." else payload / relative
        if not lstat_exists(path):
            continue
        validate_cleanup_object_before_delete(payload, label, expected, present, expected_index)
        if expected["kind"] == "directory":
            rmdir_path(path)
        else:
            unlink_path(path)
        present.discard(relative)


def drain_cleanup_journal(target: Path, *, pending_on_failure: bool) -> bool:
    try:
        recover_cleanup_promotion_stage(target)
        journal = validate_cleanup_journal(target)
        if journal is None:
            return False
        root = cleanup_root(target)
        for entry in journal["entries"]:
            payload = root / entry["name"]
            if not lstat_exists(payload):
                continue
            delete_cleanup_payload_bottom_up(payload, entry["label"], entry["metadata"])
            if lstat_exists(root):
                fsync_directory(root)
        if lstat_exists(root):
            require_private_directory(root, "cleanup tombstone")
            if sorted(path.name for path in root.iterdir()):
                fail("cleanup tombstone contains unknown entries")
            rmdir_path(root)
        if lstat_exists(cleanup_stage_path(target)):
            unlink_path(cleanup_stage_path(target))
        if lstat_exists(cleanup_journal_path(target)):
            unlink_path(cleanup_journal_path(target))
        if lstat_exists(cleanup_drain_path(target)):
            unlink_path(cleanup_drain_path(target))
        return False
    except BaseException:
        if pending_on_failure:
            return True
        raise


def drain_cleanup_before_mutation(target: Path) -> bool:
    had_pending = lstat_exists(cleanup_stage_path(target)) or cleanup_pending(target)
    drain_cleanup_journal(target, pending_on_failure=False)
    return had_pending


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
    with contextlib.suppress(OSError):
        fsync_directory(path.parent)


def atomic_write(path: Path, content: bytes, *, mode: int = OWNER_FILE_MODE) -> None:
    make_parent_directories(path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        try:
            os.fchmod(fd, mode)
            write_all_fd(fd, content)
            os.fsync(fd)
        finally:
            os.close(fd)
            fd = -1
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def atomic_write_executable(path: Path, content: bytes) -> None:
    atomic_write(path, content, mode=OWNER_EXEC_MODE)


def parse_os_release_content(content: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key] = value
    return result


def linux_os_release() -> dict[str, str]:
    freedesktop = getattr(py_platform, "freedesktop_os_release", None)
    if freedesktop is not None:
        try:
            return dict(freedesktop())
        except OSError:
            pass
    for path in OS_RELEASE_PATHS:
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            fail("Linux OS release metadata must be a regular file")
        if info.st_size > OS_RELEASE_MAX_BYTES:
            fail("Linux OS release metadata exceeds the bounded size limit")
        try:
            return parse_os_release_content(path.read_text(encoding="utf-8"))
        except OSError as exc:
            fail(f"Linux OS release metadata cannot be read: {exc}")
    fail("Ubuntu detection requires /etc/os-release or /usr/lib/os-release")


def current_host_id() -> str:
    system = sys.platform
    machine = os.uname().machine.lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        fail(f"unsupported Antigravity CLI installer architecture: {machine}")
    if system == "darwin":
        host_id = f"macos-{arch}"
    elif system.startswith("linux"):
        libc_name = py_platform.libc_ver()[0].lower()
        if libc_name == "musl":
            fail("linux-musl hosts are not supported by the pinned Antigravity CLI manifests")
        release = linux_os_release()
        identifiers = {
            str(release.get("ID", "")).lower(),
            *str(release.get("ID_LIKE", "")).lower().split(),
        }
        if "ubuntu" not in identifiers:
            fail("non-ubuntu-linux hosts are not supported by this product")
        host_id = f"ubuntu-glibc-{arch}"
    else:
        fail(f"unsupported Antigravity CLI installer platform: {system}")
    if host_id not in SUPPORTED_PUBLIC_HOSTS:
        fail(f"unsupported Antigravity CLI installer host: {host_id}")
    return host_id


def current_platform_key() -> str:
    return OFFICIAL_PLATFORM_BY_HOST[current_host_id()]


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


def software_status_locked(target: Path) -> dict[str, Any]:
    target = canonical_target_identity(target)
    cleanup = cleanup_state(target)
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
            "cleanup_pending": cleanup["pending"],
            "cleanup": cleanup["metadata"],
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
        "cleanup_pending": cleanup["pending"],
        "cleanup": cleanup["metadata"],
    }


def software_status(target: Path) -> dict[str, Any]:
    return read_only_target_payload(target, software_status_locked)


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
    cleanup_drained = drain_cleanup_before_mutation(target)
    require_clean_current(target)
    status = software_status_locked(target)
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
            "cleanup_pending": status["cleanup_pending"],
            "cleanup_drained": cleanup_drained,
            "cleanup": status["cleanup"],
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
    version_relative = str(
        Path(".nddev-software/antigravity-cli/versions") / CLI_VERSION / CLI_COMMAND
    )
    reject_symlink_ancestors(target, version_relative)
    staging = versions / f".stage-{os.getpid()}-{time.time_ns()}"
    rollback_version = versions / f".rollback-{os.getpid()}-{time.time_ns()}"
    changed: list[str] = []
    if before_binary != artifact["binary"]:
        changed.append("bin/agy")
    before_version_binary = read_optional_software_executable(
        version_binary, f"managed software version binary {version_binary}"
    )
    if before_version_binary != artifact["binary"]:
        changed.append(version_relative)
    stamp_bytes = canonical_json(software_stamp(target, artifact))
    if before_stamp != stamp_bytes:
        changed.append(str(Path(".nddev-software/antigravity-cli") / SOFTWARE_STAMP_NAME))
    try:
        staging.mkdir(mode=OWNER_DIR_MODE)
        fsync_directory(staging.parent)
        os.chmod(staging, OWNER_DIR_MODE)
        require_private_directory(staging, "software staging directory")
        atomic_write_executable(staging / CLI_COMMAND, artifact["binary"])
        if before_version_exists:
            version_dir.rename(rollback_version)
            fsync_directory(version_dir.parent)
        staging.rename(version_dir)
        fsync_directory(version_dir.parent)
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
    cleanup_pending_result = False
    promotion = promote_cleanup_items(
        target,
        "software-version-replacement",
        [(rollback_version if lstat_exists(rollback_version) else None, "software rollback directory")],
    )
    if promotion is not None:
        cleanup_pending_result = True
        if promotion.journal_durable:
            cleanup_pending_result = drain_cleanup_journal(target, pending_on_failure=True)
    final_status = software_status_locked(target)
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
        "cleanup_pending": cleanup_pending_result or final_status["cleanup_pending"],
        "cleanup_drained": cleanup_drained,
        "cleanup": final_status["cleanup"],
    }


def install_cli(target: Path, command: str) -> dict[str, Any]:
    with target_lock(target, create=False) as target:
        return install_cli_unlocked(target, command)


def remove_cli(target: Path) -> dict[str, Any]:
    with target_lock(target, create=False, allow_missing=True) as target:
        if not ensure_target_directory(target, create=False):
            return {
                "schema_version": 1,
                "command": "remove-cli",
                "operation": "current",
                "target": str(target),
                "version": None,
                "current": True,
                "changed": [],
                "managed_command": str(managed_cli_path(target)),
                "cleanup_pending": False,
                "cleanup_drained": False,
                "cleanup": cleanup_pending_summary_from_journal(target, None),
            }
        cleanup_drained = drain_cleanup_before_mutation(target)
        status = software_status_locked(target)
        if not status["installed"] and not status["drift"]:
            return {
                "schema_version": 1,
                "command": "remove-cli",
                "operation": "current",
                "target": str(target),
                "version": None,
                "current": True,
                "changed": [],
                "managed_command": str(managed_cli_path(target)),
                "cleanup_pending": status["cleanup_pending"],
                "cleanup_drained": cleanup_drained,
                "cleanup": status["cleanup"],
            }
        items: list[tuple[Path | None, str]] = []
        root = software_root(target)
        command_path = managed_cli_path(target)
        items.append((root if lstat_exists(root) else None, "removed software root"))
        items.append((command_path if lstat_exists(command_path) else None, "removed software command"))
        promotion = promote_cleanup_items(target, "software-removal", items)
        cleanup_pending_result = False
        if promotion is not None:
            cleanup_pending_result = True
            if promotion.journal_durable:
                cleanup_pending_result = drain_cleanup_journal(target, pending_on_failure=True)
        with contextlib.suppress(OSError):
            rmdir_path(command_path.parent)
        final_status = software_status_locked(target)
        return {
            "schema_version": 1,
            "command": "remove-cli",
            "operation": "remove",
            "target": str(target),
            "version": None,
            "current": not cleanup_pending_result and not final_status["drift"],
            "changed": ["software"],
            "managed_command": str(command_path),
            "cleanup_pending": cleanup_pending_result or final_status["cleanup_pending"],
            "cleanup_drained": cleanup_drained,
            "cleanup": final_status["cleanup"],
        }


def remove_empty_managed_parents(target: Path, relative: str) -> None:
    current = (target / safe_relative_path(relative)).parent
    while current != target and current.exists():
        try:
            rmdir_path(current)
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
                unlink_path(path)
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
def target_lock(
    target: Path,
    *,
    create: bool,
    read_only: bool = False,
    allow_missing: bool = False,
) -> Iterator[Path]:
    product_handle: BootstrapGlobalLockHandle | None = None
    lexical_handle: BootstrapLockHandle | None = None
    canonical_handle: BootstrapLockHandle | None = None
    parent_descriptor: int | None = None
    lock_descriptor: int | None = None
    lock_acquired = False
    cold_read_without_product_anchor = False
    canonical: Path | None = None
    try:
        if read_only:
            product_handle = open_external_global_lock(create=False, exclusive=False)
            if product_handle is None:
                cold_read_without_product_anchor = True
                canonical = validate_target_identity_for_lock(target)
            else:
                lexical_handle = acquire_lexical_external_handle(
                    product_handle.product_root,
                    target,
                    create=False,
                    exclusive=False,
                    blocking=True,
                )
                canonical = validate_target_identity_for_lock(target)
                canonical_handle = acquire_external_target_handle(
                    product_handle.product_root,
                    canonical,
                    create=False,
                    exclusive=False,
                    blocking=True,
                )
                if canonical_handle is not None:
                    release_external_handle(product_handle)
                    product_handle = None
        else:
            product_handle = open_external_global_lock(create=True, exclusive=True)
            if product_handle is None:
                fail("bootstrap product anchor could not be created")
            lexical_handle = acquire_lexical_external_handle(
                product_handle.product_root,
                target,
                create=True,
                exclusive=True,
                blocking=False,
            )
            canonical = validate_target_identity_for_lock(target)
            canonical_handle = acquire_external_target_handle(
                product_handle.product_root,
                canonical,
                create=True,
                exclusive=True,
                blocking=False,
            )
            if canonical_handle is None:
                fail("bootstrap target anchor could not be created")
            release_external_handle(product_handle)
            product_handle = None
            if lexical_handle is not None:
                release_external_handle(lexical_handle)
                lexical_handle = None
        canonical = validate_target_identity_for_lock(target)
        if not ensure_private_target(canonical, create=create):
            if allow_missing or read_only:
                yield canonical
                return
            fail("--target is missing")
        if read_only:
            yield canonical
            return
        lock_parent = canonical / TARGET_LOCK_DIR_NAME
        lock_file = lock_parent / TARGET_LOCK_FILE_NAME
        try:
            lock_parent.mkdir(mode=OWNER_DIR_MODE)
            fsync_directory(canonical)
        except FileExistsError:
            pass
        parent_descriptor, parent_info = open_owner_directory_fd(
            lock_parent,
            "target lock parent",
            {OWNER_DIR_MODE, OWNER_READ_EXEC_DIR_MODE},
        )
        lock_file_missing = False
        try:
            lock_file.lstat()
        except FileNotFoundError:
            lock_file_missing = True
        if lock_file_missing and stat.S_IMODE(parent_info.st_mode) == OWNER_READ_EXEC_DIR_MODE:
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
        require_current_owner(lock_info, "target lock file")
        if stat.S_IMODE(lock_info.st_mode) != OWNER_FILE_MODE:
            if lock_file_missing:
                os.fchmod(lock_descriptor, OWNER_FILE_MODE)
                lock_info = os.fstat(lock_descriptor)
            if stat.S_IMODE(lock_info.st_mode) != OWNER_FILE_MODE:
                fail("target lock file must be owned by the current user with mode 0600")
        path_info = lock_file.lstat()
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
        yield canonical
    finally:
        release_error: BaseException | None = None

        def remember(callback: Any) -> None:
            nonlocal release_error
            try:
                callback()
            except BaseException as exc:
                if release_error is None:
                    release_error = exc

        if parent_descriptor is not None and lock_acquired and canonical is not None:
            with contextlib.suppress(FileNotFoundError, OSError, ManagerError):
                set_directory_fd_mode(
                    parent_descriptor,
                    canonical / TARGET_LOCK_DIR_NAME,
                    "target lock parent",
                    OWNER_DIR_MODE,
                )
        if lock_descriptor is not None:
            if lock_acquired:
                with contextlib.suppress(OSError):
                    fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            remember(lambda: os.close(lock_descriptor))
        if parent_descriptor is not None:
            remember(lambda: os.close(parent_descriptor))
        if canonical_handle is not None:
            remember(lambda: release_external_handle(canonical_handle))
        if lexical_handle is not None:
            remember(lambda: release_external_handle(lexical_handle))
        if product_handle is not None:
            remember(lambda: release_external_handle(product_handle))
        if cold_read_without_product_anchor and external_global_anchor_exists():
            release_error = release_error or BootstrapColdReadRace()
        if release_error is not None:
            raise release_error


def read_only_target_payload(target: Path, callback: Any) -> Any:
    for _ in range(4):
        try:
            with target_lock(target, create=False, read_only=True, allow_missing=True) as canonical:
                return callback(canonical)
        except BootstrapColdReadRace:
            continue
    fail("read-only target state changed during bootstrap coordination handoff")


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
        unlink_path(child)
    rmdir_path(path)


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


def current_status_locked(target: Path) -> dict[str, Any]:
    target = canonical_target_identity(target)
    cleanup = cleanup_state(target)
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
            "cleanup_pending": cleanup["pending"],
            "cleanup": cleanup["metadata"],
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
            "cleanup_pending": cleanup["pending"],
            "cleanup": cleanup["metadata"],
        }
    drift = detect_drift(target, stamp)
    legacy = is_legacy_stamp(stamp)
    builder_files = LEGACY_BUILDER_MANAGED_FILES if legacy else BUILDER_MANAGED_FILES
    launch_allowed = False
    if not legacy and not drift:
        software = software_status_locked(target)
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
        "cleanup_pending": cleanup["pending"],
        "cleanup": cleanup["metadata"],
    }


def current_status(target: Path) -> dict[str, Any]:
    return read_only_target_payload(target, current_status_locked)


def plan_setup_locked(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    render_setup(setup_id)
    render_profile(profile_id)
    status = current_status_locked(target)
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
        "cleanup_pending": status["cleanup_pending"],
        "cleanup": status["cleanup"],
    }


def plan_setup(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    return read_only_target_payload(
        target,
        lambda canonical: plan_setup_locked(canonical, setup_id, profile_id),
    )


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
    with target_lock(target, create=action != "switch") as target:
        ensure_target_directory(target, create=True)
        cleanup_drained = drain_cleanup_before_mutation(target)
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
        before = snapshot_managed_files(target)
        desired = desired_for(target, setup, profile)
        stamp_bytes = canonical_json(stamp_payload(target, setup_id, profile_id, desired))
        desired[STAMP_NAME] = stamp_bytes
        changed = []
        for relative in MANAGED_FILES:
            desired_content = desired[relative]
            desired_digest = None if desired_content is None else sha256_bytes(desired_content)
            if before[relative].digest != desired_digest:
                changed.append(relative)
        if before[STAMP_NAME].digest != sha256_bytes(stamp_bytes):
            changed.append(STAMP_NAME)
        if (
            existing_stamp is not None
            and not is_legacy_stamp(existing_stamp)
            and existing_stamp["setup_id"] == setup_id
            and existing_stamp["profile_id"] == profile_id
            and not changed
        ):
            cleanup = cleanup_state(target)
            return {
                "operation": "update",
                "target": str(target),
                "setup_id": setup_id,
                "profile_id": profile_id,
                "changed": [],
                "backup_slot": None,
                "builder": {"projection": "native-plugin", "enabled": True},
                "cleanup_pending": cleanup["pending"],
                "cleanup_drained": cleanup_drained,
                "cleanup": cleanup["metadata"],
            }
        backup_slot: int | None = None
        if existing_stamp is not None and (
            existing_stamp["setup_id"] != setup_id or existing_stamp["profile_id"] != profile_id
        ):
            backup_slot = write_backup(target, existing_stamp)
        try:
            replace_managed_state(target, desired, before)
        except BaseException:
            restore_snapshot(target, before)
            raise
        cleanup = cleanup_state(target)
        return {
            "operation": "install" if existing_stamp is None else action,
            "target": str(target),
            "setup_id": setup_id,
            "profile_id": profile_id,
            "changed": changed,
            "backup_slot": backup_slot,
            "builder": {"projection": "native-plugin", "enabled": True},
            "cleanup_pending": cleanup["pending"],
            "cleanup_drained": cleanup_drained,
            "cleanup": cleanup["metadata"],
        }


def update_setup(target: Path) -> dict[str, Any]:
    with target_lock(target, create=False) as target:
        cleanup_drained = drain_cleanup_before_mutation(target)
        existing_stamp = require_clean_current(target)
        setup_id = existing_stamp["setup_id"]
        profile_id = existing_stamp["profile_id"]
        setup = render_setup(setup_id)
        profile = render_profile(profile_id)
        before = snapshot_managed_files(target)
        desired = desired_for(target, setup, profile)
        stamp_bytes = canonical_json(stamp_payload(target, setup_id, profile_id, desired))
        desired[STAMP_NAME] = stamp_bytes
        changed: list[str] = []
        for relative in MANAGED_FILES:
            content = desired[relative]
            digest = None if content is None else sha256_bytes(content)
            if before[relative].digest != digest:
                changed.append(relative)
        if before[STAMP_NAME].digest != sha256_bytes(stamp_bytes):
            changed.append(STAMP_NAME)
        if changed:
            try:
                replace_managed_state(target, desired, before)
            except BaseException:
                restore_snapshot(target, before)
                raise
        cleanup = cleanup_state(target)
        return {
            "operation": "update",
            "target": str(target),
            "setup_id": setup_id,
            "profile_id": profile_id,
            "changed": changed,
            "backup_slot": None,
            "builder": {"projection": "native-plugin", "enabled": True},
            "cleanup_pending": cleanup["pending"],
            "cleanup_drained": cleanup_drained,
            "cleanup": cleanup["metadata"],
        }


def migrate_setup(target: Path, setup_id: str, profile_id: str) -> dict[str, Any]:
    setup = render_setup(setup_id)
    profile = render_profile(profile_id)
    with target_lock(target, create=False) as target:
        cleanup_drained = drain_cleanup_before_mutation(target)
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
            "cleanup_pending": cleanup_state(target)["pending"],
            "cleanup_drained": cleanup_drained,
            "cleanup": cleanup_state(target)["metadata"],
        }


def restore_backup(target: Path, slot: int) -> dict[str, Any]:
    with target_lock(target, create=False) as target:
        cleanup_drained = drain_cleanup_before_mutation(target)
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
            "cleanup_pending": cleanup_state(target)["pending"],
            "cleanup_drained": cleanup_drained,
            "cleanup": cleanup_state(target)["metadata"],
        }


def remove_setup(target: Path) -> dict[str, Any]:
    with target_lock(target, create=False) as target:
        cleanup_drained = drain_cleanup_before_mutation(target)
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
            "cleanup_pending": cleanup_state(target)["pending"],
            "cleanup_drained": cleanup_drained,
            "cleanup": cleanup_state(target)["metadata"],
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
        for option in MANAGED_LAUNCH_OPTION_NAMES:
            if argument == option or argument.startswith(f"{option}="):
                fail(
                    "launch argument overrides managed Antigravity CLI setup scope: "
                    f"{argument}"
                )


def normalized_launch_child_args(child_args: list[str]) -> list[str]:
    args = list(child_args)
    if args and args[0] == "--":
        return args[1:]
    return args


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
    validate_launch_args(normalized_launch_child_args(child_args))
    require_clean_current(target)
    status = software_status_locked(target)
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
    with target_lock(target, create=False) as target:
        return validate_launch_ready_unlocked(target, child_args)


def launch(target: Path, child_args: list[str]) -> int:
    child_args = normalized_launch_child_args(child_args)
    with target_lock(target, create=False) as target:
        drain_cleanup_before_mutation(target)
        stamp = launch_ready_stamp_unlocked(target, child_args)
        env = build_launch_env(target)
        with protected_launch_handoff(target):
            executable = recheck_launch_executable(target, stamp)
            process = subprocess.Popen([str(executable), *child_args], env=env)
            return process.wait()


def emit(payload: dict[str, Any] | list[Any], *, as_json: bool) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = AntigravityArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=AntigravityArgumentParser,
    )

    list_parser = subparsers.add_parser("list", help="list available setups and profiles")
    list_parser.add_argument("--json", action="store_true")

    for name in ("status", "update", "remove"):
        command = subparsers.add_parser(name)
        command.add_argument("--target")
        command.add_argument("--json", action="store_true")

    software_status_parser = subparsers.add_parser("software-status")
    software_status_parser.add_argument("--target")
    software_status_parser.add_argument("--json", action="store_true")

    for name in ("install-cli", "update-cli", "remove-cli"):
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
        if args.command in {
            "status",
            "software-status",
            "install-cli",
            "update-cli",
            "remove-cli",
            "plan",
            "install",
            "update",
            "apply",
            "switch",
            "migrate",
            "restore",
            "remove",
            "launch",
        }:
            current_host_id()
        if args.command == "status":
            emit(current_status(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command == "software-status":
            emit(software_status(resolve_target(args.target)), as_json=args.json)
            return 0
        if args.command in {"install-cli", "update-cli"}:
            emit(install_cli(resolve_target(args.target), args.command), as_json=args.json)
            return 0
        if args.command == "remove-cli":
            emit(remove_cli(resolve_target(args.target)), as_json=args.json)
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
        if args.command == "update":
            emit(update_setup(resolve_target(args.target)), as_json=args.json)
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
            return launch(resolve_target(args.target), list(args.child_args))
        fail(f"unsupported command: {args.command}")
    except (ManagerError, AntigravityArgumentError) as exc:
        if wants_json(raw_argv):
            print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        else:
            print(f"nddev-antigravity-cli: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
