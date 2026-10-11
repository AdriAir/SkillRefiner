import json
import subprocess
import sys
from pathlib import Path

from refinerlib.proposals import propose as build_proposal


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "plugins/skill-refiner/skills/skill-refiner/scripts/refiner.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def skill(tmp_path: Path, text: str = "old\n") -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_bytes(
        ("---\nname: demo\ndescription: Demo\n---\n" + text).encode("utf-8")
    )
    return source


def output(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def completed_report(source: Path, state: Path, directory: Path) -> Path:
    pending = directory / "pending-report.json"
    findings = directory / "findings.json"
    completed = directory / "completed-report.json"
    findings.write_text("[]", encoding="utf-8")
    output(run_cli("review", str(source), "--state-dir", str(state), "--report-file", str(pending)))
    output(run_cli("semantic", str(source), "--state-dir", str(state), "--report", str(pending), "--findings", str(findings), "--report-file", str(completed)))
    return completed


def test_cli_runs_review_semantic_propose_approve_and_apply_without_leaking_secrets(tmp_path):
    source = skill(tmp_path, "token=secretvalue123\nold\n")
    state = tmp_path / "state"
    report_file = tmp_path / "report.json"
    completed_file = tmp_path / "completed.json"
    findings = tmp_path / "findings.json"
    changes = tmp_path / "changes.json"
    proposal = tmp_path / "proposal.json"
    approval = tmp_path / "approval.json"
    copied = tmp_path / "copy"
    findings.write_text(json.dumps([{
        "rule": "clarity", "path": "SKILL.md", "evidence": "old",
        "category": "quality", "severity": "low", "message": "Use clearer text",
    }]), encoding="utf-8")
    changes.write_text(json.dumps([{
        "path": "SKILL.md",
        "old": "old\n",
        "new": "new\n",
    }]), encoding="utf-8")

    review = output(run_cli("review", str(source), "--state-dir", str(state), "--context", "token=secretvalue123", "--report-file", str(report_file)))
    assert review["semantic_status"] == "pending"
    assert "secretvalue123" not in json.dumps(review)
    semantic = output(run_cli("semantic", str(source), "--report", str(report_file), "--findings", str(findings), "--state-dir", str(state), "--report-file", str(completed_file)))
    assert semantic["semantic_status"] == "completed"
    assert any(item["rule"] == "clarity" for item in semantic["findings"])
    public = output(run_cli("propose", str(source), "--report", str(completed_file), "--changes", str(changes), "--purpose", "Correct wording", "--verification", "pytest", "--proposal-file", str(proposal), "--state-dir", str(state)))
    assert public["proposal_digest"]
    assert proposal.exists()
    approved = output(run_cli("approve", "--target", str(source), "--report", str(completed_file), "--proposal-file", str(proposal), "--base-digest", public["base_digest"], "--proposal-digest", public["proposal_digest"], "--decision", "apply", "--approval-file", str(approval), "--state-dir", str(state)))
    assert approved["decision"] == "apply"
    applied = output(run_cli("apply", str(source), "--proposal-file", str(proposal), "--approval-file", str(approval), "--output", str(copied), "--state-dir", str(state)))
    assert applied["status"] == "applied"
    assert applied["static_verification"]["status"] == "completed"
    assert (copied / "SKILL.md").read_text(encoding="utf-8").endswith("new\n")
    assert (source / "SKILL.md").read_text(encoding="utf-8").endswith("old\n")
    assert not proposal.exists()
    assert "secretvalue123" not in "".join(path.read_text(encoding="utf-8") for path in state.rglob("*.json"))


def test_cli_rejects_stale_or_rejected_proposals_and_removes_raw_artifacts(tmp_path):
    source = skill(tmp_path)
    state = tmp_path / "state"
    changes = tmp_path / "changes.json"
    proposal = tmp_path / "proposal.json"
    approval = tmp_path / "approval.json"
    changes.write_text(json.dumps([{"path": "SKILL.md", "old": "old\n", "new": "new\n"}]), encoding="utf-8")
    report = completed_report(source, state, tmp_path)
    public = output(run_cli("propose", str(source), "--report", str(report), "--changes", str(changes), "--purpose", "Correct wording", "--proposal-file", str(proposal), "--state-dir", str(state)))
    output(run_cli("approve", "--target", str(source), "--report", str(report), "--proposal-file", str(proposal), "--base-digest", public["base_digest"], "--proposal-digest", public["proposal_digest"], "--decision", "reject", "--reason", "not now", "--approval-file", str(approval), "--state-dir", str(state)))
    assert not proposal.exists()
    assert not approval.exists()

    proposal = tmp_path / "stale.json"
    approval = tmp_path / "stale-approval.json"
    public = output(run_cli("propose", str(source), "--report", str(report), "--changes", str(changes), "--purpose", "Correct wording", "--proposal-file", str(proposal), "--state-dir", str(state)))
    output(run_cli("approve", "--target", str(source), "--report", str(report), "--proposal-file", str(proposal), "--base-digest", public["base_digest"], "--proposal-digest", public["proposal_digest"], "--decision", "apply", "--approval-file", str(approval), "--state-dir", str(state)))
    (source / "SKILL.md").write_bytes(b"---\nname: demo\ndescription: Demo\n---\nchanged\n")
    result = run_cli("apply", str(source), "--proposal-file", str(proposal), "--approval-file", str(approval), "--output", str(tmp_path / "copy"), "--state-dir", str(state))
    assert result.returncode != 0
    assert "outdated" in result.stderr.lower()
    assert proposal.exists()
    assert approval.exists()


def test_cli_payload_and_profile_outputs_are_redacted_and_json_only(tmp_path):
    source = skill(tmp_path, "token=secretvalue123\n")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({
        "language": "en", "tone": "direct", "detail": "concise",
        "conventions": ["password=anothersecret456"],
    }), encoding="utf-8")

    payload = output(run_cli("payload", str(source)))
    assert payload["trust"] == "UNTRUSTED"
    assert "secretvalue123" not in json.dumps(payload)
    rendered_profile = output(run_cli("profile", "--profile", str(profile)))
    assert "anothersecret456" not in json.dumps(rendered_profile)


def test_cli_approve_requires_target_and_does_not_mutate_foreign_state(tmp_path):
    source = skill(tmp_path)
    state = tmp_path / "state"
    proposal = tmp_path / "proposal.json"
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps([{"path": "SKILL.md", "old": "old\n", "new": "new\n"}]), encoding="utf-8")
    report = completed_report(source, state, tmp_path)
    public = output(run_cli("propose", str(source), "--report", str(report), "--changes", str(changes), "--purpose", "Correct wording", "--proposal-file", str(proposal), "--state-dir", str(state)))
    missing_target = run_cli("approve", "--proposal-file", str(proposal), "--base-digest", public["base_digest"], "--proposal-digest", public["proposal_digest"], "--decision", "apply", "--approval-file", str(tmp_path / "approval.json"), "--state-dir", str(state))
    assert missing_target.returncode != 0
    assert proposal.exists()


def test_cli_approve_checks_existing_approval_artifact_before_recording_decision(tmp_path):
    source = skill(tmp_path)
    state = tmp_path / "state"
    proposal = tmp_path / "proposal.json"
    approval = tmp_path / "approval.json"
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps([{"path": "SKILL.md", "old": "old\n", "new": "new\n"}]), encoding="utf-8")
    report = completed_report(source, state, tmp_path)
    public = output(run_cli("propose", str(source), "--report", str(report), "--changes", str(changes), "--purpose", "Correct wording", "--proposal-file", str(proposal), "--state-dir", str(state)))
    approval.write_text("existing", encoding="utf-8")
    result = run_cli("approve", "--target", str(source), "--report", str(report), "--proposal-file", str(proposal), "--base-digest", public["base_digest"], "--proposal-digest", public["proposal_digest"], "--decision", "apply", "--approval-file", str(approval), "--state-dir", str(state))
    assert result.returncode != 0
    index = json.loads((state / "index.json").read_text(encoding="utf-8"))
    assert index["decisions"] == []


def test_cli_apply_cannot_move_approval_to_a_new_history(tmp_path):
    source = skill(tmp_path)
    state = tmp_path / "state"
    changes = tmp_path / "changes.json"
    proposal = tmp_path / "proposal.json"
    approval = tmp_path / "approval.json"
    changes.write_text(json.dumps([{"path":"SKILL.md", "old":"old\n", "new":"new\n"}]))
    report = completed_report(source, state, tmp_path)
    public = output(run_cli("propose", str(source), "--report", str(report), "--changes", str(changes), "--purpose", "Change", "--proposal-file", str(proposal), "--state-dir", str(state)))
    output(run_cli("approve", "--target", str(source), "--report", str(report), "--proposal-file", str(proposal), "--base-digest", public["base_digest"], "--proposal-digest", public["proposal_digest"], "--decision", "apply", "--approval-file", str(approval), "--state-dir", str(state)))
    foreign = tmp_path / "new-state"
    result = run_cli("apply", str(source), "--proposal-file", str(proposal), "--approval-file", str(approval), "--output", str(tmp_path / "copy"), "--state-dir", str(foreign))
    assert result.returncode != 0
    assert not foreign.exists()
    assert not (tmp_path / "copy").exists()


def test_cli_public_proposal_redacts_deleted_private_key_from_original_snapshot(tmp_path):
    source = skill(tmp_path)
    key = "-----BEGIN PRIVATE KEY-----\nveryprivatekeymaterial123456789\n-----END PRIVATE KEY-----\n"
    (source / "key.pem").write_bytes(key.encode("utf-8"))
    state = tmp_path / "state"
    changes = tmp_path / "changes.json"
    proposal = tmp_path / "proposal.json"
    changes.write_text(json.dumps([{"path": "key.pem", "content": None}]), encoding="utf-8")
    report = completed_report(source, state, tmp_path)

    result = run_cli("propose", str(source), "--report", str(report), "--changes", str(changes), "--purpose", "Remove exposed key", "--proposal-file", str(proposal), "--state-dir", str(state))
    assert result.returncode == 0, result.stderr
    assert "veryprivatekeymaterial123456789" not in result.stdout
    assert "BEGIN PRIVATE KEY" not in result.stdout
    assert (source / "key.pem").read_bytes() == key.encode("utf-8")


def test_cli_review_rejects_state_inside_any_multi_target_before_mutating(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    first = skill(one)
    second = skill(two)
    state = second / "state"

    result = run_cli("review", str(first), str(second), "--state-dir", str(state))
    assert result.returncode != 0
    assert not state.exists()
    assert (first / "SKILL.md").exists()
    assert (second / "SKILL.md").exists()


def test_cli_propose_requires_a_completed_report_for_the_same_source(tmp_path):
    source = skill(tmp_path)
    state = tmp_path / "state"
    pending = tmp_path / "pending.json"
    changes = tmp_path / "changes.json"
    proposal = tmp_path / "proposal.json"
    changes.write_text(json.dumps([{"path": "SKILL.md", "old": "old\n", "new": "new\n"}]), encoding="utf-8")
    output(run_cli("review", str(source), "--state-dir", str(state), "--report-file", str(pending)))

    result = run_cli("propose", str(source), "--report", str(pending), "--changes", str(changes), "--purpose", "Change", "--proposal-file", str(proposal), "--state-dir", str(state))
    assert result.returncode != 0
    assert not proposal.exists()


def test_cli_propose_rejects_a_completed_report_from_a_different_source(tmp_path):
    one, two = tmp_path / "source-one", tmp_path / "source-two"
    one.mkdir()
    two.mkdir()
    source = skill(one)
    other = skill(two)
    state = tmp_path / "state"
    changes = tmp_path / "changes.json"
    proposal = tmp_path / "proposal.json"
    changes.write_text(json.dumps([{"path": "SKILL.md", "old": "old\n", "new": "new\n"}]), encoding="utf-8")
    report = completed_report(other, state, tmp_path)

    result = run_cli("propose", str(source), "--report", str(report), "--changes", str(changes), "--purpose", "Change", "--proposal-file", str(proposal), "--state-dir", str(state))
    assert result.returncode != 0
    assert not proposal.exists()
    assert (source / "SKILL.md").read_bytes().endswith(b"old\n")


def test_cli_approve_blocks_a_handcrafted_valid_proposal_when_review_is_pending(tmp_path):
    source = skill(tmp_path)
    state = tmp_path / "state"
    pending = tmp_path / "pending.json"
    proposal_file = tmp_path / "proposal.json"
    approval_file = tmp_path / "approval.json"
    output(run_cli("review", str(source), "--state-dir", str(state), "--report-file", str(pending)))
    proposal = build_proposal(source, [{"path": "SKILL.md", "old": "old\n", "new": "new\n"}], "Change")
    proposal_file.write_text(json.dumps(proposal), encoding="utf-8")

    result = run_cli("approve", "--target", str(source), "--report", str(pending), "--proposal-file", str(proposal_file), "--base-digest", proposal["base_digest"], "--proposal-digest", proposal["proposal_digest"], "--decision", "apply", "--approval-file", str(approval_file), "--state-dir", str(state))
    assert result.returncode != 0
    assert proposal_file.exists()
    assert not approval_file.exists()
    assert json.loads((state / "index.json").read_text(encoding="utf-8"))["decisions"] == []
