"""SQLite persistence for workflows (+ version history) and executions."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

DB_PATH = os.environ.get("FLOWFORGE_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "flowforge.db"))
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, graph TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workflow_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT NOT NULL, version INTEGER NOT NULL,
            graph TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL, UNIQUE(workflow_id, version));
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY, workflow_id TEXT, workflow_version INTEGER, status TEXT, scenario_id TEXT,
            scenario_name TEXT, llm_mode TEXT, duration_ms REAL, trace TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        if c.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] == 0:
            pass  # seeding happens in app startup with the demo graph


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def save_workflow(wf: dict, note: str = "saved") -> dict:
    now = _now()
    with _lock, _conn() as c:
        row = c.execute("SELECT version FROM workflows WHERE id=?", (wf["id"],)).fetchone()
        version = (row["version"] + 1) if row else 1
        graph = json.dumps({k: wf[k] for k in ("nodes", "edges")} | {"name": wf.get("name"),
                                                                    "description": wf.get("description")})
        if row:
            c.execute("UPDATE workflows SET name=?, graph=?, version=?, updated_at=? WHERE id=?",
                      (wf.get("name", "Untitled"), graph, version, now, wf["id"]))
        else:
            c.execute("INSERT INTO workflows VALUES (?,?,?,?,?,?)",
                      (wf["id"], wf.get("name", "Untitled"), graph, version, now, now))
        c.execute("INSERT INTO workflow_versions (workflow_id, version, graph, note, created_at) VALUES (?,?,?,?,?)",
                  (wf["id"], version, graph, note, now))
    return {"id": wf["id"], "version": version, "updated_at": now}


def restore_workflow(wf: dict, note: str = "restored") -> dict:
    """Overwrite the live graph with a known baseline, recording it as a new version."""
    return save_workflow(wf, note=note)


def list_workflows() -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT id, name, version, updated_at FROM workflows ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_workflow(wid: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM workflows WHERE id=?", (wid,)).fetchone()
    if not row:
        return None
    g = json.loads(row["graph"])
    return {"id": row["id"], "name": g.get("name") or row["name"], "description": g.get("description", ""),
            "version": row["version"], "nodes": g["nodes"], "edges": g["edges"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def list_versions(wid: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute("SELECT version, note, created_at FROM workflow_versions WHERE workflow_id=? "
                         "ORDER BY version DESC", (wid,)).fetchall()
    return [dict(r) for r in rows]


def get_version(wid: str, version: int) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM workflow_versions WHERE workflow_id=? AND version=?",
                        (wid, version)).fetchone()
    if not row:
        return None
    g = json.loads(row["graph"])
    return {"id": wid, "name": g.get("name", ""), "description": g.get("description", ""), "version": version,
            "nodes": g["nodes"], "edges": g["edges"]}


def save_execution(trace: dict) -> None:
    sc = trace.get("scenario") or {}
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO executions VALUES (?,?,?,?,?,?,?,?,?,?)", (
            trace["execution_id"], trace.get("workflow_id"), trace.get("workflow_version"), trace.get("status"),
            sc.get("id"), sc.get("name"), trace.get("llm_mode"), trace.get("duration_ms"),
            json.dumps(trace), trace.get("started_at") or _now()))


def list_executions(workflow_id: str | None = None, limit: int = 25) -> list[dict]:
    q = ("SELECT id, workflow_id, workflow_version, status, scenario_id, scenario_name, llm_mode, duration_ms, "
         "created_at FROM executions")
    args: list[Any] = []
    if workflow_id:
        q += " WHERE workflow_id=?"
        args.append(workflow_id)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _lock, _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def get_execution(eid: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT trace FROM executions WHERE id=?", (eid,)).fetchone()
    return json.loads(row["trace"]) if row else None
