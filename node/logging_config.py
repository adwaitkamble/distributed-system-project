"""Structured JSON logging for experiment-metric extraction.

Every log line emitted via the returned logger is a single JSON object:
{
  "ts": "2026-10-03T01:15:22.341+05:30",
  "level": "INFO",
  "node_id": 3,
  "lamport_ts": 47,
  "event": "VOTE_ACCEPTED",
  "election_term": 2,
  "correlation_id": "voter42:3:47",
  "data": { ... }
}

The experiment runner (Phase 7) parses these from Docker container logs.
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Formats a LogRecord as a single-line JSON object."""

    def __init__(self, node_id: int = 0) -> None:
        super().__init__()
        self.node_id = node_id

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "node_id": self.node_id,
            "lamport_ts": getattr(record, "lamport_ts", 0),
            "event": getattr(record, "event", "LOG"),
            "election_term": getattr(record, "election_term", 0),
            "correlation_id": getattr(record, "correlation_id", ""),
        }
        data = getattr(record, "data", None)
        if data:
            log_obj["data"] = data

        # Keep the human-readable message when it differs from event
        msg = record.getMessage()
        if msg and msg != log_obj["event"]:
            log_obj["msg"] = msg

        return json.dumps(log_obj, default=str)


def setup_logging(node_id: int, level: str = "INFO") -> logging.Logger:
    """Create and return a logger that emits structured JSON to stdout."""
    logger = logging.getLogger(f"node.{node_id}")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    # Avoid duplicate handlers on re-init
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter(node_id=node_id))
        logger.addHandler(handler)

    return logger


def log_event(
    logger: logging.Logger,
    event: str,
    lamport_ts: int = 0,
    election_term: int = 0,
    correlation_id: str = "",
    level: int = logging.INFO,
    **data: Any,
) -> None:
    """Convenience helper: emit a structured event log line.

    Usage:
        log_event(logger, "VOTE_ACCEPTED", lamport_ts=47,
                  correlation_id=vote_id, client_id="voter42", choice="Alice")
    """
    logger.log(
        level,
        event,
        extra={
            "event": event,
            "lamport_ts": lamport_ts,
            "election_term": election_term,
            "correlation_id": correlation_id,
            "data": data if data else {},
        },
    )
