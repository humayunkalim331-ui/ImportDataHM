"""
Aggregation helpers — quantity-weighted averages, top-N by company, month x company
pivots, and landed-cost ranking. A direct port of the aggregation functions from the
original HTML/JS tool. Operates on `rows`: a list of dicts (customs data rows already
matched to an item and filtered to the comparison period — see matching.rows_for_item),
each carrying a `_date` key (a pandas Timestamp or NaT) with the parsed shipment date.
"""
import re
import pandas as pd

from matching import company_key

CURRENCY_CODES = {
    "USD", "PKR", "EUR", "GBP", "CNY", "JPY", "AED", "SAR", "THB", "INR", "CHF", "AUD",
    "CAD", "SGD", "HKD", "KRW", "MYR", "IDR", "TRY", "ZAR", "QAR", "KWD",
}


KG_PER_MT = 1000


def fmt_qty_mt(qty_kg):
    """Quantity display in MT (director-requested unit), converted from the underlying KG data."""
    if qty_kg is None:
        return "—"
    return f"{qty_kg / KG_PER_MT:,.2f}"


def fmt_price_per_mt(price_per_kg, currency=None):
    """Per-unit price converted to a per-MT basis, kept consistent with qty being shown in
    MT — showing MT quantities next to a $/KG price would be a confusing unit mismatch."""
    if price_per_kg is None:
        return "—"
    val = price_per_kg * KG_PER_MT
    return f"{val:,.2f}{' ' + currency if currency else ''}"


def num(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        return float(v)
    cleaned = re.sub(r"[^0-9.\-]", "", str(v).strip())
    if cleaned in ("", "-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _row_date(row):
    d = row.get("_date")
    if d is None or (isinstance(d, float)) or pd.isna(d):
        return None
    return d


# ---------------- Company / region aggregation ----------------

def aggregate_by(rows, key_col, mapping, normalize_key=None):
    """Returns [(display_name, info), ...] sorted by total quantity desc.
    info = {qty, priceAvg, currency, values: {role: [ordered distinct raw values]}, mergedVariantCount}"""
    if not key_col:
        return []
    agg = {}
    roles = [r for r, c in mapping.items() if c]
    for row in rows:
        raw_key = row.get(key_col)
        raw_key = raw_key if raw_key not in (None, "") else "(unspecified)"
        key = normalize_key(raw_key) if normalize_key else raw_key
        bucket = agg.setdefault(key, {
            "qty": 0.0, "price_sum": 0.0, "n": 0, "weighted_sum": 0.0, "weighted_qty": 0.0,
            "currency": None, "values": {}, "name_counts": {},
        })
        bucket["name_counts"][raw_key] = bucket["name_counts"].get(raw_key, 0) + 1
        q = num(row.get(mapping.get("qty"))) if mapping.get("qty") else None
        if q is not None:
            bucket["qty"] += q
        p = num(row.get(mapping.get("price"))) if mapping.get("price") else None
        if p is not None:
            bucket["n"] += 1
            bucket["price_sum"] += p
            if q is not None:
                bucket["weighted_sum"] += p * q
                bucket["weighted_qty"] += q
        if not bucket["currency"] and mapping.get("currency"):
            c = row.get(mapping["currency"])
            if c:
                bucket["currency"] = c
        for role in roles:
            col = mapping[role]
            val = row.get(col)
            if val in (None, ""):
                continue
            seen = bucket["values"].setdefault(role, [])
            if val not in seen:
                seen.append(val)

    out = []
    for key, v in agg.items():
        display_name, best_count = key, 0
        for raw, c in v["name_counts"].items():
            if c > best_count or (c == best_count and len(str(raw)) > len(str(display_name))):
                display_name, best_count = raw, c
        variant_count = len(v["name_counts"])
        price_avg = None
        if v["weighted_qty"] > 0:
            price_avg = v["weighted_sum"] / v["weighted_qty"]
        elif v["n"]:
            price_avg = v["price_sum"] / v["n"]
        out.append((display_name, {
            "qty": v["qty"], "priceAvg": price_avg, "currency": v["currency"], "values": v["values"],
            "mergedVariantCount": variant_count if variant_count > 1 else 0,
        }))
    out.sort(key=lambda kv: kv[1]["qty"], reverse=True)
    return out


def match_company_name(raw_name, display_names):
    k = company_key(raw_name)
    for n in display_names:
        if company_key(n) == k:
            return n
    return None


# ---------------- Currency-aware price stats ----------------

def dominant_currency_prices(rows, mapping):
    """Only rows sharing the dominant currency are compared — mixing currencies in one
    average/rank is meaningless. Returns (prices, pairs[{price,qty}], currency, excluded)."""
    price_col = mapping.get("price")
    if not price_col:
        return [], [], None, 0
    currency_col = mapping.get("currency")
    qty_col = mapping.get("qty")
    if not currency_col:
        pairs = []
        for row in rows:
            p = num(row.get(price_col))
            if p is not None:
                pairs.append({"price": p, "qty": num(row.get(qty_col)) if qty_col else None})
        return [p["price"] for p in pairs], pairs, None, 0

    counts = {}
    for row in rows:
        c = row.get(currency_col)
        if c:
            counts[c] = counts.get(c, 0) + 1
    dominant, best = None, 0
    for c, n in counts.items():
        if n > best:
            dominant, best = c, n

    excluded = 0
    pairs = []
    for row in rows:
        p = num(row.get(price_col))
        if p is None:
            continue
        c = row.get(currency_col)
        if dominant and c and c != dominant:
            excluded += 1
            continue
        pairs.append({"price": p, "qty": num(row.get(qty_col)) if qty_col else None})
    return [p["price"] for p in pairs], pairs, dominant, excluded


def weighted_average(pairs):
    with_qty = [p for p in pairs if p.get("qty") is not None and p["qty"] > 0]
    if with_qty:
        total_qty = sum(p["qty"] for p in with_qty)
        weighted_sum = sum(p["price"] * p["qty"] for p in with_qty)
        return weighted_sum / total_qty if total_qty > 0 else None
    if not pairs:
        return None
    return sum(p["price"] for p in pairs) / len(pairs)


def compute_rank(rows, mapping, our_price):
    """Returns dict {rank, total, currency, excluded} or None if not computable."""
    if not mapping or not mapping.get("price") or our_price is None:
        return None
    prices, _pairs, currency, excluded = dominant_currency_prices(rows, mapping)
    if not prices:
        return None
    all_prices = sorted(prices + [our_price])
    rank = all_prices.index(our_price) + 1
    return {"rank": rank, "total": len(all_prices), "currency": currency, "excluded": excluded}


# ---------------- Month x company pivots ----------------

def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def month_label(mk):
    y, m = mk.split("-")
    return pd.Timestamp(year=int(y), month=int(m), day=1).strftime("%B") + "-" + y[2:]


def monthly_pivot(rows, mapping, company_role, top_n):
    """Month x top-N-company price matrix — mirrors the PPTX 'top 5 competitors' slide table."""
    name_col = mapping.get(company_role)
    if not name_col or not mapping.get("price"):
        return None
    top_companies = [n for n, _ in aggregate_by(rows, name_col, mapping, company_key)[:top_n]]
    if not top_companies:
        return None

    pivot = {}
    currency_counts = {c: {} for c in top_companies}
    for row in rows:
        name = match_company_name(row.get(name_col), top_companies)
        if not name:
            continue
        d = _row_date(row)
        if d is None:
            continue
        p = num(row.get(mapping["price"]))
        if p is None:
            continue
        q = num(row.get(mapping.get("qty"))) if mapping.get("qty") else None
        mk = month_key(d)
        cell = pivot.setdefault(mk, {}).setdefault(name, {"sum": 0.0, "n": 0, "wsum": 0.0, "wqty": 0.0})
        cell["sum"] += p
        cell["n"] += 1
        if q is not None:
            cell["wsum"] += p * q
            cell["wqty"] += q
        if mapping.get("currency") and row.get(mapping["currency"]):
            c = row[mapping["currency"]]
            currency_counts[name][c] = currency_counts[name].get(c, 0) + 1

    company_currency = {}
    for c in top_companies:
        counts = currency_counts[c]
        best, best_n = None, 0
        for cur, n in counts.items():
            if n > best_n:
                best, best_n = cur, n
        company_currency[c] = best

    months = sorted(pivot.keys())[-6:]  # most recent 6 months with any data
    if not months:
        return None

    cheapest = None
    for mk in months:
        for c in top_companies:
            cell = pivot[mk].get(c)
            if cell:
                avg = cell["wsum"] / cell["wqty"] if cell["wqty"] > 0 else cell["sum"] / cell["n"]
                if cheapest is None or avg < cheapest["price"]:
                    cheapest = {"name": c, "price": avg, "currency": company_currency[c]}

    headers = ["Month"] + [f"{c} ({company_currency[c]})" if company_currency[c] else c for c in top_companies]
    body_rows = []
    for mk in months:
        row_out = [month_label(mk)]
        for c in top_companies:
            cell = pivot[mk].get(c)
            if not cell:
                row_out.append("—")
            else:
                avg = cell["wsum"] / cell["wqty"] if cell["wqty"] > 0 else cell["sum"] / cell["n"]
                row_out.append(f"{avg:.2f}")
        body_rows.append(row_out)
    return {"headers": headers, "rows": body_rows, "cheapest": cheapest}


def full_company_month_matrix(rows, mapping, company_role, max_companies):
    """Full (not top-5-capped) company x month matrix — powers the 'EXPORTER/IMPORTER DATA
    BASED ON SELECTED ITEM' tabs. Each cell carries total qty + quantity-weighted avg price."""
    name_col = mapping.get(company_role)
    if not name_col or not mapping.get("price") or not mapping.get("qty"):
        return None
    all_companies = [n for n, _ in aggregate_by(rows, name_col, mapping, company_key)]
    if not all_companies:
        return None
    shown = all_companies[:max_companies]
    rest = len(all_companies) - len(shown)

    cell = {}
    months_set = set()
    for row in rows:
        name = match_company_name(row.get(name_col), shown)
        if not name:
            continue
        d = _row_date(row)
        if d is None:
            continue
        mk = month_key(d)
        months_set.add(mk)
        bucket = cell.setdefault(name, {}).setdefault(mk, {"qty": 0.0, "sum": 0.0, "n": 0, "wsum": 0.0, "wqty": 0.0, "currency": None})
        q = num(row.get(mapping["qty"]))
        if q is not None:
            bucket["qty"] += q
        p = num(row.get(mapping["price"]))
        if p is not None:
            bucket["sum"] += p
            bucket["n"] += 1
            if q is not None:
                bucket["wsum"] += p * q
                bucket["wqty"] += q
        if not bucket["currency"] and mapping.get("currency") and row.get(mapping["currency"]):
            bucket["currency"] = row[mapping["currency"]]

    months = sorted(months_set)
    return {"companies": shown, "months": months, "cell": cell, "rest": rest, "total_companies": len(all_companies)}


# ---------------- Landed cost (paid duties/taxes already in the customs file) ----------------

LANDED_COST_FIELD_CANDIDATES = {
    "importValuePkr": ["Import Value in PKR"],
    "paidCustomsDuty": ["Paid Customs Duty"],
    "paidSalesTax": ["Paid Sales Tax"],           # detected but NOT included — see EXCLUDED_FROM_LANDED_COST
    "paidIncomeTax": ["Paid Income Tax"],         # detected but NOT included
    "additionalSalesTax": ["Additional Sales Tax"],  # detected but NOT included
    "additionalCustomsDuty": ["Additional Customs Duty"],
    "fed": ["Federal Excise Duty"],
    "specialFed": ["Special FED"],
    "otherTaxes": ["Other Taxes"],
}

# Columns actually summed into landed cost. Sales Tax and Income Tax are deliberately
# excluded: Sales Tax is a recoverable input tax credit for a registered business (not a
# real cost — it's reclaimed against output tax), and Income Tax withheld at import is an
# advance payment against the importer's own income tax liability, not a cost of the goods.
# Customs Duty and FED are non-recoverable and genuinely embedded in the landed cost.
LANDED_COST_INCLUDED_KEYS = ["paidCustomsDuty", "additionalCustomsDuty", "fed", "specialFed", "otherTaxes"]
LANDED_COST_EXCLUDED_KEYS = ["paidSalesTax", "paidIncomeTax", "additionalSalesTax"]


def detect_landed_cost_columns(headers):
    if not headers:
        return {}
    found = {}
    lower_headers = {str(h).strip().lower(): h for h in headers}
    for key, candidates in LANDED_COST_FIELD_CANDIDATES.items():
        for c in candidates:
            match = lower_headers.get(c.strip().lower())
            if match:
                found[key] = match
                break
    return found


def landed_cost_formula_text(cols):
    """Human-readable formula for the columns actually present in this file — shown on
    screen and in the PPT so the calculation isn't a black box."""
    parts = ["Import Value in PKR"]
    labels = {
        "paidCustomsDuty": "Paid Customs Duty", "additionalCustomsDuty": "Additional Customs Duty",
        "fed": "Federal Excise Duty", "specialFed": "Special FED", "otherTaxes": "Other Taxes",
    }
    for k in LANDED_COST_INCLUDED_KEYS:
        if k in cols:
            parts.append(labels[k])
    formula = " + ".join(parts) + "  ÷  Quantity"
    excluded_present = [k for k in LANDED_COST_EXCLUDED_KEYS if k in cols]
    note = ""
    if excluded_present:
        excl_labels = {"paidSalesTax": "Sales Tax", "paidIncomeTax": "Income Tax", "additionalSalesTax": "Additional Sales Tax"}
        note = (f" Sales Tax and Income Tax ({', '.join(excl_labels[k] for k in excluded_present)}) are "
                f"intentionally excluded — Sales Tax is a recoverable input tax credit and Income Tax "
                f"withheld at import is an advance against the company's own tax liability, so neither is "
                f"a real cost of the goods. Customs Duty and FED are non-recoverable, so they're included.")
    return formula, note


def landed_cost_per_unit(row, cols, qty):
    if "importValuePkr" not in cols or not qty or qty <= 0:
        return None
    total = num(row.get(cols["importValuePkr"]))
    if total is None:
        return None
    for k in LANDED_COST_INCLUDED_KEYS:
        if k in cols:
            v = num(row.get(cols[k]))
            if v is not None:
                total += v
    return total / qty



def landed_cost_ranked(rows, mapping, headers, company_role, limit=10):
    """Cheapest-first list of (display_name, landed_cost_per_kg, qty). None if not computable."""
    name_col = mapping.get(company_role)
    if not name_col or not mapping.get("qty"):
        return None
    cols = detect_landed_cost_columns(headers)
    if "importValuePkr" not in cols:
        return None

    agg = {}
    for row in rows:
        raw = row.get(name_col)
        if raw in (None, ""):
            continue
        name = company_key(raw)
        q = num(row.get(mapping["qty"]))
        if q is None or q <= 0:
            continue
        lc = landed_cost_per_unit(row, cols, q)
        if lc is None:
            continue
        bucket = agg.setdefault(name, {"qty": 0.0, "weighted_sum": 0.0, "name_counts": {}})
        bucket["qty"] += q
        bucket["weighted_sum"] += lc * q
        bucket["name_counts"][raw] = bucket["name_counts"].get(raw, 0) + 1

    ranked = []
    for name, v in agg.items():
        display_name, best_count = name, 0
        for raw, c in v["name_counts"].items():
            if c > best_count or (c == best_count and len(str(raw)) > len(str(display_name))):
                display_name, best_count = raw, c
        ranked.append((display_name, v["weighted_sum"] / v["qty"], v["qty"]))
    ranked.sort(key=lambda x: x[1])
    return ranked[:limit] if ranked else None
