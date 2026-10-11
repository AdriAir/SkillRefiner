import pytest
from refinerlib.common import RefinerError
from refinerlib.proposals import propose, approve, apply


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\n")
    (folder / "README.md").write_text("original")
    return folder


def test_case_alias_cannot_disguise_overwrite_as_addition(source):
    with pytest.raises(RefinerError):
        propose(source, [{"path": "readme.md", "content": "replacement"}], "Change")


def test_proposal_must_validate_full_file_tree_before_approval(source):
    with pytest.raises(RefinerError):
        propose(source, [{"path": "a", "content": "file"}, {"path": "a/b", "content": "nested"}], "Change")


def test_replacement_preserves_unaffected_private_values(source, tmp_path):
    (source / "code.py").write_text('token="privatecredential123"\nprint("before")\n')
    proposal = propose(source, [{"path": "code.py", "old": 'print("before")', "new": 'print("after")'}], "Update print")
    decision = approve(proposal, proposal["base_digest"], proposal["proposal_digest"], "apply")
    output = tmp_path / "copy"
    apply(source, proposal, decision, output)
    assert (output / "code.py").read_text() == 'token="privatecredential123"\nprint("after")\n'


def test_mask_cannot_accidentally_be_written_as_original_secret(source):
    (source / "code.py").write_text('token="privatecredential123"\nprint("before")\n')
    with pytest.raises(RefinerError):
        propose(source, [{"path": "code.py", "content": 'token="[REDACTED]"\nprint("after")\n'}], "Update print")


def test_reapply_rejects_added_excluded_git_artifacts(source, tmp_path):
    proposal = propose(source, [{"path": "README.md", "content": "replacement"}], "Change")
    decision = approve(proposal, proposal["base_digest"], proposal["proposal_digest"], "apply")
    output = tmp_path / "copy"
    apply(source, proposal, decision, output)
    (output / ".git").mkdir()
    with pytest.raises(RefinerError):
        apply(source, proposal, decision, output)


def test_directory_case_alias_is_not_a_portable_postimage(source):
    with pytest.raises(RefinerError):
        propose(source, [{"path": "Dir/a", "content": "a"}, {"path": "dir/b", "content": "b"}], "Change")


def test_binary_edits_fail_before_generating_private_diff(source):
    (source / "data.bin").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(RefinerError):
        propose(source, [{"path": "data.bin", "content": "new"}], "Change")
