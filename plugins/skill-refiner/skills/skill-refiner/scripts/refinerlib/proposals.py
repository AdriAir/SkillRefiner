"""Private, digest-bound proposals for copying a reviewed skill safely."""

from __future__ import annotations

import datetime as _datetime
import difflib
import os
import shutil
import tempfile
import unicodedata
import ctypes
import errno
from pathlib import Path

from .common import (
    RefinerError,
    digest,
    ensure_outside,
    private_directory,
    redact_tree,
    relative_path,
    reject_links,
    secret_values,
)
from .snapshot import inventory


def _hash(contents: bytes | None) -> str | None:
    return None if contents is None else digest(contents)


def _proposal_body(proposal: dict) -> dict:
    return {key: value for key, value in proposal.items() if key not in {"id", "proposal_digest"}}


def _proposal_digest(proposal: dict) -> str:
    return digest(_proposal_body(proposal))


def _validate_proposal(proposal: dict) -> None:
    if not isinstance(proposal, dict) or proposal.get("schema_version") != "1":
        raise RefinerError("Invalid proposal")
    actual = _proposal_digest(proposal)
    if proposal.get("proposal_digest") != actual or proposal.get("id") != actual[:16]:
        raise RefinerError("proposal digest does not match its contents")


def _normalise_changes(snapshot, changes: list[dict]) -> list[dict]:
    if not isinstance(changes, list) or not changes or len(changes) > 256:
        raise RefinerError("Proposal needs at least one change")
    normalised: list[dict] = []
    seen: set[str] = set()
    existing = {unicodedata.normalize("NFC", name).casefold(): name for name in snapshot.files}
    for item in changes:
        if not isinstance(item, dict):
            raise RefinerError("Invalid change")
        path = relative_path(item.get("path"))
        folded = unicodedata.normalize("NFC", path).casefold()
        if ".git" in folded.split("/"):
            raise RefinerError("Git metadata cannot be copied or proposed")
        if folded in seen or folded in existing and existing[folded] != path:
            raise RefinerError("A path may only be changed once")
        seen.add(folded)
        before = snapshot.files.get(path)
        if set(item) == {"path", "old", "new"}:
            if before is None or not isinstance(item["old"], str) or not item["old"] or not isinstance(item["new"], str):
                raise RefinerError("A replacement requires existing text and a nonempty old fragment")
            try:
                original = before.decode("utf-8")
            except UnicodeError as error:
                raise RefinerError("Only UTF-8 text can be edited") from error
            if original.count(item["old"]) != 1:
                raise RefinerError("Replacement fragment must match exactly once")
            content = original.replace(item["old"], item["new"], 1)
        elif set(item) == {"path", "content"}:
            content = item["content"]
            if isinstance(content, str) and "[REDACTED]" in content and before and secret_values(before.decode("utf-8", errors="replace")):
                raise RefinerError("Do not replace private original values with display masks; use an exact fragment replacement")
        else:
            raise RefinerError("Change must specify content or an old/new exact replacement")
        if content is not None and not isinstance(content, str):
            raise RefinerError("Replacement content must be UTF-8 text or null")
        if before is None and content is None:
            raise RefinerError("Cannot delete a file that does not exist")
        if before is not None:
            try:
                before.decode("utf-8")
            except UnicodeError as error:
                raise RefinerError("Only UTF-8 text can be edited") from error
        after = None if content is None else content.encode("utf-8")
        if before == after:
            raise RefinerError("Proposal contains no change")
        normalised.append({
            "path": path,
            "base_hash": _hash(before),
            "new_hash": _hash(after),
            "content": content,
        })
    post = dict(snapshot.files)
    for change in normalised:
        if change["content"] is None:
            post.pop(change["path"], None)
        else:
            post[change["path"]] = change["content"].encode("utf-8")
    if len(post) > 2000 or sum(map(len, post.values())) > 100 * 1024 * 1024:
        raise RefinerError("Proposed copy exceeds snapshot limits")
    all_paths = set()
    directories = {}
    for name in post:
        folded = unicodedata.normalize("NFC", name).casefold()
        if folded in all_paths:
            raise RefinerError("Case-colliding postimage")
        all_paths.add(folded)
        parts = name.split("/")
        for index in range(1, len(parts)):
            directory = "/".join(parts[:index])
            identity = directory.casefold()
            if identity in directories and directories[identity] != directory:
                raise RefinerError("Case-colliding postimage directories")
            directories[identity] = directory
    for name in all_paths:
        parts = name.split("/")
        if len(parts) > 20 or any("/".join(parts[:i]) in all_paths for i in range(1, len(parts))):
            raise RefinerError("Invalid postimage file tree")
    if "SKILL.md" not in post:
        raise RefinerError("Proposed copy must contain SKILL.md")
    return sorted(normalised, key=lambda item: item["path"])


def _exact_diff(snapshot, changes: list[dict]) -> str:
    pieces: list[str] = []
    for change in changes:
        path = change["path"]
        before = snapshot.files.get(path, b"").decode("utf-8").splitlines(keepends=True)
        after = (change["content"] or "").splitlines(keepends=True)
        for line in difflib.unified_diff(before, after, fromfile=f"a/{path}", tofile=f"b/{path}"):
            pieces.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(pieces)


def propose(source, changes: list[dict], purpose: str, risk: str = "Requires explicit approval", verification: list[str] | None = None) -> dict:
    """Build a private, exact proposal. Do not persist this artifact."""
    if not isinstance(purpose, str) or not purpose.strip() or not isinstance(risk, str) or len(purpose) > 8192 or len(risk) > 8192:
        raise RefinerError("Purpose and risk must be text")
    if verification is None:
        verification = []
    if not isinstance(verification, list) or len(verification) > 64 or not all(isinstance(item, str) and len(item) <= 4096 for item in verification):
        raise RefinerError("Verification must be a list of text checks")
    snapshot = inventory(source)
    normalised = _normalise_changes(snapshot, changes)
    proposal = {
        "schema_version": "1",
        "base_digest": snapshot.digest,
        "changes": normalised,
        "diff": _exact_diff(snapshot, normalised),
        "purpose": purpose,
        "risk": risk,
        "verification": verification,
    }
    proposal_digest = _proposal_digest(proposal)
    proposal["id"] = proposal_digest[:16]
    proposal["proposal_digest"] = proposal_digest
    return proposal


def approve(proposal: dict, base_digest: str, proposal_digest: str, decision: str, reason: str = "") -> dict:
    """Record an explicit decision bound to the exact private proposal."""
    _validate_proposal(proposal)
    if base_digest != proposal["base_digest"] or proposal_digest != proposal["proposal_digest"]:
        raise RefinerError("Approval digests do not match proposal")
    if decision not in {"apply", "reject"} or not isinstance(reason, str) or len(reason) > 4096:
        raise RefinerError("Decision must be apply or reject")
    approval = {
        "schema_version": "1",
        "proposal_id": proposal["id"],
        "base_digest": base_digest,
        "proposal_digest": proposal_digest,
        "decision": decision,
        "reason": redact_tree(reason, _proposal_secrets(proposal) + secret_values(reason)),
        "timestamp": _datetime.datetime.now(_datetime.UTC).isoformat(),
    }
    approval["approval_digest"] = digest(approval)
    return approval


def _validate_approval(proposal: dict, approval: dict) -> None:
    if not isinstance(approval, dict) or approval.get("approval_digest") != digest({key: value for key, value in approval.items() if key != "approval_digest"}):
        raise RefinerError("Invalid approval")
    if approval.get("decision") != "apply":
        raise RefinerError("Approval decision is not apply")
    for key, expected in (("proposal_id", proposal["id"]), ("base_digest", proposal["base_digest"]), ("proposal_digest", proposal["proposal_digest"])):
        if approval.get(key) != expected:
            raise RefinerError("Approval does not match proposal")


def _write_postimage(stage: Path, snapshot, changes: list[dict]) -> None:
    content = dict(snapshot.files)
    for change in changes:
        original = content.get(change["path"])
        if _hash(original) != change["base_hash"]:
            raise RefinerError("Proposal preimage does not match source")
        if change["content"] is None:
            content.pop(change["path"], None)
        else:
            replacement = change["content"].encode("utf-8")
            if _hash(replacement) != change["new_hash"]:
                raise RefinerError("Proposal postimage does not match replacement")
            content[change["path"]] = replacement
    for path, data in content.items():
        target = stage / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _checks(output: Path) -> list[str]:
    skill = output / "SKILL.md"
    if not skill.is_file() or skill.is_symlink():
        raise RefinerError("Proposed copy is missing a regular SKILL.md")
    return ["regular SKILL.md present", "all proposed paths remained inside output"]


def _proposal_secrets(proposal: dict) -> list[str]:
    text = [proposal.get("diff", ""), proposal.get("purpose", ""), proposal.get("risk", "")]
    for item in proposal.get("changes", []):
        text.append(item.get("path", ""))
        if item.get("content") is not None:
            text.append(str(item["content"]))
    return [secret for value in text for secret in secret_values(value)]


def public_proposal(proposal: dict, snapshot=None) -> dict:
    """Return a display-safe view; private exact transformations remain transient."""
    _validate_proposal(proposal)
    secrets = _proposal_secrets(proposal)
    if snapshot is not None:
        secrets.extend(secret for data in snapshot.files.values() for secret in secret_values(data.decode("utf-8", errors="ignore")))
    return redact_tree(proposal, secrets)


def apply(source, proposal: dict, approval: dict, output) -> dict:
    """Create a fresh corrected copy after validating proposal, approval and source."""
    _validate_proposal(proposal)
    _validate_approval(proposal, approval)
    source = reject_links(source)
    output = ensure_outside(output, source)
    before = inventory(source)
    if before.digest != proposal["base_digest"]:
        raise RefinerError("Proposal is outdated for the current source")
    # Validate the whole postimage before writing any bytes, including hand-crafted artifacts.
    checked = _normalise_changes(before, [{"path": c["path"], "content": c["content"]} for c in proposal["changes"]])
    if checked != proposal["changes"]:
        raise RefinerError("Proposal hashes do not match its postimage")
    if output.exists():
        if any(p.name.casefold() == ".git" for p in output.rglob("*")):
            raise RefinerError("Output contains excluded metadata and is not the exact postimage")
        existing = inventory(output)
        expected = _expected_digest(before, proposal["changes"], output.parent)
        if existing.digest == expected:
            return {"status": "noop", "output": str(output), "source_digest": before.digest, "output_digest": existing.digest, "checks": _checks(output)}
        raise RefinerError("Output conflict: existing folder is not this proposal postimage")

    private_directory(output.parent)
    stage = Path(tempfile.mkdtemp(prefix=".refiner-stage-", dir=output.parent))
    try:
        _write_postimage(stage, before, proposal["changes"])
        after = inventory(stage)
        checks = _checks(stage)
        if inventory(source).digest != before.digest:
            raise RefinerError("Source changed while applying proposal")
        _publish_no_replace(stage, output)
        return {"status": "applied", "output": str(output), "source_digest": before.digest, "output_digest": after.digest, "checks": checks}
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _publish_no_replace(stage, output):
    if os.name == "nt":
        # On Windows rename never replaces an existing destination.
        try:
            os.rename(stage, output)
        except FileExistsError as error:
            raise RefinerError("Output appeared while publishing; no overwrite performed") from error
        return
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise RefinerError("Atomic no-replace publication is not supported on this host")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(output), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise RefinerError("Output appeared while publishing; no overwrite performed")
        raise RefinerError("Atomic no-replace publication failed")


def _expected_digest(snapshot, changes: list[dict], parent: Path) -> str:
    stage = Path(tempfile.mkdtemp(prefix=".refiner-expected-", dir=parent))
    try:
        _write_postimage(stage, snapshot, changes)
        return inventory(stage).digest
    finally:
        shutil.rmtree(stage, ignore_errors=True)
