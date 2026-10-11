import hashlib
import json
import os
import re
import stat
import unicodedata
from pathlib import Path, PurePosixPath


class RefinerError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 1024 or unicodedata.normalize("NFC", value) != value or "\\" in value or ":" in value or any(unicodedata.category(c) in ("Cc", "Cf") or c in '<>"|?*' for c in value):
        raise RefinerError("Invalid relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise RefinerError("Path must stay inside the skill")
    for part in path.parts:
        if part.endswith((".", " ")) or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", part, re.I):
            raise RefinerError("Ambiguous filesystem name")
    return path.as_posix()


def reject_links(path):
    path = Path(os.path.abspath(path))
    for node in reversed([path, *path.parents]):
        if node.exists() or node.is_symlink():
            info = node.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise RefinerError("Links and reparse points are not accepted")
    return path


def private_directory(path):
    path = reject_links(path)
    created = not path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    reject_links(path)
    if created and os.name != "nt":
        path.chmod(0o700)
    return path


def ensure_outside(path, source):
    path, source = reject_links(path), reject_links(source)
    if path == source or source in path.parents or path in source.parents:
        raise RefinerError("Output/history must be outside the input skill")
    # Filesystem identity catches aliases such as Windows short paths and SUBST drives.
    for candidate, original in ((path, source), (source, path)):
        if original.exists():
            for ancestor in [candidate, *candidate.parents]:
                if ancestor.exists() and os.path.samefile(ancestor, original):
                    raise RefinerError("Output/history aliases the input skill")
    return path


def read_json(path):
    path = reject_links(path)
    if path.stat().st_size > 100 * 1024 * 1024:
        raise RefinerError("JSON record exceeds size limit")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    import tempfile
    path = reject_links(path)
    private_directory(path.parent)
    # A random exclusive file prevents another process from planting a link.
    fd, temp_name = tempfile.mkstemp(prefix=".refiner-", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(value) + b"\n")
        reject_links(path)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


_SECRET = re.compile(
    r"(?i)(?:\b(?:api[_-]?key|(?:access|refresh|id)[_-]?token|client[_-]?secret|(?:aws[_-]?)?secret[_-]?access[_-]?key|private[_-]?key|token|password|passwd|pwd|secret|authorization)[\"']?\s*[:=]\s*[\"']?(?:(?:Bearer|Basic)\s+)?)"
    r"([^\s\"'`,;}]{8,})"
    r"|\b(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{82}|glpat-[A-Za-z0-9_-]{20,}|xoxb-[0-9]{1,16}-[A-Za-z0-9-]{20,}|sk_live_[A-Za-z0-9]{16,}|(?:AKIA|ASIA)[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b"
    r"|(?:[a-z][a-z0-9+.-]*://[^\s/:@]+:)([^\s/@]{1,})(?=@)"
    r"|-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----"
)
_PEM = re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----")


def _matched_secret(match):
    return next((group for group in match.groups() if group is not None), match.group(0))


def secret_values(text):
    # An earlier assignment match must not consume the beginning of a PEM block.
    return [_matched_secret(match) for match in _SECRET.finditer(text)] + _PEM.findall(text)


def redact(text, secrets=()):
    text = str(text)
    text = _PEM.sub("[REDACTED PRIVATE KEY]", text)
    # Replace known values first, including values leaked without their label.
    for value in sorted(set(secrets), key=len, reverse=True):
        if value:
            text = text.replace(value, "[REDACTED]")
    return _SECRET.sub(lambda match: match.group(0).replace(_matched_secret(match), "[REDACTED]"), text)


def redact_tree(value, secrets=()):
    if isinstance(value, dict):
        return {redact(k, secrets): redact_tree(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_tree(v, secrets) for v in value]
    return redact(value, secrets) if isinstance(value, str) else value
