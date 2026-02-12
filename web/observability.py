from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from fastapi import Request, Response


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


def request_logger() -> Callable[[Request, Callable[[Request], Response]], Response]:
    logger = logging.getLogger("anibot.web")

    async def middleware(request: Request, call_next: Callable[[Request], Response]) -> Response:
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000
            logger.exception(
                "request.error",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            raise
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "request.completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    return middleware
