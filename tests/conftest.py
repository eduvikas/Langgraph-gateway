"""Tests must never depend on the machine they run on.

Two things can leak configuration into a test run, and both are closed here, before any test module imports the app:

1. A developer's private `.env` (it may hold a real API key, real model IDs, a different application allowlist...).
   `GATEWAY_IGNORE_DOTENV=1` makes the implicit `.env` search a no-op.
2. Real process environment variables. `Settings` and the pricing table read `os.getenv` when their modules are
   imported, so an exported `ALLOWED_APPLICATIONS`, `MODEL_PROFILES_JSON`, `BASELINE_MODEL`, `DEFAULT_DAILY_BUDGET_USD`...
   (from a shell profile, a CI secret store or a container) silently changes test outcomes even with (1) in place.
   Every variable the configuration modules read is removed here. The names are read from the source, so a variable
   added to `app/config.py` later is covered without anyone remembering to update a list.

Tests that need a particular configuration state it explicitly (see `tests/support.py`) instead of inheriting it.
"""
import os
import re
from pathlib import Path

os.environ["GATEWAY_IGNORE_DOTENV"] = "1"

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_SOURCES = ("app/config.py", "app/economics/pricing.py")
_GETENV = re.compile(r"""os\.getenv\(\s*['"]([A-Z][A-Z0-9_]*)['"]""")


def configuration_env_vars() -> set[str]:
    names: set[str] = set()
    for rel in _CONFIG_SOURCES:
        names |= set(_GETENV.findall((_ROOT / rel).read_text(encoding="utf-8")))
    return names


for _name in configuration_env_vars():
    os.environ.pop(_name, None)
