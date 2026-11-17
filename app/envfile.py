"""One place that loads `.env`, so tests and demos can opt out of picking up a developer's private configuration.

Setting GATEWAY_IGNORE_DOTENV=1 skips the *implicit* `.env` search. An explicit path (such as `--env-file`) is always loaded.
"""
import os


def load_env(path=None, default=None):
    from dotenv import load_dotenv
    if path is not None:
        return load_dotenv(path, override=False)
    if os.getenv("GATEWAY_IGNORE_DOTENV", "").strip() == "1":
        return False
    return load_dotenv(default, override=False) if default else load_dotenv()
