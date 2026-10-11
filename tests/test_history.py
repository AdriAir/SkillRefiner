import json
from pathlib import Path

import pytest

from refinerlib.common import RefinerError
from refinerlib.history import complete_review, default_state_dir, dismiss, forget, record_decision, review, validate_profile


def skill(tmp_path: Path, text="---\nname: demo\ndescription: Demo skill\n---\nHello") -> Path:
    root = tmp_path / "demo"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_bytes(text.encode("utf-8"))
    return root


def test_validate_profile_rejects_unknown_security_knobs():
    assert validate_profile(None)["language"] == "es"
    assert validate_profile({"language": "es", "tone": "direct", "detail": "concise", "conventions": ["x"]})["language"] == "es"
    with pytest.raises(RefinerError):
        validate_profile({"security": "off"})


def test_review_persists_only_redacted_pending_artifact_and_replays(tmp_path):
    source, state = skill(tmp_path, "api_key=secretvalue123\n"), tmp_path / "state"
    first = review(source, state, context="focus")
    replay = review(source, state, context="focus")
    assert first["status"] == "fresh"
    assert first["semantic_status"] == "pending"
    assert replay["status"] == "replayed"
    assert replay["semantic_status"] == "pending"
    assert "secretvalue123" not in "".join(path.read_text(encoding="utf-8") for path in state.rglob("*.json"))


def test_complete_review_and_force_keep_prior_revision_and_compare(tmp_path):
    source, state = skill(tmp_path), tmp_path / "state"
    initial = review(source, state)
    completed = complete_review(source, initial, state, [])
    assert completed["semantic_status"] == "completed"
    forced = review(source, state, force=True)
    assert forced["status"] == "fresh"
    assert forced["comparison"]["prior_review_key"] == initial["review_key"]
    assert len(list(state.glob("reports/*.json"))) >= 2


def test_complete_review_accepts_a_pending_review_with_context(tmp_path):
    source, state = skill(tmp_path), tmp_path / "state"
    pending = review(source, state, context="release review")
    assert complete_review(source, pending, state, [])["semantic_status"] == "completed"


def test_dismissal_is_scoped_to_evidence_and_forget_only_state(tmp_path):
    source, state = skill(tmp_path, "eval('x')\n"), tmp_path / "state"
    report = review(source, state)
    finding = report["findings"][0]
    dismissed = dismiss(state, report, finding["id"], "accepted token=secretvalue123")
    assert dismissed["finding_id"] == finding["id"]
    replay = review(source, state)
    visible = next(item for item in replay["findings"] if item["id"] == finding["id"])
    assert visible["dismissed"]["reason"] == "accepted token=[REDACTED]"
    assert forget(state)["records_removed"] > 0
    assert source.exists()


def test_default_state_dir_uses_platform_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert default_state_dir() == tmp_path / "skill-refiner"


def test_default_state_dir_uses_public_windows_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert default_state_dir() == tmp_path / "SkillRefiner"


def test_report_persists_digests_not_raw_context_or_profile_secrets(tmp_path):
    source, state = skill(tmp_path), tmp_path / "state"
    report = review(source, state, context="token=secretvalue123", profile={"conventions": ["password=anothersecret456"]})
    assert report["context_digest"]
    assert report["profile_digest"]
    stored = "".join(item.read_text(encoding="utf-8") for item in state.rglob("*.json"))
    assert "secretvalue123" not in stored
    assert "anothersecret456" not in stored
    assert "context" not in report
    assert "profile" not in report


def test_force_comparison_uses_same_source_lineage_only(tmp_path):
    state = tmp_path / "state"
    first = skill(tmp_path / "one")
    second = skill(tmp_path / "two")
    pending = review(first, state, context="same")
    complete_review(first, pending, state, [])
    review(second, state, context="same")
    forced = review(first, state, context="same", force=True)
    assert forced["comparison"]["prior_review_key"]
    assert forced["comparison"]["prior_source_id"] == forced["source_id"]


def test_review_rejects_foreign_or_overlapping_state(tmp_path):
    source = skill(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(RefinerError, match="[Ss]tate"):
        review(source, foreign)
    with pytest.raises(RefinerError, match="outside"):
        review(source, tmp_path)
    with pytest.raises(RefinerError, match="outside"):
        review(source, source / "state")


def test_forget_nonexistent_does_not_create_and_foreign_is_rejected(tmp_path):
    missing = tmp_path / "missing"
    assert forget(missing) == {"records_removed": 0}
    assert not missing.exists()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "index.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RefinerError):
        forget(foreign)
    assert (foreign / "index.json").exists()


def test_complete_and_dismiss_require_the_stored_unaltered_report(tmp_path):
    source, state = skill(tmp_path, "eval('x')\n"), tmp_path / "state"
    report = review(source, state)
    altered = {**report, "source_digest": "0" * 64}
    with pytest.raises(RefinerError):
        complete_review(source, altered, state, [])
    fabricated = {**report, "findings": [{**report["findings"][0], "rule": "fabricated"}]}
    with pytest.raises(RefinerError):
        dismiss(state, fabricated, report["findings"][0]["id"], "reason")


def test_decisions_are_whitelisted_redacted_and_owned(tmp_path):
    source, state = skill(tmp_path), tmp_path / "state"
    review(source, state)
    stored = record_decision(state, {
        "proposal_id": "p1", "base_digest": "a" * 64, "proposal_digest": "b" * 64,
        "decision": "apply", "reason": "token=secretvalue123", "timestamp": "2026-01-01T00:00:00Z",
        "output_digest": "c" * 64, "diff": "must not persist",
    })
    assert set(stored) == {"proposal_id", "base_digest", "proposal_digest", "decision", "reason", "timestamp", "output_digest", "provenance"}
    assert "secretvalue123" not in json.dumps(stored)
    with pytest.raises(RefinerError):
        record_decision(tmp_path / "foreign", {"decision": "apply"})


def test_forget_deletes_only_tracked_owned_state(tmp_path):
    source, state = skill(tmp_path), tmp_path / "state"
    review(source, state)
    extra = state / "do-not-delete.txt"
    extra.write_text("foreign", encoding="utf-8")
    with pytest.raises(RefinerError):
        forget(state)
    assert extra.exists()


def test_replay_rejects_a_structurally_poisoned_stored_report(tmp_path, monkeypatch):
    source, state = skill(tmp_path), tmp_path / "state"
    report = review(source, state)
    monkeypatch.setattr("refinerlib.history._fingerprints", lambda: report["fingerprints"])
    report_path = next((state / "reports").glob("*.json"))
    poisoned = json.loads(report_path.read_text(encoding="utf-8"))
    poisoned["findings"].append({"raw_context": "token=secretvalue123"})
    report_path.write_text(json.dumps(poisoned), encoding="utf-8")
    with pytest.raises(RefinerError, match="stored finding"):
        review(source, state)


def test_pending_replay_can_be_completed_but_not_forged(tmp_path):
    source, state = skill(tmp_path), tmp_path / "state"
    review(source, state)
    replayed = review(source, state)
    assert replayed["status"] == "replayed"
    assert complete_review(source, replayed, state, [])["semantic_status"] == "completed"
    forged = {**replayed, "limitations": ["forged"]}
    with pytest.raises(RefinerError):
        complete_review(source, forged, state, [])


def test_completed_replay_can_be_dismissed_using_stored_evidence(tmp_path):
    source, state = skill(tmp_path, "eval('x')\n"), tmp_path / "state"
    pending = review(source, state)
    complete_review(source, pending, state, [])
    replayed = review(source, state)
    finding = replayed["findings"][0]
    assert dismiss(state, replayed, finding["id"], "accepted")["finding_id"] == finding["id"]


def test_completed_comparison_uses_final_semantic_findings_and_updates_limitations(tmp_path):
    source, state = skill(tmp_path, "---\nname: demo\ndescription: Demo\n---\nsemantic evidence\n"), tmp_path / "state"
    initial = review(source, state)
    complete_review(source, initial, state, [])
    pending = review(source, state, force=True)
    semantic = {
        "rule": "semantic-rule", "path": "SKILL.md", "evidence": "semantic evidence", "line": 999,
        "category": "quality", "severity": "low", "message": "Review evidence",
        "verification": "verified", "provenance": "semantic",
    }
    completed = complete_review(source, pending, state, [semantic])
    semantic_id = next(item["id"] for item in completed["findings"] if item["provenance"] == "semantic")
    assert semantic_id in completed["comparison"]["added"]
    assert all("pending" not in limitation.lower() for limitation in completed["limitations"])
    assert any("Python syntax" in limitation for limitation in completed["limitations"])
    assert any("separate execution records" in limitation for limitation in completed["limitations"])


def test_review_records_git_omission_and_honest_static_scope(tmp_path):
    source, state = skill(tmp_path), tmp_path / "state"
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("secret=secretvalue123", encoding="utf-8")
    report = review(source, state)
    assert {"path": ".git", "reason": "git-metadata", "bytes": 0} in report["omitted"]
    assert any("Python syntax" in limitation for limitation in report["limitations"])
    assert any("runtime behavior" in limitation for limitation in report["limitations"])
