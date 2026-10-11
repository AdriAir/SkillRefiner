import tempfile
from pathlib import Path

from refinerlib import snapshot


def test_review_uses_a_cleaned_independent_temporary_copy(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\n")
    (source / "blob.bin").write_bytes(b"\x00\xff")
    before = snapshot.inventory(source)
    original = tempfile.TemporaryDirectory
    created = []

    def tracked(*args, **kwargs):
        directory = original(*args, **kwargs)
        created.append(Path(directory.name))
        return directory

    monkeypatch.setattr(tempfile, "TemporaryDirectory", tracked)
    prepared = snapshot.prepared_inventory(source)
    assert created and all(not path.exists() for path in created)
    assert prepared.root == before.root
    assert prepared.files == before.files
    assert prepared.digest == snapshot.inventory(source).digest == before.digest


def test_git_pointer_files_are_explicitly_omitted_without_reading(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\n")
    (source / ".git").write_text("gitdir: privateexternalpath\n")
    result = snapshot.inventory(source)
    assert ".git" not in result.files
    assert {"path": ".git", "reason": "git-metadata", "bytes": 0} in result.omitted
