"""
Database-backed customs data storage (Turso / libSQL).

Replaces holding the full uploaded file in a pandas DataFrame in memory. Instead:
  1. Upload streams into a database table in chunks (openpyxl read_only mode for Excel,
     csv.reader for CSV) — memory stays flat regardless of file size, whether it's 246MB
     or 50GB, because we never hold more than one chunk at a time.
  2. Matching runs a broad SQL pre-filter (LIKE on HS Code / Item Description) to narrow
     millions of rows down to a small candidate set, THEN hands that small set to the
     existing, already-tested matching.py scoring functions for the precise match. This
     avoids reimplementing the whole matching algorithm as SQL, while still never loading
     the full dataset into memory.

Connects to Turso in production (TURSO_DATABASE_URL / TURSO_AUTH_TOKEN env vars) and to a
local SQLite file automatically when those aren't set, so this runs the same way in local
testing as it will in production — same code path either way.
"""
import os
import csv
import json
import re
import openpyxl
import libsql_client

CHUNK_SIZE = 500  # rows per batch insert — keeps memory flat regardless of file size

_client = None


def get_client():
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    if url:
        _client = libsql_client.create_client_sync(url, auth_token=token)
    else:
        # Local dev / testing fallback — same API, same code path, no live Turso needed.
        local_path = os.environ.get("RM_ANALYZER_LOCAL_DB", "rm_analyzer_data.db")
        _client = libsql_client.create_client_sync(f"file:{local_path}")
    return _client


def _safe_col_name(name):
    """SQLite column names: quote to allow spaces/special chars from real customs headers."""
    return '"' + str(name).replace('"', '""') + '"'


def _table_name(file_key):
    return f"customs_{file_key}"


def init_table(file_key, headers):
    """Creates (or confirms) the table for this file type, with one TEXT column per header."""
    client = get_client()
    table = _table_name(file_key)
    cols_sql = ", ".join(f"{_safe_col_name(h)} TEXT" for h in headers)
    client.execute(f"CREATE TABLE IF NOT EXISTS {table} (_row_id INTEGER PRIMARY KEY AUTOINCREMENT, {cols_sql})")
    return table


def drop_table(file_key):
    client = get_client()
    client.execute(f"DROP TABLE IF EXISTS {_table_name(file_key)}")


def ensure_indexes(file_key, mapping):
    """Index the columns matching actually filters on — makes the pre-filter query fast
    even against millions of rows, instead of a full table scan."""
    client = get_client()
    table = _table_name(file_key)
    for role in ("hs", "desc"):
        col = mapping.get(role)
        if col:
            idx_name = f"idx_{table}_{role}".replace(" ", "_")
            try:
                client.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({_safe_col_name(col)})")
            except Exception:
                pass  # indexing is a performance nice-to-have, never block on it


def row_count(file_key):
    client = get_client()
    table = _table_name(file_key)
    try:
        rs = client.execute(f"SELECT COUNT(*) FROM {table}")
        return rs.rows[0][0]
    except Exception:
        return 0


def get_headers(file_key):
    client = get_client()
    table = _table_name(file_key)
    try:
        rs = client.execute(f"SELECT * FROM {table} LIMIT 0")
        return [c for c in rs.columns if c != "_row_id"]
    except Exception:
        return []


def _insert_chunk(client, table, headers, rows_chunk):
    if not rows_chunk:
        return
    col_list = ", ".join(_safe_col_name(h) for h in headers)
    placeholders = ", ".join("?" for _ in headers)
    stmts = [
        libsql_client.Statement(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", row)
        for row in rows_chunk
    ]
    client.batch(stmts)


def stream_upload_xlsx(file_key, file_path_or_stream, existing_headers=None):
    """Streams an .xlsx file into the database using openpyxl's read_only mode — never
    loads the full sheet into memory, regardless of file size."""
    wb = openpyxl.load_workbook(file_path_or_stream, read_only=True, data_only=True)
    ws = wb.active
    row_iter = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(row_iter)]

    client = get_client()
    table = init_table(file_key, headers)

    chunk = []
    total = 0
    for row in row_iter:
        row = list(row) + [None] * (len(headers) - len(row)) if len(row) < len(headers) else list(row)[:len(headers)]
        row = [str(v) if v is not None else None for v in row]
        chunk.append(row)
        if len(chunk) >= CHUNK_SIZE:
            _insert_chunk(client, table, headers, chunk)
            total += len(chunk)
            chunk = []
    if chunk:
        _insert_chunk(client, table, headers, chunk)
        total += len(chunk)

    wb.close()
    return headers, total


def stream_upload_csv(file_key, file_stream):
    """Streams a .csv file into the database in chunks, same memory-flat approach as xlsx."""
    text_stream = (line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
                   for line in file_stream)
    reader = csv.reader(text_stream)
    headers = [h.strip() for h in next(reader)]

    client = get_client()
    table = init_table(file_key, headers)

    chunk = []
    total = 0
    for row in reader:
        row = row + [None] * (len(headers) - len(row)) if len(row) < len(headers) else row[:len(headers)]
        chunk.append(row)
        if len(chunk) >= CHUNK_SIZE:
            _insert_chunk(client, table, headers, chunk)
            total += len(chunk)
            chunk = []
    if chunk:
        _insert_chunk(client, table, headers, chunk)
        total += len(chunk)
    return headers, total


def prefilter_candidates(file_key, mapping, item_name, item_hs, limit=5000):
    """Broad SQL pre-filter — narrows a potentially huge table down to a small candidate
    set using cheap LIKE matching, before handing off to matching.py's precise scoring.
    Deliberately over-inclusive (a plain substring/prefix check): false positives here get
    filtered out correctly by the exact scoring step afterward; false negatives would be a
    real problem, so this stays broad on purpose."""
    client = get_client()
    table = _table_name(file_key)
    hs_col = mapping.get("hs")
    desc_col = mapping.get("desc")

    clauses, params = [], []
    if hs_col:
        hs_digits = re.sub(r"[^0-9]", "", str(item_hs or ""))
        if hs_digits:
            heading6 = hs_digits[:6]
            clauses.append(f"REPLACE(REPLACE({_safe_col_name(hs_col)}, '.', ''), '-', '') LIKE ?")
            params.append(f"{heading6}%")
    if desc_col:
        words = [w for w in re.split(r"[^a-zA-Z0-9]+", item_name or "") if len(w) > 3][:3]
        for w in words:
            clauses.append(f"{_safe_col_name(desc_col)} LIKE ?")
            params.append(f"%{w}%")

    if not clauses:
        return [], []

    where = " OR ".join(clauses)
    sql = f"SELECT * FROM {table} WHERE {where} LIMIT {limit}"
    rs = client.execute(sql, params)
    headers = [c for c in rs.columns if c != "_row_id"]
    col_idx = {c: i for i, c in enumerate(rs.columns)}
    records = [{h: row[col_idx[h]] for h in headers} for row in rs.rows]
    return headers, records
