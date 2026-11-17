import json
import logging
import os
import sys
from datetime import datetime, timezone

class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        allowed_extra = ("request_id", "method", "path", "status_code", "duration_ms", "provider", "model", "event")
        for key in allowed_extra:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info and record.exc_info[0]:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)

def configure_logging(level: str = "INFO", stream=None):
    """Structured JSON logs. stdout by default; LOG_STREAM=stderr moves them to stderr.

    The stdio MCP server must keep stdout exclusively for JSON-RPC frames, so app.mcp_server
    sets LOG_STREAM=stderr before importing the gateway.
    """
    if stream is None:
        stream = sys.stderr if os.getenv("LOG_STREAM", "stdout").strip().lower() == "stderr" else sys.stdout
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())

def get_logger(name: str):
    return logging.getLogger(name)
