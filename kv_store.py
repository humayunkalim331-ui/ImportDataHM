"""
Small persistent key/value store — column mappings, custom items, manual positions,
remarks, HS overrides. Shares the same connection as db_store.py (Turso when configured,
a local file otherwise) so everything persists together consistently: if Turso is set up,
both the big customs data AND these small settings survive a restart; if it isn't, both
are equally ephemeral, rather than one persisting and the other silently not.
"""
import pickle
import base64

import db_store

_TABLE_READY = False


def _ensure_table():
    global _TABLE_READY
    if _TABLE_READY:
        return
    client = db_store.get_client()
    client.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")
    _TABLE_READY = True


def get(key, default=None):
    _ensure_table()
    client = db_store.get_client()
    try:
        rs = client.execute("SELECT value FROM kv_store WHERE key = ?", [key])
        if not rs.rows:
            return default
        return pickle.loads(base64.b64decode(rs.rows[0][0]))
    except Exception:
        return default


def set(key, value):
    _ensure_table()
    client = db_store.get_client()
    blob = base64.b64encode(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)).decode("ascii")
    client.execute(
        "INSERT INTO kv_store (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [key, blob],
    )


def delete(key):
    _ensure_table()
    client = db_store.get_client()
    try:
        client.execute("DELETE FROM kv_store WHERE key = ?", [key])
    except Exception:
        pass
