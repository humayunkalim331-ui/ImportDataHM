"""
Small persistent key/value store — column mappings, custom items, manual positions,
remarks, HS overrides. Shares the same connection AND lock as db_store.py (Turso when
configured, a local file otherwise) so everything persists together consistently: if
Turso is set up, both the big customs data AND these small settings survive a restart;
if it isn't, both are equally ephemeral, rather than one persisting and the other not.

Uses db_store.execute() (not the raw client) specifically because it's serialized —
without that lock, concurrent access from multiple Streamlit sessions throws
"SQLITE_BUSY: database is locked" against the local-file fallback, which can crash the
request handling it and surface as a connection error to the browser. Reproduced
directly during testing: 20 concurrent calls without the lock failed 13 of them.
"""
import pickle
import base64

import db_store

_TABLE_READY = False


def _ensure_table():
    global _TABLE_READY
    if _TABLE_READY:
        return
    db_store.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")
    _TABLE_READY = True


def get(key, default=None):
    _ensure_table()
    try:
        rs = db_store.execute("SELECT value FROM kv_store WHERE key = ?", [key])
        if not rs.rows:
            return default
        return pickle.loads(base64.b64decode(rs.rows[0][0]))
    except Exception:
        return default


def set(key, value):
    _ensure_table()
    blob = base64.b64encode(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)).decode("ascii")
    db_store.execute(
        "INSERT INTO kv_store (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [key, blob],
    )


def delete(key):
    _ensure_table()
    try:
        db_store.execute("DELETE FROM kv_store WHERE key = ?", [key])
    except Exception:
        pass
