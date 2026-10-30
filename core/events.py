"""Thread-safe local observability sinks."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentEvent:
    run_id: str
    type: str
    source: str
    data: dict[str, Any]
    timestamp: str

    @classmethod
    def create(cls, run_id: str, event_type: str, source: str, **data: Any) -> "AgentEvent":
        return cls(run_id, event_type, source, data, datetime.now(timezone.utc).isoformat())


class EventSink(Protocol):
    def emit(self, event: AgentEvent) -> None: ...


class NullEventSink:
    def emit(self, event: AgentEvent) -> None:
        return None


class ConsoleEventSink:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._lock = threading.Lock()

    def emit(self, event: AgentEvent) -> None:
        if not self.verbose and event.type.startswith(("tool.", "agent.message")):
            return
        details = " ".join(f"{key}={value}" for key, value in event.data.items())
        stamp = event.timestamp[11:19]
        with self._lock:
            print(f"[{stamp}] [{event.source}] {event.type} {details}".rstrip(), flush=True)


class SQLiteEventSink:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL, timestamp TEXT NOT NULL,
                type TEXT NOT NULL, source TEXT NOT NULL, data TEXT NOT NULL)"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def emit(self, event: AgentEvent) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO events(run_id,timestamp,type,source,data) VALUES(?,?,?,?,?)",
                (event.run_id, event.timestamp, event.type, event.source,
                 json.dumps(event.data, ensure_ascii=False, default=str)),
            )

    def read(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT sequence,timestamp,type,source,data FROM events WHERE run_id=? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return [
            {"sequence": row[0], "timestamp": row[1], "type": row[2],
             "source": row[3], "data": json.loads(row[4])}
            for row in rows
        ]


class CompositeEventSink:
    def __init__(self, *sinks: EventSink):
        self.sinks = sinks

    def emit(self, event: AgentEvent) -> None:
        for sink in self.sinks:
            sink.emit(event)


def emit(sink: EventSink, run_id: str, event_type: str, source: str, **data: Any) -> None:
    sink.emit(AgentEvent.create(run_id, event_type, source, **data))
