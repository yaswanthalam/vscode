"""Append-only audit trail: who asked what, what ran where, and the verdicts.

Ship audit.jsonl to Kusto (e.g. via Azure Monitor Agent) so the agent's own
activity is queryable like any other log.
"""
import json
import threading
from datetime import datetime, timezone

from .settings import AUDIT_LOG

_lock = threading.Lock()


def record(user: str, action: str, **fields) -> None:
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "user": user, "action": action, **fields}
    line = json.dumps(entry, default=str)
    with _lock:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def tail(limit: int = 100) -> list[dict]:
    if not AUDIT_LOG.exists():
        return []
    with open(AUDIT_LOG, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    return [json.loads(l) for l in reversed(lines) if l.strip()]
