"""The acceptance script is the evidence behind 'an existing application can adopt this gateway', so it is itself tested:
it must ACCEPT a healthy gateway and must refuse one whose policy has been weakened. Each test starts a real server."""
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_against_gateway(tmp_path, gateway_env=None, script_args=()):
    import os
    port = free_port()
    env = {**os.environ, "GATEWAY_IGNORE_DOTENV": "1", "DATABASE_URL": f"sqlite:///{(tmp_path / 'g.db').as_posix()}",
           "MOCK_PROVIDER_ENABLED": "true", **(gateway_env or {})}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1); break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.fail("gateway did not start")
        done = subprocess.run([sys.executable, "scripts/acceptance_check.py", "--url", f"http://127.0.0.1:{port}",
                               "--expect-provider", "mock", *script_args], cwd=ROOT, capture_output=True, text=True, timeout=240)
        return done.returncode, done.stdout
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def test_a_healthy_gateway_is_accepted(tmp_path):
    code, out = run_against_gateway(tmp_path)
    assert code == 0 and "ACCEPTED" in out and "NOT ACCEPTED" not in out and "[FAIL]" not in out, out[-2500:]
    assert "D1 gateway ledger matches" in out and "C2 a secret in the prompt is blocked" in out


@pytest.mark.parametrize("weakening,failing_check", [({"BLOCK_SECRETS": "false"}, "C2"),
                                                     ({"BLOCK_PROMPT_INJECTION": "false"}, "C3"),
                                                     ({"CACHE_ENABLED": "false"}, "B3")])
def test_a_weakened_gateway_is_not_accepted(tmp_path, weakening, failing_check):
    code, out = run_against_gateway(tmp_path, weakening)
    assert code == 1 and "NOT ACCEPTED" in out and f"[FAIL] {failing_check}" in out, out[-2500:]
