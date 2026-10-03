import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.settings import Settings


_STANDARD_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}

_SENSITIVE_LOG_KEY_FRAGMENTS = (
    "api_key",
    "authorization",
    "secret",
    "token",
    "password",
    "payload",
    "provenance",
    "prompt",
)


def _safe_log_value(key: str, value: Any) -> Any:
    normalized = key.lower()
    if any(fragment in normalized for fragment in _SENSITIVE_LOG_KEY_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _safe_log_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_log_value(key, item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """Small stdlib JSON formatter; avoids adding logging infrastructure to the MVP."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOG_RECORD_FIELDS and not key.startswith("_")
        }
        if extras:
            payload["context"] = {
                key: _safe_log_value(key, value) for key, value in extras.items()
            }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root.handlers.clear()
    root.addHandler(handler)
