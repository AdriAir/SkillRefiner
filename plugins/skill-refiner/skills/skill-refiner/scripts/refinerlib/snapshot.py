from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import unicodedata
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .common import RefinerError, digest, reject_links, relative_path

MAX_FILES = 2_000
MAX_BYTES = 100 * 1024 * 1024
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_DEPTH = 20
_BARE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:(?://)?")


@dataclass(frozen=True)
class Snapshot:
    root: Path
    files: dict[str, bytes]
    digest: str
    manifest: list[dict]
    omitted: list[dict]


def _validate_entry(root: Path, path: Path) -> str:
    try:
        name = path.relative_to(root).as_posix()
    except ValueError as error:
        raise RefinerError("Path must stay inside the skill") from error
    value = relative_path(name)
    if len(Path(value).parts) > MAX_DEPTH:
        raise RefinerError("Skill exceeds path depth limit")
    return value


def _identity(path: str) -> str:
    return "/".join(unicodedata.normalize("NFC", part).casefold() for part in path.split("/"))


def _same_stat(left, right) -> bool:
    keys = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
    return all(getattr(left, key, None) == getattr(right, key, None) for key in keys)


def _read_regular(path: Path, expected) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.EMLINK}:
            raise RefinerError("Links and reparse points are not accepted") from error
        raise RefinerError(f"Cannot read skill file: {path.name}") from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or not _same_stat(expected, opened):
            raise RefinerError("Skill entry changed while being inventoried")
        chunks: list[bytes] = []
        remaining = expected.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise RefinerError("Skill entry changed while being inventoried")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RefinerError("Skill entry changed while being inventoried")
        finished = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        current = path.lstat()
    except OSError as error:
        raise RefinerError("Skill entry changed while being inventoried") from error
    if not _same_stat(opened, finished) or not _same_stat(finished, current):
        raise RefinerError("Skill entry changed while being inventoried")
    return b"".join(chunks)


def _text_omission(path: str, contents: bytes) -> dict | None:
    if len(contents) > MAX_TEXT_BYTES:
        return {"path": path, "reason": "file-too-large", "bytes": len(contents)}
    try:
        contents.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": path, "reason": "binary-or-non-utf8", "bytes": len(contents)}
    if b"\x00" in contents:
        return {"path": path, "reason": "binary-or-non-utf8", "bytes": len(contents)}
    return None


def inventory(source) -> Snapshot:
    root = reject_links(Path(source))
    if not root.is_dir():
        raise RefinerError("Skill source must be a directory")
    files: dict[str, bytes] = {}
    manifest: list[dict] = []
    omitted: list[dict] = []
    entries: dict[str, tuple[str, str]] = {}
    entry_count = 0
    total = 0

    def walk_error(error: OSError):
        raise RefinerError("Cannot enumerate the complete skill tree") from error

    for current, dirs, names in os.walk(root, topdown=True, followlinks=False, onerror=walk_error):
        current_path = Path(current)
        dirs.sort()
        names.sort()
        kept: list[str] = []
        for directory in dirs:
            child = current_path / directory
            reject_links(child)
            try:
                info = child.lstat()
            except OSError as error:
                raise RefinerError("Cannot inspect skill directory") from error
            if not stat.S_ISDIR(info.st_mode):
                raise RefinerError("Special filesystem entries are not accepted")
            relative = _validate_entry(root, child)
            key = _identity(relative)
            previous = entries.get(key)
            if previous and previous != (relative, "directory"):
                raise RefinerError("Case or Unicode-colliding paths are not accepted")
            entries[key] = (relative, "directory")
            entry_count += 1
            if entry_count > MAX_FILES:
                raise RefinerError("Skill exceeds entry limit")
            if directory.casefold() == ".git":
                omitted.append({"path": relative, "reason": "git-metadata", "bytes": 0})
            else:
                kept.append(directory)
        dirs[:] = kept
        for name in names:
            path = current_path / name
            reject_links(path)
            relative = _validate_entry(root, path)
            key = _identity(relative)
            previous = entries.get(key)
            if previous and previous != (relative, "file"):
                raise RefinerError("Case or Unicode-colliding paths are not accepted")
            entries[key] = (relative, "file")
            entry_count += 1
            if entry_count > MAX_FILES:
                raise RefinerError("Skill exceeds entry limit")
            try:
                info = path.lstat()
            except OSError as error:
                raise RefinerError("Cannot inspect skill file") from error
            if not stat.S_ISREG(info.st_mode):
                raise RefinerError("Special filesystem entries are not accepted")
            if name.casefold() == ".git":
                omitted.append({"path": relative, "reason": "git-metadata", "bytes": 0})
                continue
            total += info.st_size
            if total > MAX_BYTES:
                raise RefinerError("Skill exceeds size limit")
            contents = _read_regular(path, info)
            files[relative] = contents
            manifest.append({"path": relative, "sha256": hashlib.sha256(contents).hexdigest(), "bytes": len(contents)})
            reason = _text_omission(relative, contents)
            if reason:
                omitted.append(reason)
    manifest.sort(key=lambda item: item["path"])
    omitted.sort(key=lambda item: item["path"])
    return Snapshot(root=root, files=files, digest=digest({"manifest": manifest, "omitted": omitted}), manifest=manifest, omitted=omitted)


def prepared_inventory(source) -> Snapshot:
    """Analyze an independent temporary byte copy, then remove it immediately."""
    original = inventory(source)
    with tempfile.TemporaryDirectory(prefix="refiner-review-") as temporary:
        stage = Path(temporary)
        for name, content in original.files.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        # Excluded Git entries have no original content in the copy.
        for item in original.omitted:
            if item["reason"] == "git-metadata":
                (stage / item["path"]).mkdir(parents=True, exist_ok=True)
        copied = inventory(stage)
        if copied.digest != original.digest or inventory(source).digest != original.digest:
            raise RefinerError("Input changed while preparing the review copy")
        return Snapshot(root=original.root, files=copied.files, digest=original.digest, manifest=original.manifest, omitted=original.omitted)


def textual_files(snapshot: Snapshot) -> dict[str, str]:
    omitted = {item["path"] for item in snapshot.omitted}
    return {path: raw.decode("utf-8") for path, raw in snapshot.files.items() if path not in omitted}


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if path.exists():
            path = reject_links(path)
            identity = os.path.normcase(str(path.resolve(strict=True)))
        else:
            identity = os.path.normcase(str(Path(os.path.abspath(path))))
        if identity not in seen:
            result.append(path)
            seen.add(identity)
    return result


def _default_roots() -> list[Path]:
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", home / ".codex"))
    roots = [home / ".agents" / "skills", codex_home / "skills", home / ".codex" / "skills"]
    cache = home / ".codex" / "plugins" / "cache"
    if cache.is_dir():
        cache = reject_links(cache)
        for vendor in sorted(cache.iterdir()):
            if not vendor.is_dir():
                continue
            vendor = reject_links(vendor)
            for plugin in sorted(vendor.iterdir()):
                if not plugin.is_dir():
                    continue
                plugin = reject_links(plugin)
                for version in sorted(plugin.iterdir()):
                    if not version.is_dir():
                        continue
                    version = reject_links(version)
                    skills = version / "skills"
                    if skills.is_dir():
                        roots.append(reject_links(skills))
    return _deduplicate_paths(roots)


def _is_explicit_local(value: str) -> bool:
    candidate = Path(value)
    return candidate.is_absolute() or value.startswith(("./", ".\\")) or "/" in value or "\\" in value


def resolve_targets(values: list[str], roots: list[Path] | None = None) -> list[Path]:
    known_roots = _deduplicate_paths(list(roots) if roots is not None else _default_roots())
    resolved: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise RefinerError("Skill target must be an explicit local path or bare name")
        if _URL.match(value) and not re.match(r"^[A-Za-z]:[\\/]", value):
            raise RefinerError("Skill target must be an explicit local path or bare name")
        if _is_explicit_local(value):
            if any(part == ".." for part in Path(value).parts):
                raise RefinerError("Skill target traversal is not accepted")
            direct = Path(value)
            if not direct.exists():
                raise RefinerError(f"Unknown skill target: {value}")
            resolved.append(reject_links(direct))
            continue
        if not _BARE_NAME.fullmatch(value) or value in {".", ".."}:
            raise RefinerError("Bare skill target must be one filename without traversal")
        matches: list[Path] = []
        seen_matches: set[str] = set()
        for root in known_roots:
            if not root.exists():
                continue
            root = reject_links(root)
            candidate = root / value
            if candidate.is_dir():
                candidate = reject_links(candidate)
                identity = os.path.normcase(str(candidate.resolve(strict=True)))
                if identity not in seen_matches:
                    matches.append(candidate)
                    seen_matches.add(identity)
        if not matches:
            raise RefinerError(f"Unknown skill target: {value}")
        if len(matches) != 1:
            raise RefinerError(f"Ambiguous skill target: {value}")
        resolved.append(matches[0])
    return resolved
