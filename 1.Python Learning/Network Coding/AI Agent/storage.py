"""Local evidence and audit persistence. No credentials are stored here."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import uuid


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY, mode TEXT NOT NULL, device TEXT NOT NULL,
                    source TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS evidence_lookup
                    ON evidence(mode, device, observed_at);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, time TEXT NOT NULL, event TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reports (
                    run_id TEXT PRIMARY KEY, completed_at TEXT NOT NULL, payload TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def audit(self, event, **details):
        with self.connect() as db:
            db.execute("INSERT INTO audit(time,event,details) VALUES(?,?,?)",
                       (stamp(), event, json.dumps(details)))

    def save(self, mode, device, source, **payload):
        record = {"id": uuid.uuid4().hex[:12], "mode": mode, "device": device,
                  "source": source, "observed_at": stamp(), **payload}
        with self.connect() as db:
            db.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?)",
                       (record["id"], mode, device, source, record["observed_at"],
                        json.dumps(record)))
        return record

    def save_report(self, report):
        with self.connect() as db:
            db.execute("INSERT INTO reports VALUES(?,?,?)",
                       (report["run_id"], report["completed_at"], json.dumps(report)))

    def history(self, mode, devices, limit=30, source=None):
        if not devices:
            return []
        placeholders = ",".join("?" for _ in devices)
        sql = f"SELECT payload FROM evidence WHERE mode=? AND device IN ({placeholders})"
        args = [mode, *devices]
        if source:
            sql += " AND source=?"
            args.append(source)
        sql += " ORDER BY observed_at DESC, rowid DESC LIMIT ?"
        args.append(limit)
        with self.connect() as db:
            return [json.loads(row["payload"]) for row in db.execute(sql, args)]
