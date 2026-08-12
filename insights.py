"""Rule-based, no-external-calls insight bullets — a direct port of buildInsightsBullets()."""
import pandas as pd

from aggregation import num, dominant_currency_prices, weighted_average, aggregate_by
from matching import company_key


def build_series(rows, mapping):
    if not mapping or not mapping.get("price"):
        return []
    out = []
    for r in rows:
        d = r.get("_date")
        if d is None or pd.isna(d):
            continue
        p = num(r.get(mapping["price"]))
        if p is None:
            continue
        out.append({"date": d, "price": p})
    out.sort(key=lambda p: p["date"])
    return out


def build_insights_bullets(item, manual, imp_rows, imp_mapping, has_import_file,
                            exp_rows, exp_mapping, has_export_file):
    our_price = num(manual.get("price"))
    bullets = []
    imp_avg = None

    if imp_mapping and imp_mapping.get("price") and imp_rows:
        prices, pairs, imp_cur, imp_excluded = dominant_currency_prices(imp_rows, imp_mapping)
        if prices:
            imp_avg = weighted_average(pairs)
            imp_min = min(prices)
            imp_max = max(prices)
            cur_suffix = f" {imp_cur}" if imp_cur else ""
            excluded_note = f" ({imp_excluded} shipment{'s' if imp_excluded != 1 else ''} in a different currency excluded)" if imp_excluded > 0 else ""
            if our_price is not None:
                diff_pct = (our_price - imp_avg) / imp_avg * 100
                bullets.append(
                    f"Our price ({our_price}{cur_suffix}) is {abs(diff_pct):.1f}% {'above' if diff_pct >= 0 else 'below'} "
                    f"the quantity-weighted average matched import price of {imp_avg:.2f}{cur_suffix} across "
                    f"{len(prices)} shipment{'s' if len(prices) != 1 else ''}{excluded_note}."
                )
                gap_to_min = ((our_price - imp_min) / imp_min * 100) if imp_min > 0 else 0
                if gap_to_min > 1:
                    bullets.append(
                        f"The cheapest matched import price is {imp_min:.2f}{cur_suffix} — {gap_to_min:.1f}% "
                        f"below what we're currently paying."
                    )
            else:
                bullets.append(
                    f"Matched import prices for this item range from {imp_min:.2f} to {imp_max:.2f}{cur_suffix}, "
                    f"averaging {imp_avg:.2f}{excluded_note}. Enter our current price above for a direct comparison."
                )
    elif not imp_rows and has_import_file:
        bullets.append("No matched import records for this item — check the HS Code / Item Description mapping, "
                        "or this item may not appear in the uploaded import file.")

    trend = build_series(imp_rows, imp_mapping)
    if len(trend) >= 2:
        first, last = trend[0]["price"], trend[-1]["price"]
        direction = "risen" if last > first else "fallen" if last < first else "stayed flat"
        bullets.append(f"Import price has {direction} over the selected period — from {first:.2f} to {last:.2f}.")

    if imp_mapping and imp_mapping.get("importer") and imp_mapping.get("qty") and imp_rows:
        top = aggregate_by(imp_rows, imp_mapping["importer"], imp_mapping, company_key)
        if top:
            name, info = top[0]
            avg_str = f"{info['priceAvg']:.2f}" if info["priceAvg"] is not None else "n/a"
            bullets.append(f"Largest matched importer by volume: {name} (avg price {avg_str}).")

    if exp_mapping and exp_mapping.get("price") and exp_rows:
        prices, pairs, exp_cur, _ = dominant_currency_prices(exp_rows, exp_mapping)
        if prices:
            avg = weighted_average(pairs)
            cur_suffix = f" {exp_cur}" if exp_cur else ""
            bullets.append(
                f"Matched export records average {avg:.2f}{cur_suffix} (quantity-weighted) across "
                f"{len(prices)} shipment{'s' if len(prices) != 1 else ''}."
            )

    if our_price is not None and imp_avg is not None:
        diff_pct = (our_price - imp_avg) / imp_avg * 100
        if diff_pct > 5:
            bullets.append("Recommendation: our price sits meaningfully above the matched market average — "
                            "worth renegotiating with the current supplier or sourcing a competitive quote.")
        elif diff_pct < -5:
            bullets.append("Recommendation: current pricing is favorable versus the matched market — "
                            "maintain the supplier relationship and keep monitoring.")
        else:
            bullets.append("Recommendation: pricing is broadly in line with the matched market — "
                            "no urgent action, continue monitoring.")

    if not bullets:
        bullets.append("Not enough matched data yet to draft insights — upload customs data, confirm the item's "
                        "HS Code / Item Description mapping, and enter our current price above.")

    return bullets[:6]
