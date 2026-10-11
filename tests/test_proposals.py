import json
from pathlib import Path

import pytest

from refinerlib.common import RefinerError
from refinerlib.proposals import apply, approve, propose, public_proposal
from refinerlib.analysis import analyze
from refinerlib.snapshot import inventory


def skill(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "demo"
    root.mkdir()
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def test_proposal_requires_exact_approval_then_applies_a_distinct_copy(tmp_path):
    source = skill(tmp_path, {"SKILL.md": "---\nname: demo\ndescription: Demo\n---\nold\n"})
    original = (source / "SKILL.md").read_bytes()
    proposal = propose(source, [{"path": "SKILL.md", "content": "---\nname: demo\ndescription: Demo\n---\nnew\n"}], "Update wording")

    with pytest.raises(RefinerError, match="approval"):
        apply(source, proposal, {"decision": "apply"}, tmp_path / "copy")

    approval = approve(proposal, proposal["base_digest"], proposal["proposal_digest"], "apply", "approved")
    result = apply(source, proposal, approval, tmp_path / "copy")

    assert result["status"] == "applied"
    assert result["output"] == str(tmp_path / "copy")
    assert (tmp_path / "copy" / "SKILL.md").read_text(encoding="utf-8").endswith("new\n")
    assert (source / "SKILL.md").read_bytes() == original


def test_proposal_supports_add_edit_delete_and_reapply_is_noop_only_for_expected_postimage(tmp_path):
    source = skill(tmp_path, {"SKILL.md": "---\nname: demo\ndescription: Demo\n---\nold\n", "remove.md": "bye\n"})
    proposal = propose(source, [
        {"path": "SKILL.md", "content": "---\nname: demo\ndescription: Demo\n---\nnew\n"},
        {"path": "added.md", "content": "added\n"},
        {"path": "remove.md", "content": None},
    ], "Apply three changes")
    approval = approve(proposal, proposal["base_digest"], proposal["proposal_digest"], "apply")
    output = tmp_path / "copy"

    assert apply(source, proposal, approval, output)["status"] == "applied"
    assert apply(source, proposal, approval, output)["status"] == "noop"
    (output / "added.md").write_text("drift\n", encoding="utf-8")
    with pytest.raises(RefinerError, match="conflict"):
        apply(source, proposal, approval, output)


def test_tampering_and_stale_sources_are_rejected_before_any_output_is_created(tmp_path):
    source = skill(tmp_path, {"SKILL.md": "---\nname: demo\ndescription: Demo\n---\nold\n"})
    proposal = propose(source, [{"path": "SKILL.md", "content": "---\nname: demo\ndescription: Demo\n---\nnew\n"}], "Update")
    approval = approve(proposal, proposal["base_digest"], proposal["proposal_digest"], "apply")
    proposal["purpose"] = "tampered"
    output = tmp_path / "copy"

    with pytest.raises(RefinerError, match="proposal"):
        apply(source, proposal, approval, output)
    assert not output.exists()

    proposal = propose(source, [{"path": "SKILL.md", "content": "---\nname: demo\ndescription: Demo\n---\nnew\n"}], "Update")
    approval = approve(proposal, proposal["base_digest"], proposal["proposal_digest"], "apply")
    (source / "SKILL.md").write_text("changed after proposal\n", encoding="utf-8")
    with pytest.raises(RefinerError, match="outdated"):
        apply(source, proposal, approval, output)
    assert not output.exists()


def test_public_proposal_redacts_source_and_replacement_secrets_but_retains_digest(tmp_path):
    source = skill(tmp_path, {"SKILL.md": "api_key=secretvalue123\n"})
    proposal = propose(source, [{"path": "SKILL.md", "content": "token=replacementsecret456\n"}], "Replace api_key=secretvalue123")
    public = public_proposal(proposal)
    rendered = json.dumps(public)

    assert public["proposal_digest"] == proposal["proposal_digest"]
    assert "secretvalue123" not in rendered
    assert "replacementsecret456" not in rendered
    assert "[REDACTED]" in rendered


def test_proposal_rejects_unsafe_paths_and_rejected_decisions_cannot_apply(tmp_path):
    source = skill(tmp_path, {"SKILL.md": "---\nname: demo\ndescription: Demo\n---\nold\n"})
    with pytest.raises(RefinerError):
        propose(source, [{"path": "../escape", "content": "x"}], "Unsafe")

    proposal = propose(source, [{"path": "SKILL.md", "content": "---\nname: demo\ndescription: Demo\n---\nnew\n"}], "Update")
    rejected = approve(proposal, proposal["base_digest"], proposal["proposal_digest"], "reject")
    with pytest.raises(RefinerError, match="apply"):
        apply(source, proposal, rejected, tmp_path / "copy")


def test_repaired_copy_no_longer_exhibits_the_same_defect(tmp_path):
    source = skill(tmp_path, {"SKILL.md": "---\nname: demo\ndescription: Demo\n---\n[Guide](missing.md)\n"})
    assert any(f["rule"] == "broken-local-link" for f in analyze(inventory(source)))
    changes = [{"path": "SKILL.md", "old": "[Guide](missing.md)", "new": "Use the local output description."}]
    proposal = propose(source, changes, "Remove a reference to an absent guide")
    approval = approve(proposal, proposal["base_digest"], proposal["proposal_digest"], "apply")
    output = tmp_path / "copy"
    apply(source, proposal, approval, output)
    assert not any(f["rule"] == "broken-local-link" for f in analyze(inventory(output)))
    assert any(f["rule"] == "broken-local-link" for f in analyze(inventory(source)))
    assert apply(source, proposal, approval, output)["status"] == "noop"
    with pytest.raises(RefinerError, match="exactly once"):
        propose(output, changes, "Repeat the same correction")
