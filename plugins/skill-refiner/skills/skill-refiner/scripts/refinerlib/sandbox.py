import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .common import RefinerError, redact, relative_path, secret_values
from .snapshot import inventory

DEFAULT_IMAGE = "python@sha256:f85c5697265c178cc6887276c55fe16cf3d14ca35c3df6a5eab3b360534a55d2"


@dataclass(frozen=True)
class SandboxConfig:
    image: str = DEFAULT_IMAGE
    cpus: float = 1
    memory_mib: int = 512
    pids: int = 64
    timeout: float = 30
    output_bytes: int = 1048576

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[0-9a-f]{64}", self.image):
            raise RefinerError("A digest-pinned image is required")
        if not (0 < self.cpus <= 16 and 32 <= self.memory_mib <= 8192 and 1 <= self.pids <= 512 and 0 < self.timeout <= 300 and 1 <= self.output_bytes <= 10485760):
            raise RefinerError("Sandbox limits are outside supported bounds")


def command_for(staging, script, args, config, name):
    script = relative_path(script)
    if Path(script).suffix not in (".py", ".sh"):
        raise RefinerError("Only Python and Bash scripts can execute")
    staging = Path(staging).absolute()
    if any(c in str(staging) for c in (",", "\n", "\r")):
        raise RefinerError("Unsupported mount path")
    if not re.fullmatch(r"refiner-[a-zA-Z0-9-]+", name):
        raise RefinerError("Invalid owned container name")
    command = ["docker", "run", "--rm", "--name", name, "--pull=never", "--read-only", "--network=none",
               "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534",
               f"--cpus={config.cpus:g}", f"--memory={config.memory_mib}m", f"--memory-swap={config.memory_mib}m",
               f"--pids-limit={config.pids}", "--ulimit=nofile=256:256", "--ulimit=core=0",
               "--tmpfs=/work:rw,nosuid,nodev,size=128m,mode=1777", "--tmpfs=/tmp:rw,nosuid,nodev,size=64m,mode=1777",
               "--workdir=/work", "--mount", f"type=bind,source={staging},target=/input,readonly",
               "--entrypoint", "python" if script.endswith(".py") else "bash", config.image]
    if script.endswith(".py"):
        # Entry point is overridden; executable is therefore not a target-controlled image command.
        command.extend(["-I", f"/input/{script}"])
    else:
        command.extend(["--noprofile", "--norc", f"/input/{script}"])
    return command + [str(arg) for arg in args]


def _capture(command, timeout, cap):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    chunks = bytearray()
    exceeded = threading.Event()

    def reader():
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            available = cap - len(chunks)
            chunks.extend(chunk[:max(0, available)])
            if len(chunk) > available:
                exceeded.set()
                process.kill()
                break

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    timed_out = False
    while process.poll() is None:
        if time.monotonic() > deadline:
            timed_out = True
            process.kill()
            break
        time.sleep(0.02)
    process.wait(timeout=5)
    thread.join(timeout=2)
    process.stdout.close()
    return process.returncode, bytes(chunks), timed_out, exceeded.is_set()


def run_test(source, script, args=(), config=None):
    config = config or SandboxConfig()
    snapshot = inventory(source)
    script = relative_path(script)
    if script not in snapshot.files:
        raise RefinerError("Script is not in the validated snapshot")
    # Validate all arguments before touching Docker.
    name = "refiner-" + uuid.uuid4().hex
    command_for(snapshot.root, script, args, config, name)
    detected = [value for raw in snapshot.files.values() for value in secret_values(raw.decode("utf-8", errors="replace"))]
    detected.extend(value for path in snapshot.files for value in secret_values(path))
    detected.extend(value for arg in args for value in secret_values(str(arg)))
    if detected:
        return {"status": "blocked", "reason": "Detected credentials in inputs: remove them in an approved test copy before execution", "cleanup": "not-needed"}
    if not shutil.which("docker"):
        return {"status": "blocked", "reason": "Docker is unavailable", "cleanup": "not-needed"}
    if os.environ.get("DOCKER_HOST", "").startswith(("tcp:", "ssh:", "http:")):
        return {"status": "blocked", "reason": "Only a local Docker engine is allowed", "cleanup": "not-needed"}
    try:
        endpoint = subprocess.run(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], capture_output=True, timeout=10, shell=False)
        if endpoint.returncode or not endpoint.stdout.decode().strip().startswith(("npipe:", "unix:")):
            return {"status": "blocked", "reason": "Local Docker context could not be verified", "cleanup": "not-needed"}
        engine = subprocess.run(["docker", "version", "--format", "{{.Server.Os}}"], capture_output=True, timeout=10, shell=False)
        if engine.returncode or engine.stdout.strip() != b"linux":
            return {"status": "blocked", "reason": "Docker Linux engine is inaccessible", "cleanup": "not-needed"}
        image = subprocess.run(["docker", "image", "inspect", config.image], capture_output=True, timeout=10, shell=False)
        if image.returncode:
            return {"status": "blocked", "reason": "Pinned image is not installed; trusted setup must install it explicitly", "cleanup": "not-needed"}
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "blocked", "reason": "Docker preflight failed", "cleanup": "not-needed"}
    secrets = []
    for data in snapshot.files.values():
        secrets.extend(secret_values(data.decode("utf-8", errors="replace")))
    for path in snapshot.files:
        secrets.extend(secret_values(path))
    with tempfile.TemporaryDirectory(prefix="refiner-sandbox-") as temporary:
        stage = Path(temporary)
        for path, data in snapshot.files.items():
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for directory in [stage, *[p for p in stage.rglob("*") if p.is_dir()]]:
            directory.chmod(0o755)
        for file in [p for p in stage.rglob("*") if p.is_file()]:
            file.chmod(0o644)
        result = {"status": "blocked", "reason": "Docker execution failed"}
        try:
            code, data, timed_out, exceeded = _capture(command_for(stage, script, args, config, name), config.timeout, config.output_bytes)
            result = {"status": "passed" if code == 0 and not timed_out and not exceeded else "failed",
                      "returncode": code, "timed_out": timed_out, "output_limited": exceeded,
                      "output": redact(data.decode("utf-8", errors="replace"), secrets), "image": config.image,
                      "source_digest": snapshot.digest}
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            try:
                # Removes only this run's UUID-named container; no enumeration or broad cleanup.
                removed = subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10, shell=False)
                gone = subprocess.run(["docker", "container", "inspect", name], capture_output=True, timeout=10, shell=False)
                result["cleanup"] = "confirmed" if gone.returncode == 1 and (removed.returncode == 0 or b"No such container" in removed.stderr) else "unverified"
            except (OSError, subprocess.TimeoutExpired):
                result["cleanup"] = "unverified"
        if result["cleanup"] != "confirmed" and result["status"] == "passed":
            result["status"] = "failed"
            result["reason"] = "Container cleanup could not be confirmed"
        if inventory(source).digest != snapshot.digest:
            raise RefinerError("Input changed during sandbox execution")
        return result
