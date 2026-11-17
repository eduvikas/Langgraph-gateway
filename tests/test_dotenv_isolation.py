"""A developer's `.env` must not change test results, and explicit env files must still load."""
from pathlib import Path

from app.envfile import load_env

ROOT = Path(__file__).resolve().parent.parent


def test_implicit_dotenv_is_skipped_when_the_flag_is_set(tmp_path, monkeypatch):
    env = tmp_path / ".env"; env.write_text("ISOLATION_PROBE=leaked\n")
    monkeypatch.delenv("ISOLATION_PROBE", raising=False)
    monkeypatch.setenv("GATEWAY_IGNORE_DOTENV", "1")
    assert load_env(None, default=env) is False
    assert "ISOLATION_PROBE" not in __import__("os").environ


def test_implicit_dotenv_still_loads_without_the_flag(tmp_path, monkeypatch):
    env = tmp_path / ".env"; env.write_text("ISOLATION_PROBE2=loaded\n")
    monkeypatch.delenv("ISOLATION_PROBE2", raising=False)
    monkeypatch.delenv("GATEWAY_IGNORE_DOTENV", raising=False)
    assert load_env(None, default=env) is True
    assert __import__("os").environ["ISOLATION_PROBE2"] == "loaded"
    monkeypatch.delenv("ISOLATION_PROBE2", raising=False)


def test_an_explicit_env_file_loads_even_with_the_flag(tmp_path, monkeypatch):
    env = tmp_path / "explicit.env"; env.write_text("ISOLATION_PROBE3=explicit\n")
    monkeypatch.delenv("ISOLATION_PROBE3", raising=False)
    monkeypatch.setenv("GATEWAY_IGNORE_DOTENV", "1")
    assert load_env(env) is True
    assert __import__("os").environ["ISOLATION_PROBE3"] == "explicit"
    monkeypatch.delenv("ISOLATION_PROBE3", raising=False)


def test_the_app_loads_dotenv_only_through_the_helper():
    for rel in ("app/config.py", "app/economics/pricing.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "from dotenv import" not in src and "load_env()" in src, rel
