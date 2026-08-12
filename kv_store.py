"""
Small persistent key/value store backed by SQLite, mirroring the role the original
HTML tool's `storageBackend` (window.storage / IndexedDB / localStorage) played:
save uploaded customs data, column mappings, manual positions, custom items, etc.
so they survive a page reload.

Render note: a Render web service's local disk is ephemeral across deploys/restarts
unless you attach a persistent disk. For real persistence in production, mount a
Render Disk at DATA_DIR (or point DB_PATH at it) — otherwise data uploaded between
deploys will be lost, same as it would with any other local-file approach.
"""
import os
import pickle
import sqlite3
import threading

DATA_DIR = os.environ.get("RM_ANALYZER_DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "rm_analyzer.sqlite3")

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB)")
    return conn


_conn = _connect()


def get(key, default=None):
    with _lock:
        cur = _conn.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = cur.fetchone()
    if row is None:
        return default
    try:
        return pickle.loads(row[0])
    except Exception:
        return default


def set(key, value):
    blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    with _lock:
        _conn.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, blob))
        _conn.commit()


def delete(key):
    with _lock:
        _conn.execute("DELETE FROM kv WHERE key = ?", (key,))
        _conn.commit()
