"""Durable PRU sessions with a bounded, single-writer SQLite queue.

Only committed rows contribute to the counters. A storage/queue failure is
latched for the entire session; accepted rows are drained before close returns.
"""
from __future__ import annotations

import asyncio
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import sqlite3
import threading
import time


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


_METRICS = ("vrect_mv", "irect_ma", "vout_mv", "iout_ma", "temperature_c",
            "vrect_min_mv", "vrect_set_mv", "vrect_high_mv", "pru_alert", "tester_cmd")
_OPTIONAL = {"vout_mv": 0x80, "iout_ma": 0x40, "temperature_c": 0x20,
             "vrect_min_mv": 0x10, "vrect_set_mv": 0x08, "vrect_high_mv": 0x04}
_COLUMNS = ("record_type", "at", "monotonic", "raw_hex", "validity", "valid",
            "error", "title", "detail", "kind", "level", *_METRICS, "data_json")


class SessionRecorder:
    """One immutable session destination, opened exclusively (never overwritten)."""

    def __init__(self, path, metadata=None, *, queue_capacity=4096, batch_size=128):
        if queue_capacity < 1 or batch_size < 1:
            raise ValueError("queue_capacity and batch_size must be positive")
        self.path = Path(path).expanduser().resolve()
        self.started_at = timestamp()
        self.metadata = dict(metadata or {})
        self.metadata.update(schema_version=1, started_at=self.started_at,
                             timestamp_timezone="UTC", monotonic_unit="seconds")
        # Exclusive creation is also an atomic guard against two simultaneous starts.
        with self.path.open("xb"):
            pass
        self.queue_capacity = queue_capacity
        self._batch_size = min(batch_size, queue_capacity)
        self._queue = queue.Queue(maxsize=queue_capacity)
        self._state = threading.Condition()
        self._pending = self._samples = self._events = self._dropped = 0
        self._accepted = self._settled = 0
        self._error = ""
        self._accepting = True
        self._closing = threading.Event()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="pru-session-writer", daemon=False)
        self._thread.start()
        self._ready.wait()
        if self.error:
            self._closing.set()
            self._thread.join()
            raise RuntimeError(self.error)

    @classmethod
    async def create(cls, path, metadata=None, **kwargs):
        creating = asyncio.create_task(asyncio.to_thread(cls, path, metadata, **kwargs))
        try:
            return await asyncio.shield(creating)
        except asyncio.CancelledError:
            # A thread cannot be cancelled: retrieve and close its writer explicitly.
            recorder = await creating
            await recorder.close()
            raise

    @property
    def sample_count(self):
        with self._state:
            return self._samples

    @property
    def event_count(self):
        with self._state:
            return self._events

    @property
    def pending_count(self):
        with self._state:
            return self._pending

    @property
    def dropped_count(self):
        with self._state:
            return self._dropped

    @property
    def error(self):
        with self._state:
            return self._error

    def _fail(self, exc):
        with self._state:
            if not self._error:
                self._error = str(exc) or type(exc).__name__
            self._state.notify_all()

    def _enqueue(self, record_type, *, raw=None, at=None, monotonic=None, **values):
        row = {name: None for name in _COLUMNS}
        row.update(record_type=record_type, at=at or timestamp(),
                   monotonic=time.monotonic() if monotonic is None else monotonic,
                   raw_hex=bytes(raw).hex(" ").upper() if raw is not None else "")
        row.update(values)
        with self._state:
            if not self._accepting:
                raise RuntimeError("Recording session is closed")
            if self._error:
                self._dropped += 1
                return False
            # Include the worker's in-flight batch in the bound, not just Queue.qsize().
            if self._pending >= self.queue_capacity:
                self._error = f"Recording queue full ({self.queue_capacity}); data was not saved"
                self._dropped += 1
                self._state.notify_all()
                return False
            self._pending += 1
            self._accepted += 1
            self._queue.put_nowait(row)
        return True

    def record_sample(self, info=None, *, raw=None, error="", **timing):
        validity = info.optional_fields_validity if info else (raw[0] if raw else None)
        values = {name: getattr(info, name) if info else None for name in _METRICS}
        for name, mask in _OPTIONAL.items():
            if validity is None or not validity & mask:
                values[name] = None
        return self._enqueue("dynamic", raw=raw if raw is not None else (info.raw if info else None),
                             validity=validity, valid=int(bool(info and info.valid)),
                             error=error, **values, **timing)

    def record_static(self, info=None, *, raw=None, error="", **timing):
        data = asdict(info) if info else {}
        data.pop("raw", None)
        validity = info.optional_fields_validity if info else (raw[0] if raw else None)
        if validity is None or not validity & 1:
            data["delta_r1_ohm"] = None
        return self._enqueue("static", raw=raw if raw is not None else (info.raw if info else None),
                             validity=validity, valid=int(bool(info and info.valid)), error=error,
                             data_json=json.dumps(data, ensure_ascii=False), **timing)

    def record_event(self, title, detail="", *, kind="link", level="info", raw=None,
                     data=None, **timing):
        return self._enqueue("event", title=title, detail=detail, kind=kind, level=level,
                             raw=raw, data_json=json.dumps(data or {}, ensure_ascii=False), **timing)

    def _write_batch(self, connection, batch):
        placeholders = ",".join("?" for _ in _COLUMNS)
        with connection:
            connection.executemany(
                f"INSERT INTO records ({','.join(_COLUMNS)}) VALUES ({placeholders})",
                [tuple(row[column] for column in _COLUMNS) for row in batch])

    def _worker(self):
        connection = None
        write_failed = False
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            metric_columns = ",".join(f"{name} INTEGER" for name in _METRICS)
            connection.executescript(f"""
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE records (
                    id INTEGER PRIMARY KEY, record_type TEXT NOT NULL,
                    at TEXT NOT NULL, monotonic REAL NOT NULL, raw_hex TEXT,
                    validity INTEGER, valid INTEGER, error TEXT,
                    title TEXT, detail TEXT, kind TEXT, level TEXT,
                    {metric_columns}, data_json TEXT
                );
                CREATE INDEX event_kind ON records(record_type, kind, id);
            """)
            with connection:
                connection.executemany("INSERT INTO metadata VALUES (?,?)", [
                    (key, json.dumps(value, ensure_ascii=False)) for key, value in self.metadata.items()])
            self._ready.set()
            while not self._closing.is_set() or not self._queue.empty():
                try:
                    first = self._queue.get(timeout=.1)
                except queue.Empty:
                    continue
                batch = [first]
                # A small batch window saves fsyncs without delaying UI or BLE operations.
                deadline = time.monotonic() + .05
                while len(batch) < self._batch_size:
                    try:
                        batch.append(self._queue.get(timeout=max(0, deadline - time.monotonic())))
                    except queue.Empty:
                        break
                committed = False
                if not write_failed:
                    try:
                        self._write_batch(connection, batch)
                        committed = True
                    except Exception as exc:
                        write_failed = True
                        self._fail(exc)
                with self._state:
                    if committed:
                        self._samples += sum(row["record_type"] == "dynamic" and row["valid"] == 1 for row in batch)
                        self._events += sum(row["record_type"] == "event" for row in batch)
                    else:
                        self._dropped += len(batch)
                    self._pending -= len(batch)
                    self._settled += len(batch)
                    self._state.notify_all()
                for _ in batch:
                    self._queue.task_done()
            if not write_failed:
                with connection:
                    connection.executemany("INSERT OR REPLACE INTO metadata VALUES (?,?)", [
                        ("ended_at", json.dumps(timestamp())), ("error", json.dumps(self.error)),
                        ("dropped_count", json.dumps(self.dropped_count))])
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as exc:
            self._fail(exc)
            # Initialization/finalization failures must not strand close/flush callers.
            with self._state:
                self._dropped += self._pending
                self._settled += self._pending
                self._pending = 0
                self._state.notify_all()
        finally:
            if connection is not None:
                connection.close()
            self._ready.set()
            self._closed.set()

    def _wait_flushed(self):
        with self._state:
            target = self._accepted
            while self._settled < target and not self._closed.is_set():
                self._state.wait(.1)
            if self._error:
                raise RuntimeError(self._error)

    async def flush(self):
        await asyncio.to_thread(self._wait_flushed)

    async def close(self):
        with self._state:
            self._accepting = False
            self._closing.set()
        # Joining in a worker keeps the Qt/asyncio event loop responsive during fsync.
        # Shield the join so cancellation cannot leave an abandoned writer behind.
        joining = asyncio.create_task(asyncio.to_thread(self._thread.join))
        try:
            await asyncio.shield(joining)
        except asyncio.CancelledError:
            await joining
            raise
        if self.error:
            raise RuntimeError(self.error)

    def _reader(self):
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=1)
        connection.row_factory = sqlite3.Row
        return connection

    def query_events(self, query="", kind="", limit=200, offset=0):
        clauses, params = ["record_type='event'"], []
        if query:
            clauses.append("(instr(lower(title), lower(?)) OR instr(lower(detail), lower(?)) OR instr(lower(raw_hex), lower(?)))")
            params.extend([query] * 3)
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        where = " AND ".join(clauses)
        connection = self._reader()
        try:
            # A single read transaction keeps count and page consistent while writing.
            connection.execute("BEGIN")
            count = connection.execute(f"SELECT count(*) FROM records WHERE {where}", params).fetchone()[0]
            rows = connection.execute(f"SELECT * FROM records WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                                      [*params, min(1000, max(1, int(limit))), max(0, int(offset))]).fetchall()
            return [dict(row) for row in rows], count
        finally:
            connection.close()

    @staticmethod
    def _csv_safe(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    def _export_csv(self, destination):
        destination = Path(destination).expanduser().resolve()
        connection = self._reader()
        created = False
        try:
            connection.execute("BEGIN")
            with destination.open("x", encoding="utf-8-sig", newline="") as stream:
                created = True
                writer = csv.writer(stream)
                columns = ("id", *_COLUMNS)
                writer.writerow(columns)
                metadata = {row["key"]: json.loads(row["value"]) for row in connection.execute("SELECT * FROM metadata")}
                metadata_row = {"record_type": "metadata", "at": self.started_at,
                                "data_json": json.dumps(metadata, ensure_ascii=False)}
                writer.writerow([self._csv_safe(metadata_row.get(column, "")) for column in columns])
                for row in connection.execute("SELECT * FROM records ORDER BY id"):
                    writer.writerow([self._csv_safe(row[column]) for column in columns])
            return destination
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
        finally:
            connection.close()

    async def export_csv(self, destination):
        await self.flush()
        return await asyncio.to_thread(self._export_csv, destination)
