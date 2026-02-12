from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


_SENSITIVE_MARKERS = ("token", "secret", "password", "key", "authorization")


def _sanitize_value(key: str, value):
    lowered = key.lower()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return "***"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {"msg", "args", "levelname", "levelno"}:
                continue
            if key in {"name", "message", "asctime", "exc_info", "exc_text", "stack_info"}:
                continue
            if key not in payload:
                payload[key] = _sanitize_value(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler])
