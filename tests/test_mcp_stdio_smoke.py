"""Integration: launch the real stdio MCP server and call every tool through the MCP client SDK."""
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
ROOT = Path(__file__).resolve().parent.parent


def test_logging_stream_can_be_redirected_to_stderr(monkeypatch, capsys):
    import logging
    from app.observability.logging import configure_logging
    monkeypatch.setenv("LOG_STREAM", "stderr")
    configure_logging("INFO")
    logging.getLogger("t").info("hello")
    out = capsys.readouterr()
    assert "hello" in out.err and out.out == ""
    monkeypatch.delenv("LOG_STREAM"); configure_logging("INFO")


def test_stdio_server_smoke(tmp_path):
    proc = subprocess.run([sys.executable, "scripts/mcp_smoke_test.py", "--mode", "all", "--db", str(tmp_path / "smoke.db")],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1500:]
    assert "FAIL" not in proc.stdout
    assert "Field required" not in proc.stderr          # no non-JSON-RPC bytes on stdout
