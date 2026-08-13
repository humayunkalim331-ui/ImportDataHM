"""
Session state + persistence glue. Mirrors the original tool's `state` object and its
load/save functions, backed by kv_store instead of window.storage/IndexedDB.

Important difference from the original: the original persisted to the browser's local
storage, so each person's uploads/custom items were private to their own browser. This
app persists to a shared server-side store (kv_store), so uploaded customs data, custom
items, and manual positions are shared across everyone who uses this deployment — which
suits a small team all reviewing the same procurement data, but is worth knowing about.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import kv_store
from items import CATEGORY_KEYS, FILE_TYPES


def _empty_per_category():
    return {k: [] for k in CATEGORY_KEYS}


def init_state():
    if st.session_state.get("_initialized"):
        return
    st.session_state.custom_items = kv_store.get("custom_items", None) or _empty_per_category()
    st.session_state.removed_items = kv_store.get("removed_items", None) or _empty_per_category()
    st.session_state.manual = kv_store.get("manual", {})
    st.session_state.hs_overrides = kv_store.get("hs_overrides", {})

    files = {}
    for ft in FILE_TYPES:
        files[ft["key"]] = kv_store.get(f"file:{ft['key']}", None)
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

def _read_excel_fast(uploaded_file):
    # openpyxl (pandas' default .xlsx engine) is pure-Python and can take minutes on large
    # files, especially on CPU-limited hosting. python-calamine is a Rust-based reader that's
    # typically 10-20x faster; fall back to openpyxl only if it isn't installed or fails.
    try:
        return pd.read_excel(uploaded_file, dtype=object, engine="calamine")
    except Exception:
        uploaded_file.seek(0)
        return pd.read_excel(uploaded_file, dtype=object)


def _read_upload(uploaded_file):
    name = uploaded_file.name
    ext = name.rsplit(".", 1)[-1].lower()
    if ext in ("xlsx", "xls"):
        df = _read_excel_fast(uploaded_file)
    else:
        try:
            df = pd.read_csv(uploaded_file, dtype=object, encoding="utf-8")
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, dtype=object, encoding="latin-1")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def handle_upload(file_key, uploaded_file):
    rec = st.session_state.files.get(file_key) or {"headers": [], "rows": pd.DataFrame(), "mapping": {}, "uploads": []}
    size = uploaded_file.size
    is_dup = any(u["fileName"] == uploaded_file.name and u["size"] == size for u in rec["uploads"])
    if is_dup:
        st.session_state.upload_notice[file_key] = {
            "type": "dup",
            "text": f'"{uploaded_file.name}" is already uploaded — skipped so data isn\'t duplicated. Upload a different file to add more.',
        }
        return

    new_df = _read_upload(uploaded_file)
    new_headers = list(new_df.columns)
    rec["headers"] = list(dict.fromkeys([*rec["headers"], *new_headers]))
    rec["rows"] = pd.concat([rec["rows"], new_df], ignore_index=True, sort=False) if len(rec["rows"]) else new_df
    rec["uploads"] = [*rec["uploads"], {
        "fileName": uploaded_file.name, "size": size,
        "uploadedAt": datetime.now().isoformat(), "rowCount": len(new_df),
    }]
    st.session_state.upload_notice[file_key] = {
        "type": "ok",
        "text": f'Added {len(new_df):,} rows from "{uploaded_file.name}". Total now: {len(rec["rows"]):,} rows across {len(rec["uploads"])} upload{"s" if len(rec["uploads"]) != 1 else ""}.',
    }
    save_file(file_key, rec)


def save_file(file_key, rec):
    st.session_state.files[file_key] = rec
    kv_store.set(f"file:{file_key}", rec)


def clear_file_data(file_key):
    st.session_state.files[file_key] = None
    st.session_state.upload_notice[file_key] = None
    kv_store.delete(f"file:{file_key}")
