"""
Live market data — feedstock price context for procurement decisions (e.g. crude oil,
the upstream base material for PTA/MEG/PET and similar petrochemical raw materials).

Uses API Ninjas' free tier (api-ninjas.com) — free signup, no card required. Requires an
API_NINJAS_KEY environment variable; without it, functions return a clear "not configured"
message instead of failing silently or raising, so a missing key never crashes the app.
"""
import os
import requests

API_NINJAS_BASE = "https://api.api-ninjas.com/v1"


def _api_key():
    return os.environ.get("API_NINJAS_KEY")


def get_oil_prices(timeout=8):
    """
    Returns {"ok": True, "wti": {...}, "brent": {...}} on success, or
    {"ok": False, "reason": "..."} on any failure — never raises, so a flaky network call
    or a missing API key never crashes the page it's shown on.
    """
    key = _api_key()
    if not key:
        return {"ok": False, "reason": "not_configured"}

    headers = {"X-Api-Key": key}
    result = {"ok": True}
    try:
        for benchmark in ("wti", "brent"):
            resp = requests.get(f"{API_NINJAS_BASE}/oilprice", params={"type": benchmark},
                                 headers=headers, timeout=timeout)
            if resp.status_code != 200:
                return {"ok": False, "reason": f"api_error_{resp.status_code}", "detail": resp.text[:200]}
            result[benchmark] = resp.json()
        return result
    except requests.exceptions.Timeout:
        return {"ok": False, "reason": "timeout"}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "reason": "network_error", "detail": str(e)[:200]}


def format_oil_insight(data):
    """Turns get_oil_prices()'s result into a short, director-readable summary."""
    if not data.get("ok"):
        reason = data.get("reason")
        if reason == "not_configured":
            return ("Live oil market data isn't set up yet — needs a free API Ninjas key "
                    "(api-ninjas.com) added as the API_NINJAS_KEY environment variable.")
        return f"Couldn't fetch live oil prices right now ({reason}). Try again shortly."

    lines = []
    for key, label in [("wti", "WTI Crude"), ("brent", "Brent Crude")]:
        d = data.get(key)
        if not d:
            continue
        price = d.get("price")
        prev = d.get("previous_close")
        change_note = ""
        if price is not None and prev:
            pct = (price - prev) / prev * 100
            arrow = "▲" if pct > 0 else "▼" if pct < 0 else "—"
            change_note = f" ({arrow} {abs(pct):.1f}% vs previous close)"
        lines.append(f"**{label}**: ${price:.2f}/barrel{change_note}")
    return "  \n".join(lines) if lines else "No oil price data returned."
