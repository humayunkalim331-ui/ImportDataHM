"""
Item ↔ customs-row matching: HS Code matching, description/word matching, date parsing,
period filtering, and company-name normalization. A direct port of the matching helpers
from the original HTML/JS tool, vectorized with pandas where the original looped per-row.
"""
import re
import numpy as np
import pandas as pd

DESC_MATCH_THRESHOLD = 0.999

LEGAL_SUFFIX_WORDS = {
    "LIMITED", "LTD", "LLC", "INC", "CORPORATION", "CORP", "CO", "COMPANY", "PLC", "GMBH", "SRL", "FZCO",
    "GROUP", "PVT", "PRIVATE", "PUBLIC", "SA", "NV", "BV", "AG",
}

# Words too generic to anchor a description match on their own (see desc_score_series).
GENERIC_MATCH_WORDS = {
    "grade", "resin", "film", "chip", "chips", "type", "additive", "additives", "compound", "compounds",
    "material", "materials", "raw", "product", "products", "industrial", "technical", "powder", "granule",
    "granules", "pellet", "pellets", "synthetic", "polymer", "chemical", "chemicals", "general", "plastic", "plastics",
}

_alnum_re = re.compile(r"[^a-z0-9]", re.IGNORECASE)
_word_re = re.compile(r"[^a-z0-9\s]", re.IGNORECASE)
_gd_date_re = re.compile(r"(\d{2})-(\d{2})-(\d{4})")
_slash_date_re = re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})")


def compact(s):
    return _alnum_re.sub("", str(s or "")).lower()


def norm_words(s):
    cleaned = _word_re.sub(" ", str(s or "")).lower()
    return [w for w in cleaned.split() if len(w) > 2]


# ---------------- HS Code matching ----------------

def normalize_hs(code, precision):
    digits = re.sub(r"[^0-9]", "", str(code or ""))
    if not digits:
        return ""
    return digits[:precision] if len(digits) >= precision else digits.ljust(precision, "0")


def hs_match_series(hs_col, item_hs, precision=8):
    item_norm = normalize_hs(item_hs, precision)
    if not item_norm:
        return pd.Series(False, index=hs_col.index)
    uniques = hs_col.dropna().unique()
    lookup = {v: normalize_hs(v, precision) == item_norm for v in uniques}
    return hs_col.map(lambda v: lookup.get(v, False)).fillna(False)


# ---------------- Company name normalization ----------------

def normalize_company_name(raw):
    if not raw:
        return ""
    s = re.sub(r"[.,()]", " ", str(raw).upper())
    s = re.sub(r"\s+", " ", s).strip()
    words = [w for w in s.split(" ") if w]
    if not words:
        return ""
    last_suffix_idx = -1
    for i, w in enumerate(words):
        if w in LEGAL_SUFFIX_WORDS:
            last_suffix_idx = i
    if last_suffix_idx >= 0:
        trailing = words[last_suffix_idx + 1:]
        if trailing and (any(re.search(r"\d", w) for w in trailing) or len(trailing) >= 2):
            words = words[: last_suffix_idx + 1]
    core = " ".join(w for w in words if w not in LEGAL_SUFFIX_WORDS)
    return core or " ".join(words)


def company_key(raw_name):
    norm = normalize_company_name(raw_name)
    return norm or str(raw_name or "(unnamed)")


# ---------------- Description / grade-code matching ----------------

def extract_code_tokens(name):
    tokens = []
    for tok in str(name or "").split():
        if re.search(r"[a-zA-Z]", tok) and re.search(r"[0-9]", tok):
            c = compact(tok)
            if c:
                tokens.append(c)
    return tokens


def desc_score_series(item_name, desc_series):
    """Vectorized port of descScore() — returns a float Series (0..1) per row."""
    row_compact = desc_series.fillna("").astype(str).map(compact)
    code_tokens = extract_code_tokens(item_name)
    if code_tokens:
        mask = pd.Series(True, index=desc_series.index)
        for ct in code_tokens:
            mask &= row_compact.str.contains(re.escape(ct), regex=True, na=False)
        return mask.astype(float)

    item_compact = compact(item_name)
    scores = pd.Series(0.0, index=desc_series.index)
    if len(item_compact) >= 4:
        phrase_mask = row_compact.str.contains(re.escape(item_compact), regex=True, na=False)
        reverse_mask = row_compact.map(lambda rc: bool(rc) and rc in item_compact)
        scores = (phrase_mask | reverse_mask).astype(float)

    item_words = list(dict.fromkeys(norm_words(item_name)))
    if not item_words:
        return scores
    distinctive = [w for w in item_words if w not in GENERIC_MATCH_WORDS]
    if not distinctive:
        return scores

    row_words = desc_series.fillna("").astype(str).map(lambda s: set(norm_words(s)))
    n_words = len(item_words)
    word_scores = row_words.map(lambda rw: sum(1 for w in item_words if w in rw) / n_words)
    return pd.Series(np.maximum(scores.values, word_scores.values), index=desc_series.index)


# ---------------- Date parsing ----------------

def _parse_date_scalar(v):
    if v is None or v == "" or (isinstance(v, float) and np.isnan(v)):
        return pd.NaT
    if isinstance(v, (pd.Timestamp,)):
        return v
    if hasattr(v, "year") and hasattr(v, "month"):  # datetime.date / datetime.datetime
        try:
            return pd.Timestamp(v)
        except Exception:
            return pd.NaT
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        # Excel serial date (epoch 1899-12-30, same convention the JS build used)
        try:
            return pd.Timestamp("1899-12-30") + pd.to_timedelta(float(v), unit="D")
        except Exception:
            return pd.NaT
    s = str(v).strip()
    if not s:
        return pd.NaT
    try:
        d = pd.to_datetime(s, errors="raise")
        if not pd.isna(d):
            return d
    except Exception:
        pass
    m = _slash_date_re.search(s)
    if m:
        a, b, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        try:
            return pd.Timestamp(f"{y}-{b}-{a}")  # assume DD/MM/YYYY, same as the original tool
        except Exception:
            return pd.NaT
    return pd.NaT


def parse_date_series(col):
    uniques = col.dropna().unique()
    lookup = {v: _parse_date_scalar(v) for v in uniques}
    return col.map(lambda v: lookup.get(v, pd.NaT))


def extract_date_from_gd_scalar(v):
    if not v:
        return pd.NaT
    m = _gd_date_re.search(str(v))
    if not m:
        return pd.NaT
    dd, mm, yyyy = m.groups()
    try:
        return pd.Timestamp(f"{yyyy}-{mm}-{dd}")
    except Exception:
        return pd.NaT


def row_date_series(df, mapping):
    idx = df.index
    result = pd.Series(pd.NaT, index=idx, dtype="datetime64[ns]")
    date_col = mapping.get("date")
    if date_col and date_col in df.columns:
        result = parse_date_series(df[date_col])
    year_col = mapping.get("year")
    if year_col and year_col in df.columns:
        need = result.isna()
        if need.any():
            years = pd.to_numeric(df.loc[need, year_col], errors="coerce")
            year_dates = years.map(lambda y: pd.Timestamp(year=int(y), month=1, day=1) if pd.notna(y) else pd.NaT)
            result.loc[need] = year_dates
    gd_col = mapping.get("gd")
    if gd_col and gd_col in df.columns:
        need = result.isna()
        if need.any():
            uniques = df.loc[need, gd_col].dropna().unique()
            lookup = {v: extract_date_from_gd_scalar(v) for v in uniques}
            result.loc[need] = df.loc[need, gd_col].map(lambda v: lookup.get(v, pd.NaT))
    return result


def in_period_mask(dates, period, period_from, period_to):
    idx = dates.index
    if period == "all":
        return pd.Series(True, index=idx)
    now = pd.Timestamp.now()
    if period == "custom":
        mask = pd.Series(True, index=idx)
        if period_from:
            mask &= dates >= pd.Timestamp(period_from)
        if period_to:
            mask &= dates <= pd.Timestamp(period_to)
    else:
        months_ago = (now - dates).dt.total_seconds() / (60 * 60 * 24 * 30.44)
        if period == "0-6":
            mask = (months_ago >= 0) & (months_ago <= 6)
        elif period == "6-12":
            mask = (months_ago > 6) & (months_ago <= 12)
        elif period == "0-12":
            mask = (months_ago >= 0) & (months_ago <= 12)
        elif period == "12-24":
            mask = (months_ago > 12) & (months_ago <= 24)
        else:
            mask = pd.Series(True, index=idx)
    # Rows with no readable date are always included, same as passesPeriod() in the original.
    return mask.fillna(False) | dates.isna()


# ---------------- Top-level matcher ----------------

def rows_for_item(df, mapping, item, file_key, period="all", period_from=None, period_to=None):
    """Returns the subset of df matching `item` by HS Code and/or description, filtered to the
    selected comparison period, with a `_date` column of parsed shipment dates attached."""
    if df is None or len(df) == 0 or not mapping:
        return df.iloc[0:0].assign(_date=pd.NaT) if df is not None else pd.DataFrame()

    desc_col = mapping.get("desc")
    mask_desc = pd.Series(False, index=df.index)
    if desc_col and desc_col in df.columns:
        mask_desc = desc_score_series(item["name"], df[desc_col]) >= DESC_MATCH_THRESHOLD

    hs_col = mapping.get("hs")
    mask_hs = pd.Series(False, index=df.index)
    if hs_col and hs_col in df.columns:
        precision = 6 if file_key == "wits" else 8
        mask_hs = hs_match_series(df[hs_col], item["hs"], precision)

    matched = df[mask_desc | mask_hs]
    if matched.empty:
        return matched.assign(_date=pd.NaT)

    dates = row_date_series(matched, mapping)
    period_mask = in_period_mask(dates, period, period_from, period_to)
    result = matched[period_mask].copy()
    result["_date"] = dates[period_mask]
    return result
