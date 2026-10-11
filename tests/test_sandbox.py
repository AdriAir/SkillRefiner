import pytest
from refinerlib.common import RefinerError
from refinerlib.sandbox import SandboxConfig, command_for, run_test

IMAGE = "python@sha256:" + "a" * 64
_DSA_BODY = "synthetic-dsa-body-marker-0123456789"


def test_hardened_command_has_no_network_or_writable_host_mount(tmp_path):
    command = command_for(tmp_path, "scripts/check.py", ["--help"], SandboxConfig(image=IMAGE), "refiner-test")
    assert command[0:2] == ["docker", "run"]
    for item in ("--read-only", "--network=none", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534", "--pull=never", "--pids-limit=64", "--memory=512m", "--cpus=1"):
        assert item in command
    mount = command[command.index("--mount") + 1]
    assert mount.endswith(",readonly")
    assert "/var/run/docker.sock" not in " ".join(command)
    assert command[command.index("--entrypoint") + 1] == "python"
    assert command[-3:] == ["-I", "/input/scripts/check.py", "--help"]


@pytest.mark.parametrize("image", ["python:latest", "python:3.14", "-v@sha256:" + "a"*64])
def test_unpinned_or_option_image_rejected(image):
    with pytest.raises(RefinerError):
        SandboxConfig(image=image)


@pytest.mark.parametrize("path", ["../bad.py", "/bad.py", "x.ps1", "x.py:stream"])
def test_unsupported_or_escaping_script_rejected(tmp_path, path):
    with pytest.raises(RefinerError):
        command_for(tmp_path, path, [], SandboxConfig(image=IMAGE), "refiner-test")


def test_no_host_fallback_when_docker_unavailable(tmp_path, monkeypatch):
    (tmp_path / "SKILL.md").write_text("---\nname: test\ndescription: Test\n---\n")
    (tmp_path / "check.py").write_text("raise RuntimeError('DO NOT EXECUTE ON HOST')")
    monkeypatch.setattr("refinerlib.sandbox.shutil.which", lambda _: None)
    result = run_test(tmp_path, "check.py", [], SandboxConfig(image=IMAGE))
    assert result["status"] == "blocked"
    assert "Docker" in result["reason"]


@pytest.mark.parametrize("secret", [
    "github_pat_" + "A" * 82,
    "glpat-" + "A" * 24,
    "xoxb-" + "1" * 12 + "-" + "A" * 24,
    "sk_live_" + "A" * 24,
    "ASIA" + "A" * 16,
    "-----BEGIN DSA PRIVATE KEY-----\n" + _DSA_BODY + "\n-----END DSA PRIVATE KEY-----",
])
def test_sandbox_blocks_recognizable_secret_prefixes_before_docker(tmp_path, secret):
    (tmp_path / "check.py").write_text(secret, encoding="utf-8")
    result = run_test(tmp_path, "check.py", [], SandboxConfig(image=IMAGE))
    assert result["status"] == "blocked"
    assert "credentials" in result["reason"]
