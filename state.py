"""
Session state + persistence glue. Mirrors the original tool's `state` object and its
load/save functions.

Uploaded customs data streams directly into the database (db_store.py — Turso when
configured, a local file otherwise) instead of being held as a full in-memory DataFrame.
Only small metadata (headers, column mapping, upload history, row count) lives in
session_state and kv_store — safe to persist regardless of how large the actual file is,
since it's a few KB either way. This is what makes "upload once, don't lose it on reload"
actually work: the metadata AND the underlying rows both persist through kv_store/db_store,
not just one of them — as long as TURSO_DATABASE_URL / TURSO_AUTH_TOKEN are configured. If
they aren't, both fall back to a local file that's still wiped on a Render restart, exactly
like before — persistence genuinely depends on that Turso setup being done.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import kv_store
import db_store
from items import CATEGORY_KEYS, FILE_TYPES


def _empty_per_category():
    return {k: [] for k in CATEGORY_KEYS}


def init_state():
    if st.session_state.get("_initialized"):
        return
    st.session_state.custom_items = kv_store.get("custom_items", None) or _empty_per_category()
    st.session_state.removed_items = kv_store.get("removed_items", None) or _empty_per_category()
    st.session_state.manual = kv_store.get("manual", {})
    st.session_state.remarks = kv_store.get("remarks", {})
    st.session_state.hs_overrides = kv_store.get("hs_overrides", {})

    # File metadata (small) persists via kv_store; the actual rows live in the database
    # (db_store) and are queried on demand, never loaded in full.
    files = {}
    for ft in FILE_TYPES:
        rec = kv_store.get(f"file_meta:{ft['key']}", None)
        if rec:
            # Reconcile with what's actually in the database — if the DB table is empty
            # (e.g. local-file fallback got wiped by a restart) but metadata says otherwise,
            # trust the database, not stale metadata.
            actual_count = db_store.row_count(ft["key"])
            if actual_count == 0 and rec.get("row_count", 0) > 0:
                rec = None
            elif rec:
                rec["row_count"] = actual_count
        files[ft["key"]] = rec
    st.session_state.files = files

    st.session_state.setdefault("selected", None)
    st.session_state.setdefault("category", CATEGORY_KEYS[0])
    st.session_state.setdefault("period", "all")
    st.session_state.setdefault("period_from", None)
    st.session_state.setdefault("period_to", None)
    st.session_state.setdefault("upload_notice", {"import": None, "export": None, "wits": None})
    st.session_state.setdefault("data_view", {"import": True, "export": True})
    st.session_state.setdefault("show_exporter_tab", False)
    st.session_state.setdefault("show_importer_tab", False)
    st.session_state.setdefault("show_add_form", False)
    st.session_state.setdefault("uploads_expanded", True)
    st.session_state.setdefault("last_insights", {})
    st.session_state._initialized = True


def effective_item(item):
    """Returns a copy of `item` with any saved HS Code override applied."""
    override = st.session_state.hs_overrides.get(item["uid"])
    if override:
        item = {**item, "hs": override}
    return item


def save_hs_override(uid, new_hs):
    st.session_state.hs_overrides[uid] = new_hs
    kv_store.set("hs_overrides", st.session_state.hs_overrides)


def save_manual(uid, qty, price, currency, supplier):
    st.session_state.manual[uid] = {"qty": qty, "price": price, "currency": currency, "supplier": supplier}
    kv_store.set("manual", st.session_state.manual)


def save_remarks(uid, text):
    st.session_state.remarks[uid] = text
    kv_store.set("remarks", st.session_state.remarks)


def add_custom_item(cat, name, hs, origin="", plant="Custom"):
    item = {
        "name": name, "hs": hs, "origin": origin or "—", "plant": plant or "Custom",
        "category": cat, "uid": f"{cat}__custom__{int(datetime.now().timestamp()*1000)}",
    }
    st.session_state.custom_items.setdefault(cat, []).append(item)
    kv_store.set("custom_items", st.session_state.custom_items)
    st.session_state.selected = item["uid"]
    st.session_state.show_add_form = False
    return item


def remove_custom_item(cat, uid):
    st.session_state.custom_items[cat] = [i for i in st.session_state.custom_items.get(cat, []) if i["uid"] != uid]
    kv_store.set("custom_items", st.session_state.custom_items)
    if st.session_state.selected == uid:
        st.session_state.selected = None


def remove_item(cat, uid):
    if "__custom__" in uid:
        remove_custom_item(cat, uid)
        return
    st.session_state.removed_items[cat] = sorted(set(st.session_state.removed_items.get(cat, [])) | {uid})
    kv_store.set("removed_items", st.session_state.removed_items)
    if st.session_state.selected == uid:
        st.session_state.selected = None


def restore_item(cat, uid):
    st.session_state.removed_items[cat] = [u for u in st.session_state.removed_items.get(cat, []) if u != uid]
    kv_store.set("removed_items", st.session_state.removed_items)


# ---------------- File upload / mapping ----------------

def handle_upload(file_key, uploaded_file):
    rec = st.session_state.files.get(file_key) or {"headers": [], "mapping": {}, "uploads": [], "row_count": 0}
    size = uploaded_file.size
    is_dup = any(u["fileName"] == uploaded_file.name and u["size"] == size for u in rec["uploads"])
    if is_dup:
        st.session_state.upload_notice[file_key] = {
            "type": "dup",
            "text": f'"{uploaded_file.name}" is already uploaded — skipped so data isn\'t duplicated. Upload a different file to add more.',
        }
        return

    name = uploaded_file.name
    ext = name.rsplit(".", 1)[-1].lower()
    if ext in ("xlsx", "xls"):
        new_headers, new_count = db_store.stream_upload_xlsx(file_key, uploaded_file)
    else:
        new_headers, new_count = db_store.stream_upload_csv(file_key, uploaded_file)

    rec["headers"] = list(dict.fromkeys([*rec["headers"], *new_headers]))
    rec["uploads"] = [*rec["uploads"], {
        "fileName": name, "size": size,
        "uploadedAt": datetime.now().isoformat(), "rowCount": new_count,
    }]
    rec["row_count"] = db_store.row_count(file_key)
    if rec.get("mapping"):
        db_store.ensure_indexes(file_key, rec["mapping"])

    st.session_state.upload_notice[file_key] = {
        "type": "ok",
        "text": f'Added {new_count:,} rows from "{name}". Total now: {rec["row_count"]:,} rows across {len(rec["uploads"])} upload{"s" if len(rec["uploads"]) != 1 else ""}.',
    }
    save_file(file_key, rec)


def save_file(file_key, rec):
    st.session_state.files[file_key] = rec
    kv_store.set(f"file_meta:{file_key}", rec)
    if rec.get("mapping"):
        db_store.ensure_indexes(file_key, rec["mapping"])


def clear_file_data(file_key):
    st.session_state.files[file_key] = None
    st.session_state.upload_notice[file_key] = None
    kv_store.delete(f"file_meta:{file_key}")
    db_store.drop_table(file_key)
