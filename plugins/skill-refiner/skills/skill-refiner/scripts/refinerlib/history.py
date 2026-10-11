from __future__ import annotations

import importlib.metadata
import os
import re
import secrets
import sys
from pathlib import Path

from .analysis import _secrets, analyze, merge_semantic
from .common import (
    RefinerError,
    canonical,
    digest,
    ensure_outside,
    private_directory,
    read_json,
    redact_tree,
    reject_links,
    secret_values,
    write_json,
)
from .snapshot import prepared_inventory as inventory

SCHEMA_VERSION = "1"
_STATE_MARKER = ".refiner-state.json"
_STATE_FORMAT = "skill-refiner-state"
_REPORT_NAME = re.compile(r"^([0-9a-f]{64})-([1-9][0-9]*)\.json$")
_PROFILE = {
    "language": {"es", "en"},
    "tone": {"professional", "friendly", "direct"},
    "detail": {"concise", "medium", "detailed"},
}
_INDEX_FIELDS = {"schema_version", "reviews", "history", "dismissals", "decisions"}
_DISMISSAL_FIELDS = {"finding_id", "rule", "evidence_digest", "policy_digest", "reason"}
_DECISION_INPUT = {"proposal_id", "base_digest", "proposal_digest", "decision", "reason", "timestamp", "output_digest"}
_DECISION_FIELDS = _DECISION_INPUT | {"provenance"}
_DECISION_REQUIRED = _DECISION_FIELDS - {"output_digest"}
_STATIC_SCOPE_LIMITATION = "Static checks cover Python syntax plus bounded metadata, link, and pattern rules; other language syntax and runtime behavior were not executed."
_EXECUTION_LIMITATION = "Dynamic tests, when run, are separate execution records and are not implied by this report."


def default_state_dir():
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "SkillRefiner"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "skill-refiner"


def validate_profile(profile):
    value = profile or {}
    if not isinstance(value, dict) or set(value) - {*_PROFILE, "conventions"}:
        raise RefinerError("Unsupported profile field")
    result = {"language": "es", "tone": "professional", "detail": "medium", "conventions": []}
    result.update(value)
    if any(result[key] not in choices for key, choices in _PROFILE.items()):
        raise RefinerError("Invalid profile")
    conventions = result["conventions"]
    if not isinstance(conventions, list) or len(conventions) > 128 or not all(isinstance(item, str) and len(item) <= 4096 for item in conventions):
        raise RefinerError("Invalid profile")
    return result


def _file_digest(path: Path) -> str:
    return digest(path.read_bytes())


def _tree_digest(root: Path, suffixes: set[str]) -> str:
    if not root.exists():
        return digest({})
    values = {
        item.relative_to(root).as_posix(): _file_digest(item)
        for item in sorted(root.rglob("*"))
        if item.is_file() and item.suffix in suffixes and "__pycache__" not in item.parts
    }
    return digest(values)


def _fingerprints() -> dict:
    skill = Path(__file__).resolve().parents[2]
    scripts = skill / "scripts"
    versions = {}
    for package in ("PyYAML", "jsonschema"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "missing"
    skill_files = [skill / "SKILL.md", skill / "agents" / "openai.yaml", skill / "assets" / "profile.default.json"]
    skill_values = {item.relative_to(skill).as_posix(): _file_digest(item) for item in skill_files if item.is_file()}
    requirements = scripts / "requirements.txt"
    return {
        "code": _tree_digest(scripts, {".py"}),
        "skill": digest(skill_values),
        "schemas": _tree_digest(skill / "schemas", {".json"}),
        "policy": _tree_digest(skill / "references", {".md"}),
        "runtime": digest({"implementation": sys.implementation.name, "python": sys.version.split()[0]}),
        "dependencies": digest({"versions": versions, "requirements": _file_digest(requirements) if requirements.is_file() else None}),
    }


def _policy_digest(fingerprints: dict | None = None):
    return digest(fingerprints or _fingerprints())


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


def _ensure_disjoint(state: Path, source: Path) -> tuple[Path, Path]:
    state = ensure_outside(_absolute(state), _absolute(source))
    source = reject_links(_absolute(source))
    return state, source


def _marker_body(owner_id: str) -> dict:
    return {
        "format": _STATE_FORMAT,
        "version": SCHEMA_VERSION,
        "owner_id": owner_id,
        "integrity": "format-digest-not-cryptographic-authentication",
    }


def _create_marker(state: Path) -> None:
    body = _marker_body(secrets.token_hex(16))
    write_json(state / _STATE_MARKER, {**body, "marker_digest": digest(body)})


def _validate_marker(state: Path) -> dict:
    marker_path = state / _STATE_MARKER
    if not marker_path.is_file():
        raise RefinerError("State directory is not owned by Skill Refiner")
    marker_path = reject_links(marker_path)
    marker = read_json(marker_path)
    if not isinstance(marker, dict) or set(marker) != {"format", "version", "owner_id", "integrity", "marker_digest"}:
        raise RefinerError("Invalid state ownership marker")
    body = {key: marker[key] for key in marker if key != "marker_digest"}
    if (
        marker.get("format") != _STATE_FORMAT
        or marker.get("version") != SCHEMA_VERSION
        or marker.get("integrity") != "format-digest-not-cryptographic-authentication"
        or not isinstance(marker.get("owner_id"), str)
        or not re.fullmatch(r"[0-9a-f]{32}", marker["owner_id"])
        or marker.get("marker_digest") != digest(body)
    ):
        raise RefinerError("Invalid state ownership marker")
    return marker


def _new_index() -> dict:
    return {"schema_version": SCHEMA_VERSION, "reviews": {}, "history": [], "dismissals": [], "decisions": []}


def _report_name(value, key: str | None = None) -> str:
    if not isinstance(value, str):
        raise RefinerError("Invalid state report name")
    match = _REPORT_NAME.fullmatch(value)
    if not match or key is not None and match.group(1) != key:
        raise RefinerError("Invalid state report name")
    return value


def _validate_index(data) -> dict:
    if not isinstance(data, dict) or set(data) - _INDEX_FIELDS or data.get("schema_version") != SCHEMA_VERSION:
        raise RefinerError("Invalid state index")
    if not isinstance(data.get("reviews"), dict) or not isinstance(data.get("history"), list):
        raise RefinerError("Invalid state index")
    if not isinstance(data.get("dismissals"), list) or not isinstance(data.get("decisions"), list):
        raise RefinerError("Invalid state index")
    if len(data["history"]) > 10_000 or len(data["dismissals"]) > 10_000 or len(data["decisions"]) > 10_000:
        raise RefinerError("State index exceeds record limits")
    tracked: list[str] = []
    for key, values in data["reviews"].items():
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key) or not isinstance(values, list) or not values:
            raise RefinerError("Invalid state review index")
        for name in values:
            tracked.append(_report_name(name, key))
    history = [_report_name(name) for name in data["history"]]
    if len(set(tracked)) != len(tracked) or history != tracked and (len(history) != len(tracked) or set(history) != set(tracked)):
        raise RefinerError("State report history does not match owned records")
    for record in data["dismissals"]:
        if not isinstance(record, dict) or set(record) != _DISMISSAL_FIELDS or not all(isinstance(record.get(field), str) for field in _DISMISSAL_FIELDS):
            raise RefinerError("Invalid state dismissal")
        if not re.fullmatch(r"[0-9a-f]{64}", record["finding_id"]) or not re.fullmatch(r"[0-9a-f]{64}", record["evidence_digest"]) or not re.fullmatch(r"[0-9a-f]{64}", record["policy_digest"]) or len(record["reason"]) > 4096:
            raise RefinerError("Invalid state dismissal")
    for record in data["decisions"]:
        if not isinstance(record, dict) or not _DECISION_REQUIRED <= set(record) <= _DECISION_FIELDS:
            raise RefinerError("Invalid state decision")
        if not all(isinstance(value, str) for value in record.values()) or record["decision"] not in {"apply", "reject"}:
            raise RefinerError("Invalid state decision")
        if not re.fullmatch(r"[0-9a-f]{64}", record["base_digest"]) or not re.fullmatch(r"[0-9a-f]{64}", record["proposal_digest"]):
            raise RefinerError("Invalid state decision")
        if "output_digest" in record and not re.fullmatch(r"[0-9a-f]{64}", record["output_digest"]):
            raise RefinerError("Invalid state decision")
    return data


def _index(path: Path, must_exist=False) -> dict:
    if not path.exists():
        if must_exist:
            raise RefinerError("Owned state index does not exist")
        return _new_index()
    return _validate_index(read_json(reject_links(path)))


def _validate_children(state: Path, index: dict | None = None) -> None:
    allowed = {_STATE_MARKER, "index.json", "reports"}
    for child in state.iterdir():
        reject_links(child)
        if child.name not in allowed:
            raise RefinerError("State directory contains foreign records")
        if child.name == "reports" and not child.is_dir():
            raise RefinerError("Invalid state reports directory")
        if child.name != "reports" and not child.is_file():
            raise RefinerError("Invalid state record")
    if index is None:
        return
    tracked = set(index["history"])
    reports = state / "reports"
    if tracked and not reports.is_dir():
        raise RefinerError("Owned state reports are missing")
    if reports.exists():
        for child in reports.iterdir():
            reject_links(child)
            if not child.is_file() or child.name not in tracked:
                raise RefinerError("State reports contain an unowned record")
        if {child.name for child in reports.iterdir()} != tracked:
            raise RefinerError("Owned state report is missing")


def _open_state(state_dir, *, create: bool, source=None) -> tuple[Path, Path, Path, dict]:
    state = _absolute(Path(state_dir))
    if source is not None:
        state, _ = _ensure_disjoint(state, Path(source))
    elif state.exists():
        state = reject_links(state)
    if not state.exists():
        if not create:
            raise RefinerError("State directory is not owned by Skill Refiner")
        private_directory(state)
        _create_marker(state)
    elif not state.is_dir():
        raise RefinerError("State path must be a directory")
    else:
        state = reject_links(state)
        children = list(state.iterdir())
        if not (state / _STATE_MARKER).exists():
            if create and not children:
                _create_marker(state)
            else:
                raise RefinerError("State directory is not owned by Skill Refiner")
    _validate_marker(state)
    index_path = state / "index.json"
    index = _index(index_path)
    _validate_children(state, index)
    return state, state / "reports", index_path, index


def _sid(snapshot):
    return digest(os.path.normcase(str(snapshot.root.resolve(strict=True))))


def _key(snapshot, source_id, profile_digest, context_digest, fingerprints):
    return digest({
        "schema": SCHEMA_VERSION,
        "source": snapshot.digest,
        "source_id": source_id,
        "manifest": snapshot.manifest,
        "profile": profile_digest,
        "context": context_digest,
        "fingerprints": fingerprints,
    })


def _load_report(reports: Path, name: str, expected_key: str | None = None) -> dict:
    name = _report_name(name, expected_key)
    item = read_json(reject_links(reports / name))
    if not isinstance(item, dict) or item.get("review_key") != name.split("-", 1)[0]:
        raise RefinerError("Invalid stored review report")
    _validate_report(item)
    return item


def _validate_report(item: dict) -> None:
    fields = {
        "schema_version", "review_key", "source_id", "source_digest", "policy_digest", "fingerprints",
        "context_digest", "profile_digest", "manifest", "findings", "omitted", "status", "semantic_status",
        "checks", "comparison", "limitations",
    }
    if set(item) != fields or item.get("schema_version") != SCHEMA_VERSION:
        raise RefinerError("Invalid stored review report shape")
    for field in ("review_key", "source_id", "source_digest", "policy_digest", "context_digest", "profile_digest"):
        if not isinstance(item.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", item[field]):
            raise RefinerError("Invalid stored review identity")
    fingerprints = item.get("fingerprints")
    expected_fingerprints = {"code", "skill", "schemas", "policy", "runtime", "dependencies"}
    if not isinstance(fingerprints, dict) or set(fingerprints) != expected_fingerprints or not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in fingerprints.values()):
        raise RefinerError("Invalid stored review fingerprints")
    if item.get("status") != "fresh" or item.get("semantic_status") not in {"pending", "completed"}:
        raise RefinerError("Invalid stored review status")
    checks = item.get("checks")
    if not isinstance(checks, dict) or set(checks) != {"static", "semantic"} or checks.get("static") != "completed" or checks.get("semantic") != item["semantic_status"]:
        raise RefinerError("Invalid stored review checks")
    comparison = item.get("comparison")
    if not isinstance(comparison, dict) or set(comparison) != {"prior_review_key", "prior_source_id", "added", "removed"}:
        raise RefinerError("Invalid stored review comparison")
    if not isinstance(comparison["added"], list) or not isinstance(comparison["removed"], list):
        raise RefinerError("Invalid stored review comparison")
    if any(not isinstance(value, str) for value in comparison["added"] + comparison["removed"]):
        raise RefinerError("Invalid stored review comparison")
    if any(value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)) for value in (comparison["prior_review_key"], comparison["prior_source_id"])):
        raise RefinerError("Invalid stored review comparison")
    if not isinstance(item.get("limitations"), list) or not all(isinstance(value, str) for value in item["limitations"]):
        raise RefinerError("Invalid stored review limitations")
    if not isinstance(item.get("manifest"), list) or not isinstance(item.get("omitted"), list):
        raise RefinerError("Invalid stored review inventory")
    for entry in item["manifest"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"} or not isinstance(entry.get("path"), str) or not isinstance(entry.get("bytes"), int) or not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise RefinerError("Invalid stored review manifest")
    for entry in item["omitted"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "reason", "bytes"} or entry.get("reason") not in {"file-too-large", "binary-or-non-utf8", "git-metadata"} or not isinstance(entry.get("path"), str) or not isinstance(entry.get("bytes"), int):
            raise RefinerError("Invalid stored review omissions")
    findings = item.get("findings")
    if not isinstance(findings, list) or len(findings) > 2_128:
        raise RefinerError("Invalid stored review findings")
    finding_fields = {"id", "rule", "path", "path_digest", "evidence", "evidence_digest", "line", "category", "severity", "message", "verification", "provenance", "dismissed"}
    required = {"id", "rule", "path", "evidence", "evidence_digest", "line", "category", "severity", "message", "verification", "provenance"}
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) - finding_fields or not required <= set(finding):
            raise RefinerError("Invalid stored finding shape")
        if not all(isinstance(finding.get(field), str) for field in required - {"line"}) or not isinstance(finding.get("line"), int) or finding["line"] < 1:
            raise RefinerError("Invalid stored finding fields")
        if not re.fullmatch(r"[0-9a-f]{64}", finding["id"]) or not re.fullmatch(r"[0-9a-f]{64}", finding["evidence_digest"]):
            raise RefinerError("Invalid stored finding identity")
        if len(finding["rule"]) > 128 or len(finding["path"]) > 1024 or len(finding["evidence"]) > 4096 or len(finding["message"]) > 4096:
            raise RefinerError("Stored finding exceeds field limits")
        if finding["category"] not in {"security", "quality", "metadata", "link", "syntax", "compatibility"} or finding["severity"] not in {"info", "low", "medium", "high", "critical"} or finding["verification"] != "unverified" or finding["provenance"] not in {"static", "semantic"}:
            raise RefinerError("Invalid stored finding classification")
        if "path_digest" in finding and (not isinstance(finding["path_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", finding["path_digest"])):
            raise RefinerError("Invalid stored finding path digest")
        if "dismissed" in finding and (not isinstance(finding["dismissed"], dict) or set(finding["dismissed"]) != {"reason", "status"} or finding["dismissed"].get("status") not in {"dismissed", "risk-accepted"} or not isinstance(finding["dismissed"].get("reason"), str)):
            raise RefinerError("Invalid stored finding dismissal")


def _validated_semantic(snapshot, stored: dict) -> list[dict]:
    semantic = [item for item in stored["findings"] if item.get("provenance") == "semantic"]
    if not semantic:
        return []
    normalized = merge_semantic(snapshot, {"findings": []}, semantic)["findings"]
    if canonical(normalized) != canonical(semantic):
        raise RefinerError("Stored semantic findings no longer validate")
    return semantic


def _save(reports: Path, index_path: Path, index: dict, report: dict, key: str):
    values = index["reviews"].setdefault(key, [])
    name = f"{key}-{len(values) + 1}.json"
    _report_name(name, key)
    private_directory(reports)
    write_json(reports / name, report)
    values.append(name)
    index["history"].append(name)
    write_json(index_path, index)


def _secrets_all(snapshot, context, profile):
    result = [*_secrets(snapshot), *secret_values(context)]
    for value in profile.get("conventions", []):
        result.extend(secret_values(value))
    return result


def _apply_dismissals(findings, index, policy):
    output = []
    for finding in findings:
        item = dict(finding)
        record = next((value for value in reversed(index["dismissals"]) if (
            value.get("finding_id") == item.get("id")
            and value.get("rule") == item.get("rule")
            and value.get("evidence_digest") == item.get("evidence_digest")
            and value.get("policy_digest") == policy
        )), None)
        if record:
            item["dismissed"] = {
                "reason": record["reason"],
                "status": "risk-accepted" if item.get("category") == "security" else "dismissed",
            }
        output.append(item)
    return output


def _replayed_view(stored, index, findings=None):
    item = dict(stored)
    item["findings"] = _apply_dismissals(
        list(stored.get("findings", [])) if findings is None else findings,
        index,
        stored.get("policy_digest"),
    )
    item["status"] = "replayed"
    return item


def _prior(index, reports, source_id, context_digest, profile_digest, policy_digest):
    for name in reversed(index["history"]):
        item = _load_report(reports, name)
        if (
            item.get("source_id") == source_id
            and item.get("context_digest") == context_digest
            and item.get("profile_digest") == profile_digest
            and item.get("policy_digest") == policy_digest
            and item.get("semantic_status") == "completed"
            and item.get("checks", {}).get("static") == "completed"
        ):
            return item
    return None


def _static_identity(findings):
    return {(item.get("id"), item.get("evidence_digest")) for item in findings if item.get("provenance") == "static"}


def review(source, state_dir, profile=None, context="", force=False):
    if not isinstance(context, str) or len(context) > 64 * 1024:
        raise RefinerError("Invalid review context")
    snapshot = inventory(source)
    profile = validate_profile(profile)
    secrets_found = _secrets_all(snapshot, context, profile)
    source_id = _sid(snapshot)
    context_digest = digest(context)
    profile_digest = digest(profile)
    fingerprints = _fingerprints()
    policy_digest = _policy_digest(fingerprints)
    state, reports, index_path, index = _open_state(state_dir, create=True, source=source)
    key = _key(snapshot, source_id, profile_digest, context_digest, fingerprints)
    old = index["reviews"].get(key, [])
    current_static = analyze(snapshot)
    if old and not force:
        stored = _load_report(reports, old[-1], key)
        if stored.get("source_digest") != snapshot.digest or stored.get("policy_digest") != policy_digest or stored.get("fingerprints") != fingerprints:
            raise RefinerError("Stored review identity is invalid")
        if _static_identity(stored.get("findings", [])) != _static_identity(current_static):
            raise RefinerError("Stored static findings no longer reproduce")
        semantic = _validated_semantic(snapshot, stored)
        item = _replayed_view(stored, index, current_static + semantic)
        if inventory(source).digest != snapshot.digest:
            raise RefinerError("Skill source changed while reviewing")
        return redact_tree(item, secrets_found)
    previous = _prior(index, reports, source_id, context_digest, profile_digest, policy_digest) if force else None
    findings = _apply_dismissals(current_static, index, policy_digest)
    before = {item["id"] for item in previous.get("findings", [])} if previous else set()
    now = {item["id"] for item in findings}
    report = {
        "schema_version": SCHEMA_VERSION,
        "review_key": key,
        "source_id": source_id,
        "source_digest": snapshot.digest,
        "policy_digest": policy_digest,
        "fingerprints": fingerprints,
        "context_digest": context_digest,
        "profile_digest": profile_digest,
        "manifest": snapshot.manifest,
        "findings": findings,
        "omitted": snapshot.omitted,
        "status": "fresh",
        "semantic_status": "pending",
        "checks": {"static": "completed", "semantic": "pending"},
        "comparison": {
            "prior_review_key": previous.get("review_key") if previous else None,
            "prior_source_id": previous.get("source_id") if previous else None,
            "added": sorted(now - before),
            "removed": sorted(before - now),
        },
        "limitations": [
            _STATIC_SCOPE_LIMITATION,
            _EXECUTION_LIMITATION,
            "Semantic review is pending; all findings remain unverified.",
        ],
    }
    report = redact_tree(report, secrets_found)
    if inventory(source).digest != snapshot.digest:
        raise RefinerError("Skill source changed while reviewing")
    _save(reports, index_path, index, report, key)
    return report


def _stored_exact(index, reports, report, *, pending_only=False):
    if not isinstance(report, dict) or not isinstance(report.get("review_key"), str):
        raise RefinerError("Review key is invalid")
    names = index["reviews"].get(report["review_key"], [])
    for name in reversed(names):
        stored = _load_report(reports, name, report["review_key"])
        if pending_only and stored.get("semantic_status") != "pending":
            continue
        if canonical(stored) == canonical(report) or canonical(_replayed_view(stored, index)) == canonical(report):
            return stored
    raise RefinerError("Review is not an exact stored artifact")


def complete_review(source, report, state_dir, findings):
    snapshot = inventory(source)
    state, reports, index_path, index = _open_state(state_dir, create=False, source=source)
    stored = _stored_exact(index, reports, report, pending_only=True)
    fingerprints = _fingerprints()
    expected_key = _key(snapshot, _sid(snapshot), stored.get("profile_digest"), stored.get("context_digest"), fingerprints)
    if (
        stored.get("review_key") != expected_key
        or stored.get("source_digest") != snapshot.digest
        or stored.get("source_id") != _sid(snapshot)
        or stored.get("fingerprints") != fingerprints
        or stored.get("policy_digest") != _policy_digest(fingerprints)
    ):
        raise RefinerError("Review does not match active source, profile, context, or policy")
    current_static = analyze(snapshot)
    if _static_identity(current_static) != _static_identity(stored.get("findings", [])):
        raise RefinerError("Static findings changed; request a new review")
    current_static = _apply_dismissals(current_static, index, stored["policy_digest"])
    output = merge_semantic(snapshot, {**stored, "findings": current_static}, findings)
    output["semantic_status"] = "completed"
    output["checks"] = {**output["checks"], "semantic": "completed"}
    previous = _prior(
        index,
        reports,
        stored["source_id"],
        stored["context_digest"],
        stored["profile_digest"],
        stored["policy_digest"],
    )
    before = {item["id"] for item in previous.get("findings", [])} if previous else set()
    after = {item["id"] for item in output["findings"]}
    output["comparison"] = {
        "prior_review_key": previous.get("review_key") if previous else None,
        "prior_source_id": previous.get("source_id") if previous else None,
        "added": sorted(after - before),
        "removed": sorted(before - after),
    }
    output["limitations"] = [
        _STATIC_SCOPE_LIMITATION,
        _EXECUTION_LIMITATION,
        "Findings remain unverified until controlled reproduction confirms them.",
    ]
    if inventory(source).digest != snapshot.digest:
        raise RefinerError("Skill source changed while completing review")
    _save(reports, index_path, index, output, output["review_key"])
    return output


def dismiss(state_dir, report, finding_id, reason):
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
        raise RefinerError("Dismissal requires a bounded reason")
    state, reports, index_path, index = _open_state(state_dir, create=False)
    stored = _stored_exact(index, reports, report)
    finding = next((item for item in stored.get("findings", []) if item.get("id") == finding_id), None)
    if not finding:
        raise RefinerError("Unknown finding")
    secrets_found = secret_values(reason)
    record = {
        "finding_id": finding_id,
        "rule": finding["rule"],
        "evidence_digest": finding.get("evidence_digest", ""),
        "policy_digest": stored.get("policy_digest", ""),
        "reason": redact_tree(reason, secrets_found),
    }
    index["dismissals"].append(record)
    write_json(index_path, index)
    return record


def record_decision(state_dir, record):
    if not isinstance(record, dict):
        raise RefinerError("Decision must be a mapping")
    state, reports, index_path, index = _open_state(state_dir, create=False)
    value = {key: record[key] for key in _DECISION_INPUT if key in record}
    required = {"proposal_id", "base_digest", "proposal_digest", "decision", "reason", "timestamp"}
    if not required <= set(value) or value.get("decision") not in {"apply", "reject"}:
        raise RefinerError("Invalid decision record")
    if not all(isinstance(item, str) for item in value.values()):
        raise RefinerError("Invalid decision record")
    if not re.fullmatch(r"[0-9a-f]{64}", value["base_digest"]) or not re.fullmatch(r"[0-9a-f]{64}", value["proposal_digest"]):
        raise RefinerError("Invalid decision digest")
    if "output_digest" in value and not re.fullmatch(r"[0-9a-f]{64}", value["output_digest"]):
        raise RefinerError("Invalid output digest")
    value["provenance"] = "human-chat-script; format record, not cryptographic authentication"
    strings = [part for part in value.values() if isinstance(part, str)]
    secrets_found = [secret for part in strings for secret in secret_values(part)]
    value = redact_tree(value, secrets_found)
    index["decisions"].append(value)
    write_json(index_path, index)
    return value


def require_approved_decision(state_dir, approval, source):
    """Require the latest matching recorded decision before publishing a copy."""
    _, _, _, index = _open_state(state_dir, create=False, source=source)
    fields = ("proposal_id", "base_digest", "proposal_digest")
    record = next((item for item in reversed(index["decisions"]) if all(item.get(key) == approval.get(key) for key in fields)), None)
    if record is None or record.get("decision") != "apply" or record.get("timestamp") != approval.get("timestamp"):
        raise RefinerError("Approval must match the latest decision in this owned history")
    return record


def require_completed_report(source, state_dir, report):
    """Bind proposal preparation to a completed review of the current input."""
    snapshot = inventory(source)
    _, reports, _, index = _open_state(state_dir, create=False, source=source)
    stored = _stored_exact(index, reports, report)
    fingerprints = _fingerprints()
    if stored.get("semantic_status") != "completed":
        raise RefinerError("Complete semantic review before preparing a proposal")
    expected = _key(snapshot, _sid(snapshot), stored["profile_digest"], stored["context_digest"], fingerprints)
    if stored["review_key"] != expected or stored["source_digest"] != snapshot.digest or stored["fingerprints"] != fingerprints:
        raise RefinerError("Completed review no longer matches the source or review policy")
    if _static_identity(stored["findings"]) != _static_identity(analyze(snapshot)):
        raise RefinerError("Completed static findings no longer reproduce")
    _validated_semantic(snapshot, stored)
    return stored


def forget(state_dir):
    state = _absolute(Path(state_dir))
    if not state.exists():
        return {"records_removed": 0}
    state, reports, index_path, index = _open_state(state, create=False)
    count = 0
    for name in list(index["history"]):
        path = reject_links(reports / _report_name(name))
        path.unlink()
        count += 1
    if reports.exists():
        reports.rmdir()
    if index_path.exists():
        reject_links(index_path).unlink()
        count += 1
    marker = reject_links(state / _STATE_MARKER)
    marker.unlink()
    count += 1
    state.rmdir()
    return {"records_removed": count}
