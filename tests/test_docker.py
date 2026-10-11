"""Opt-in Linux Docker integration checks against synthetic target scripts."""
import os
from pathlib import Path

import pytest

from refinerlib.sandbox import SandboxConfig, run_test
from refinerlib.snapshot import inventory

pytestmark = [pytest.mark.docker, pytest.mark.skipif(os.environ.get("SKILL_REFINER_DOCKER_TESTS") != "1", reason="Set SKILL_REFINER_DOCKER_TESTS=1 for live Docker checks")]


def skill(tmp_path, filename, body):
    root = tmp_path / "target"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: synthetic\ndescription: Synthetic sandbox case\n---\n", encoding="utf-8")
    (root / filename).write_text(body, encoding="utf-8")
    return root


def test_live_python_isolation_resources_and_original_unchanged(tmp_path):
    root = skill(tmp_path, "check.py", '''import os, socket
from pathlib import Path
assert os.getuid() == 65534
assert not Path('/var/run/docker.sock').exists()
assert not any(name in os.environ for name in ('OPENAI_API_KEY', 'AWS_ACCESS_KEY_ID', 'GITHUB_TOKEN'))
for filename in ('/input/SKILL.md', '/etc/forbidden'):
    try:
        Path(filename).write_text('unexpected')
    except OSError:
        pass
    else:
        raise AssertionError('read-only boundary failed')
Path('/work/ephemeral').write_text('allowed')
assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == str(512 * 1024 * 1024)
assert Path('/sys/fs/cgroup/pids.max').read_text().strip() == '64'
quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
assert int(quota) == int(period)
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
except OSError:
    pass
else:
    raise AssertionError('network boundary failed')
print('isolation verified')
''')
    before = inventory(root).digest
    result = run_test(root, "check.py")
    assert result["status"] == "passed", result
    assert result["cleanup"] == "confirmed"
    assert result["output"].strip() == "isolation verified"
    assert inventory(root).digest == before
    assert not (root / "ephemeral").exists()


def test_live_bash_support(tmp_path):
    root = skill(tmp_path, "check.sh", 'set -eu\ntest "$(id -u)" = 65534\necho bash-verified\n')
    result = run_test(root, "check.sh")
    assert result["status"] == "passed", result
    assert result["cleanup"] == "confirmed"


@pytest.mark.parametrize("body,timeout,cap,flag", [
    ("import time\ntime.sleep(60)\n", 2, 1048576, "timed_out"),
    ("import sys\nsys.stdout.write('x' * 1000000)\nsys.stdout.flush()\n", 30, 4096, "output_limited"),
])
def test_live_limits_and_cleanup(tmp_path, body, timeout, cap, flag):
    root = skill(tmp_path, "check.py", body)
    result = run_test(root, "check.py", config=SandboxConfig(timeout=timeout, output_bytes=cap))
    assert result["status"] == "failed", result
    assert result[flag], result
    assert result["cleanup"] == "confirmed"
    assert len(result["output"].encode()) <= cap


def test_live_secret_input_is_blocked_before_execution(tmp_path):
    root = skill(tmp_path, "check.py", 'import base64\ntoken="syntheticprivatecredential123"\nprint(base64.b64encode(token.encode()))\n')
    result = run_test(root, "check.py")
    assert result["status"] == "blocked"
    assert result["cleanup"] == "not-needed"
    assert "syntheticprivatecredential123" not in str(result)
