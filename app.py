"""RM Procurement Analyzer — Gatronova. Streamlit port of the original HTML/JS tool."""
import re
from datetime import date

import pandas as pd
import streamlit as st

import state
import items as items_mod
import matching
import aggregation as agg
import insights as insights_mod
import charts
import pptx_export
import market_data

st.set_page_config(page_title="RM Procurement Analyzer — Gatronova", layout="wide", page_icon="📦")
state.init_state()

st.markdown("""
<style>
div[data-testid="stMetricValue"] { color: #d4a755; }
.streamlit-expanderHeader { font-weight: 600; }
</style>
""", unsafe_allow_html=True)

import db_store

@st.cache_data(show_spinner=False)
def _cached_rows_for_item(file_key, mapping_items, item_name, item_hs, period, period_from, period_to):
    # Instead of scanning a full 100k+ row in-memory table, this runs a broad SQL pre-filter
    # against the database (indexed on HS Code / Item Description) to narrow down to a small
    # candidate set, THEN hands that small set to the exact same, already-tested precise
    # matching logic. Caching key args are small/hashable now (no more hashing a huge
    # DataFrame every rerun), and the underlying data no longer needs to fit in RAM at all.
    mapping = dict(mapping_items)
    headers, candidates = db_store.prefilter_candidates(file_key, mapping, item_name, item_hs)
    if not candidates:
        return pd.DataFrame()
    cand_df = pd.DataFrame(candidates)
    item = {"name": item_name, "hs": item_hs}
    return matching.rows_for_item(cand_df, mapping, item, file_key, period, period_from, period_to)


PERIOD_OPTIONS = [
    ("all", "All time"), ("0-6", "0–6 months"), ("6-12", "6–12 months"),
    ("0-12", "Last 12 months"), ("12-24", "12–24 months ago"), ("custom", "Custom range"),
]
PERIOD_LABELS = dict(PERIOD_OPTIONS)
CURRENCIES = ["USD", "PKR", "EUR", "CNY", "JPY", "GBP"]


# ==================== Upload section ====================

def _file_summary_text():
    bits = []
    for ft in items_mod.FILE_TYPES:
        rec = st.session_state.files.get(ft["key"])
        label = ft["label"].split(" ")[0]
        bits.append(f"{label}: {rec['row_count']:,} rows" if rec else f"{label}: not uploaded")
    return "  ·  ".join(bits)


def render_mapping_ui(ft, rec):
    key = ft["key"]
    headers = rec["headers"]
    options = ["—"] + headers
    new_mapping = {}
    changed = False
    for role_key, role_label in ft["roles"]:
        current = rec["mapping"].get(role_key)
        idx = options.index(current) if current in options else 0
        val = st.selectbox(role_label, options, index=idx, key=f"map_{key}_{role_key}")
        new_val = None if val == "—" else val
        new_mapping[role_key] = new_val
        if new_val != current:
            changed = True
    if changed:
        rec["mapping"] = new_mapping
        state.save_file(key, rec)
        st.rerun()


def render_file_card(ft):
    key = ft["key"]
    st.markdown(f"**{ft['label']}**")
    st.caption(ft["desc"])
    uploaded = st.file_uploader("Upload file", type=["csv", "txt", "xlsx", "xls"], key=f"uploader_{key}",
                                 label_visibility="collapsed")
    if uploaded is not None:
        marker = f"_last_upload_{key}"
        sig = (uploaded.name, uploaded.size)
        if st.session_state.get(marker) != sig:
            with st.spinner(f"Reading {uploaded.name}…"):
                state.handle_upload(key, uploaded)
            st.session_state[marker] = sig
            st.rerun()

    notice = st.session_state.upload_notice.get(key)
    if notice:
        (st.warning if notice["type"] == "dup" else st.success)(notice["text"])

    rec = st.session_state.files.get(key)
    if not rec:
        st.caption("No file uploaded yet")
        return

    last = rec["uploads"][-1]
    st.caption(f"Total: **{rec['row_count']:,} rows** across {len(rec['uploads'])} upload"
               f"{'s' if len(rec['uploads']) != 1 else ''}. Last added: {last['fileName']} — {last['rowCount']:,} rows.")
    if len(rec["uploads"]) > 1:
        with st.expander(f"Upload history ({len(rec['uploads'])})"):
            for u in rec["uploads"]:
                st.write(f"- {u['fileName']} — {u['rowCount']:,} rows — {u['uploadedAt'][:10]}")

    if st.button("Clear all data", key=f"clear_{key}"):
        state.clear_file_data(key)
        st.session_state.pop(f"_last_upload_{key}", None)
        st.rerun()

    with st.expander("Column mapping", expanded=False):
        render_mapping_ui(ft, rec)


def render_upload_section():
    st.caption(_file_summary_text())
    st.caption("Uploaded data lives for this browser session only — if the app disconnects "
               "or restarts, you'll need to re-upload. Column mappings, custom items, and "
               "saved positions are not affected.")
    with st.expander("Manage data sources", expanded=st.session_state.uploads_expanded):
        cols = st.columns(3)
        for col, ft in zip(cols, items_mod.FILE_TYPES):
            with col:
                render_file_card(ft)


# ==================== Category + item selection ====================

def render_category_and_item_section():
    cols = st.columns(len(items_mod.CATEGORY_DEFS))
    for col, cd in zip(cols, items_mod.CATEGORY_DEFS):
        n = len(items_mod.get_items_for_category(cd["key"], st.session_state.removed_items, st.session_state.custom_items))
        with col:
            btn_type = "primary" if st.session_state.category == cd["key"] else "secondary"
            if st.button(f"{cd['label']} ({n})", key=f"cat_{cd['key']}", width='stretch', type=btn_type):
                st.session_state.category = cd["key"]
                st.session_state.selected = None
                st.rerun()

    cat = st.session_state.category

    with st.expander("Quick Compare — add an item on the fly", expanded=False):
        st.caption(f'Add an item by name and HS Code to check its market comparison — added to '
                   f'"{items_mod.CATEGORY_LABELS[cat]}" so it\'s ready to select.')
        with st.form(f"quick_compare_{cat}", clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 1, 1])
            name = c1.text_input("Item name", placeholder="e.g. Mono Ethylene Glycol")
            hs = c2.text_input("HS Code", placeholder="e.g. 2905.3100")
            c3.write("")
            submitted = c3.form_submit_button("Add & Compare", type="primary")
            if submitted:
                if not name.strip() or not hs.strip():
                    st.warning("Item name and HS Code are both required.")
                else:
                    state.add_custom_item(cat, name.strip(), hs.strip(), plant="Quick Compare")
                    st.rerun()

    item_list = items_mod.get_items_for_category(cat, st.session_state.removed_items, st.session_state.custom_items)
    if item_list:
        labels = {it["uid"]: f"{it['plant']} — {it['name']} (HS {it['hs']})" for it in item_list}
        NONE_LABEL = "— Select an item —"
        uid_options = [NONE_LABEL] + [it["uid"] for it in item_list]
        current = st.session_state.selected if st.session_state.selected in labels else NONE_LABEL
        idx = uid_options.index(current)
        chosen = st.selectbox(
            f"{items_mod.CATEGORY_LABELS[cat]} item", uid_options, index=idx,
            format_func=lambda u: NONE_LABEL if u == NONE_LABEL else labels[u], key=f"item_select_{cat}",
        )
        if chosen != current:
            st.session_state.selected = None if chosen == NONE_LABEL else chosen
            st.rerun()

        if st.session_state.selected and st.button("Remove selected item", key=f"remove_item_{cat}"):
            state.remove_item(cat, st.session_state.selected)
            st.rerun()
    else:
        st.info(f'No items in "{items_mod.CATEGORY_LABELS[cat]}" yet — add one below.')

    removed = items_mod.removed_items_for_category(cat, st.session_state.removed_items)
    if removed:
        with st.expander(f"Discontinued items ({len(removed)})"):
            for it in removed:
                c1, c2 = st.columns([4, 1])
                c1.write(f"~~{it['name']}~~")
                if c2.button("Restore", key=f"restore_{it['uid']}"):
                    state.restore_item(cat, it["uid"])
                    st.rerun()

    with st.expander("+ Add new item to this list"):
        with st.form(f"add_item_{cat}", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Item name", placeholder="e.g. Antimony Trioxide")
            hs = c2.text_input("HS Code", placeholder="e.g. 2825.8000")
            origin = c1.text_input("Origin", placeholder="e.g. CN")
            plant = c2.text_input("Plant / group", placeholder="e.g. Novatex Plant")
            submitted = st.form_submit_button("Save item", type="primary")
            if submitted:
                if not name.strip() or not hs.strip():
                    st.warning("Item name and HS Code are required.")
                else:
                    state.add_custom_item(cat, name.strip(), hs.strip(), origin.strip(), plant.strip())
                    st.rerun()


# ==================== Detail view helpers ====================

def render_rank_banner(imp_rows, imp_mapping, our_price):
    if not imp_mapping.get("price") or our_price is None:
        st.info("Enter our unit price and map the import price column to see our rank.")
        return
    rank = agg.compute_rank(imp_rows, imp_mapping, our_price)
    if not rank:
        st.info("No matched import prices in a consistent currency to rank against.")
        return
    cur_note = f" — compared in {rank['currency']} only" if rank["currency"] else ""
    excl_note = (f" {rank['excluded']} shipment{'s' if rank['excluded'] != 1 else ''} in a different currency "
                 f"were excluded from this comparison rather than blended in." if rank["excluded"] > 0 else "")
    st.success(
        f"We are ranked **#{rank['rank']}** of {rank['total']} among matched importers, by unit price "
        f"(lowest = #1){cur_note}.\n\n"
        f"Ranking compares against the \"Import Customs Data\" file only, on the mapped HS Code + Unit Price columns. "
        f"Records only match to the 6-digit HS heading if an exact code isn't found — treat matches at that level as a "
        f"category benchmark, not an exact product comparison.{excl_note}"
    )


def render_competitor_grid(rows, mapping, company_role):
    has_key = mapping.get("hs") or mapping.get("desc")
    if not has_key:
        st.caption("Upload this file and map the HS Code and/or Item Description column to see matches.")
        return
    if not rows:
        st.caption("No matching records found for this item.")
        return
    name_col = mapping.get(company_role)
    price_col = mapping.get("price")
    if not name_col or not price_col:
        st.caption("Map the supplier/company and unit price columns to display this table.")
        return

    top = agg.aggregate_by(rows, name_col, mapping, matching.company_key)[:5]
    top_names = [n for n, _ in top]
    if not top_names:
        st.caption("No matching records found for this item.")
        return
    st.caption("Top 5 competitors by quantity. Each tab is one company — every date/price listed is an actual "
               "shipment, not an average.")
    tabs = st.tabs(top_names)
    for tab, name in zip(tabs, top_names):
        with tab:
            company_rows = [r for r in rows if agg.match_company_name(r.get(name_col), top_names) == name]

            def sort_key(r):
                d = r.get("_date")
                return d if d is not None and not pd.isna(d) else pd.Timestamp.min
            company_rows.sort(key=sort_key, reverse=True)

            table_rows = []
            for r in company_rows[:25]:
                d = r.get("_date")
                d_str = d.strftime("%m/%d/%Y") if d is not None and not pd.isna(d) else "—"
                q = agg.num(r.get(mapping.get("qty"))) if mapping.get("qty") else None
                p = agg.num(r.get(price_col))
                table_rows.append({
                    "Date": d_str,
                    "Price (per KG)": agg.fmt_price_per_kg(p) if p is not None else r.get(price_col, "—"),
                    "Currency": r.get(mapping.get("currency"), "") if mapping.get("currency") else "",
                    "Qty (MT)": agg.fmt_qty_mt(q) if q is not None else "",
                })
            st.dataframe(pd.DataFrame(table_rows), hide_index=True, width='stretch')
            if len(company_rows) > 25:
                st.caption(f"+{len(company_rows) - 25} more shipments")


def render_top_table(rows, mapping, name_role, name_label, extras):
    """extras: list of (role, label) columns to show between the name and Qty/Price columns."""
    has_key = mapping.get("hs") or mapping.get("desc")
    if not has_key or not rows or not mapping.get("qty"):
        st.caption("Not enough mapped data yet.")
        return
    name_col = mapping.get(name_role)
    if not name_col:
        st.caption(f'Map the "{name_label}" column to build this table.')
        return
    top = agg.aggregate_by(rows, name_col, mapping, matching.company_key)[:5]
    records = []
    for name, v in top:
        rec = {name_label: name}
        for role, label in extras:
            vals = v["values"].get(role, [])
            shown = ", ".join(str(x) for x in vals[:3])
            rest = len(vals) - 3
            rec[label] = shown + (f" +{rest} more" if rest > 0 else "") if vals else "—"
        rec["Qty (MT)"] = agg.fmt_qty_mt(v['qty'])
        rec["Unit Price (per KG)"] = agg.fmt_price_per_kg(v["priceAvg"], v["currency"])
        records.append(rec)
    st.dataframe(pd.DataFrame(records), hide_index=True, width='stretch')


def render_landed_cost(rows, mapping, headers):
    if not mapping.get("supplier") or not mapping.get("qty"):
        st.caption("Map the Supplier and Quantity columns to see landed cost comparison.")
        return
    ranked = agg.landed_cost_ranked(rows, mapping, headers, "supplier")
    if ranked is None:
        cols_detected = agg.detect_landed_cost_columns(headers)
        if "importValuePkr" not in cols_detected:
            st.caption('This file doesn\'t have an "Import Value in PKR" column — landed cost needs it to compute '
                       'total paid cost per unit.')
        else:
            st.caption("Couldn't compute landed cost from the matched rows — check that quantity and PKR value "
                       "fields have numeric data.")
        return
    cols_detected = agg.detect_landed_cost_columns(headers)
    formula, note = agg.landed_cost_formula_text(cols_detected)
    st.info(f"**How this is calculated:** {formula}, quantity-weighted across shipments.{note}")
    df = pd.DataFrame([
        {"#": i + 1, "Supplier (Exporter)": name, "Qty (MT)": agg.fmt_qty_mt(qty),
         "Landed Cost / KG (PKR)": agg.fmt_price_per_kg(lc)}
        for i, (name, lc, qty) in enumerate(ranked)
    ])
    st.dataframe(df, hide_index=True, width='stretch')


def render_region_table(rows, mapping, region_role):
    has_key = mapping.get("hs") or mapping.get("desc")
    region_col = mapping.get(region_role)
    if not has_key or not rows or not region_col or not mapping.get("price"):
        st.caption("Map the country/region column for this file to see the regional breakdown."
                   if not region_col else "No matching records found for this item.")
        return
    top = agg.aggregate_by(rows, region_col, mapping)[:6]
    df = pd.DataFrame([
        {"Region": name,
         "Avg Unit Price (per KG)": agg.fmt_price_per_kg(v["priceAvg"], v["currency"]),
         "Qty (MT)": agg.fmt_qty_mt(v['qty'])}
        for name, v in top
    ])
    st.dataframe(df, hide_index=True, width='stretch')


def render_company_month_matrix(rows, mapping, company_role, label):
    has_key = mapping.get("hs") or mapping.get("desc")
    if not has_key or not rows:
        st.caption("No matching records found for this item.")
        return
    matrix = agg.full_company_month_matrix(rows, mapping, company_role, 20)
    if not matrix or not matrix["companies"]:
        st.caption(f"Map the {label}, Quantity, and Unit Price columns for this file to see this table.")
        return
    if matrix["rest"] > 0:
        st.caption(f"Showing top {len(matrix['companies'])} of {matrix['total_companies']} "
                   f"{label.lower()}s by total quantity.")
    records = []
    for name in matrix["companies"]:
        row_out = {label: name}
        for mk in matrix["months"]:
            cell = matrix["cell"].get(name, {}).get(mk)
            col_label = agg.month_label(mk)
            if not cell:
                row_out[col_label] = "—"
            else:
                avg = cell["wsum"] / cell["wqty"] if cell["wqty"] > 0 else (cell["sum"] / cell["n"] if cell["n"] else 0)
                row_out[col_label] = f"{agg.fmt_qty_mt(cell['qty'])} MT @ {agg.fmt_price_per_kg(avg)}/KG"
        records.append(row_out)
    st.dataframe(pd.DataFrame(records), hide_index=True, width='stretch')
    st.caption("Each cell: total quantity (MT) @ quantity-weighted average unit price (per KG), by month.")


# ==================== Detail view ====================

def render_detail(uid):
    base_item = items_mod.find_item(uid, st.session_state.custom_items)
    if not base_item:
        st.warning("Selected item no longer exists.")
        st.session_state.selected = None
        return
    item = state.effective_item(base_item)
    manual = st.session_state.manual.get(uid, {"qty": "", "price": "", "currency": "USD", "supplier": ""})

    st.divider()
    st.subheader(item["name"])
    hc1, hc2, hc3 = st.columns([2, 1, 4])
    new_hs = hc1.text_input("HS Code", value=item["hs"], key=f"hs_edit_{uid}")
    hc2.write("")
    if hc2.button("Save HS Code", key=f"hs_save_{uid}"):
        if new_hs.strip():
            state.save_hs_override(uid, new_hs.strip())
            st.rerun()
    hc3.write("")
    hc3.caption(f"Origin {item.get('origin', '—')} · {item['plant']}")
    st.caption('If item descriptions vary in the customs data (e.g. "MONO ETHYLENE" vs "MONOETHYLENE"), correcting '
               'the HS Code here gives matching a reliable fallback.')

    with st.expander("📈 Live market scenario (crude oil — base feedstock context)"):
        st.caption("For products whose base material traces back to crude oil (e.g. petrochemical-derived "
                   "raw materials), current oil prices give directional context for cost pressure.")
        if st.button("Check current oil market", key=f"oil_check_{uid}"):
            with st.spinner("Fetching live oil prices…"):
                st.session_state[f"oil_data_{uid}"] = market_data.get_oil_prices()
        oil_result = st.session_state.get(f"oil_data_{uid}")
        if oil_result:
            if oil_result.get("ok"):
                st.markdown(market_data.format_oil_insight(oil_result))
            else:
                st.warning(market_data.format_oil_insight(oil_result))

    st.markdown("##### Data shown")
    st.caption("Some items only trade on one side. Toggle which comparisons to show here — the PPT export follows "
               "the same selection.")
    dv1, dv2 = st.columns(2)
    show_import = dv1.checkbox("Import", value=st.session_state.data_view["import"], key=f"dv_import_{uid}")
    show_export = dv2.checkbox("Export", value=st.session_state.data_view["export"], key=f"dv_export_{uid}")
    st.session_state.data_view["import"] = show_import
    st.session_state.data_view["export"] = show_export

    st.markdown("##### Our current position")
    p1, p2, p3, p4 = st.columns(4)
    qty_in = p1.text_input("Quantity (KG)", value=str(manual.get("qty") or ""), key=f"m_qty_{uid}")
    price_in = p2.text_input("Unit price (per KG)", value=str(manual.get("price") or ""), key=f"m_price_{uid}")
    cur_idx = CURRENCIES.index(manual.get("currency")) if manual.get("currency") in CURRENCIES else 0
    currency_in = p3.selectbox("Currency", CURRENCIES, index=cur_idx, key=f"m_currency_{uid}")
    supplier_in = p4.text_input("Supplier", value=manual.get("supplier") or "", key=f"m_supplier_{uid}")
    if st.button("Save position", key=f"save_manual_{uid}", type="primary"):
        state.save_manual(uid, qty_in, price_in, currency_in, supplier_in)
        st.rerun()

    st.markdown("##### Comparison period")
    st.caption("Applies to import/exporter comparisons, top tables, rank, and the trend chart below. Rows with no "
               "readable date are always included.")
    period_keys = [p[0] for p in PERIOD_OPTIONS]
    pcol1, pcol2, pcol3 = st.columns(3)
    period_idx = period_keys.index(st.session_state.period)
    new_period = pcol1.selectbox("Range", period_keys, index=period_idx,
                                  format_func=lambda k: PERIOD_LABELS[k], key=f"period_{uid}")
    if new_period != st.session_state.period:
        st.session_state.period = new_period
        st.rerun()
    period_from, period_to = st.session_state.period_from, st.session_state.period_to
    if st.session_state.period == "custom":
        pf = pcol2.date_input("From", value=date.fromisoformat(period_from) if period_from else date.today(), key=f"pf_{uid}")
        pt = pcol3.date_input("To", value=date.fromisoformat(period_to) if period_to else date.today(), key=f"pt_{uid}")
        st.session_state.period_from = pf.isoformat()
        st.session_state.period_to = pt.isoformat()
        period_from, period_to = st.session_state.period_from, st.session_state.period_to

    # ---- matched rows for this item ----
    imp_rec = st.session_state.files.get("import")
    exp_rec = st.session_state.files.get("export")
    wits_rec = st.session_state.files.get("wits")

    imp_mapping = (imp_rec or {}).get("mapping", {}) or {}
    exp_mapping = (exp_rec or {}).get("mapping", {}) or {}
    wits_mapping = (wits_rec or {}).get("mapping", {}) or {}

    with st.spinner("Matching item against uploaded customs data…"):
        imp_df = _cached_rows_for_item("import", tuple(sorted(imp_mapping.items())), item["name"], item["hs"],
                                        st.session_state.period, period_from, period_to) if imp_rec else pd.DataFrame()
        exp_df = _cached_rows_for_item("export", tuple(sorted(exp_mapping.items())), item["name"], item["hs"],
                                        st.session_state.period, period_from, period_to) if exp_rec else pd.DataFrame()
        wits_df = _cached_rows_for_item("wits", tuple(sorted(wits_mapping.items())), item["name"], item["hs"],
                                         st.session_state.period, period_from, period_to) if wits_rec else pd.DataFrame()

    imp_rows = imp_df.to_dict("records")
    exp_rows = exp_df.to_dict("records")
    wits_rows = wits_df.to_dict("records")

    our_price = agg.num(manual.get("price"))

    if show_import:
        st.markdown("##### Our position vs. the market")
        render_rank_banner(imp_rows, imp_mapping, our_price)

    if show_import or show_export:
        c1, c2 = st.columns(2)
        if show_import:
            with c1:
                st.markdown("###### Last importer data — top 5 competitors (import customs data)")
                render_competitor_grid(imp_rows, imp_mapping, "importer")
        if show_export:
            with c2:
                st.markdown("###### Exporter data — top 5 competitors (exporter customs data)")
                render_competitor_grid(exp_rows, exp_mapping, "exporter")

    if show_import:
        st.markdown(f"###### Top importers — HS {item['hs']}")
        render_top_table(imp_rows, imp_mapping, "importer", "Importer",
                          [("origin", "Country"), ("supplier", "Supplier")])
    if show_export:
        st.markdown(f"###### Top exporters — HS {item['hs']}")
        render_top_table(exp_rows, exp_mapping, "exporter", "Exporter", [("expcountry", "Country")])

    if show_import:
        st.markdown("###### Landed cost comparison — which importer/supplier pairing is most cost-effective")
        render_landed_cost(imp_rows, imp_mapping, (imp_rec or {}).get("headers", []))

    if show_import or show_export:
        c1, c2 = st.columns(2)
        if show_import:
            with c1:
                st.markdown("###### Region-wise comparison — imports (by country of origin)")
                render_region_table(imp_rows, imp_mapping, "origin")
        if show_export:
            with c2:
                st.markdown("###### Region-wise comparison — exports (by exporting country)")
                render_region_table(exp_rows, exp_mapping, "expcountry")

    st.markdown("##### Exporter data based on selected item")
    st.caption('From the "Supplier Name" column in the import customs data — the foreign seller is the exporter '
               'from our side as the buyer/importer. By month: total quantity and average unit price.')
    st.session_state.show_exporter_tab = st.checkbox(
        "Show exporter-by-month table", value=st.session_state.show_exporter_tab, key=f"toggle_exp_tab_{uid}")
    if st.session_state.show_exporter_tab:
        render_company_month_matrix(imp_rows, imp_mapping, "supplier", "Exporter (Supplier)")

    st.markdown("##### Importer data based on selected item")
    st.caption('From the "Importer Name on GD" column in the import customs data. By month: total quantity and '
               'average unit price.')
    st.session_state.show_importer_tab = st.checkbox(
        "Show importer-by-month table", value=st.session_state.show_importer_tab, key=f"toggle_imp_tab_{uid}")
    if st.session_state.show_importer_tab:
        render_company_month_matrix(imp_rows, imp_mapping, "importer", "Importer")

    st.markdown("##### Price trend")
    fig = charts.build_trend_figure(imp_rows, imp_mapping, exp_rows, exp_mapping, wits_rows, wits_mapping, manual)
    if fig:
        st.pyplot(fig, width='stretch')
        st.caption("Vertical axis is unit price, horizontal axis is shipment date — each dot is one matched "
                   "shipment, not an average.")
    else:
        st.info("Upload and map at least one dated price field (import, export, or WITS) to see a price trend. "
                "Enter and save our unit price above to at least show a reference line.")

    st.markdown("##### Insights & recommendations")
    if st.button("Regenerate insights", key=f"insights_btn_{uid}"):
        bullets = insights_mod.build_insights_bullets(item, manual, imp_rows, imp_mapping, bool(imp_rec),
                                                        exp_rows, exp_mapping, bool(exp_rec))
        st.session_state.last_insights[uid] = bullets
    bullets = st.session_state.last_insights.get(uid)
    if bullets is None:
        bullets = insights_mod.build_insights_bullets(item, manual, imp_rows, imp_mapping, bool(imp_rec),
                                                        exp_rows, exp_mapping, bool(exp_rec))
        st.session_state.last_insights[uid] = bullets
    for b in bullets:
        st.markdown(f"- {b}")
    st.caption("Auto-drafted from the figures above (rule-based, no external calls) — review before sharing.")

    st.markdown("##### Remarks")
    remarks_val = st.session_state.remarks.get(uid, "")
    new_remarks = st.text_area("Add your own notes on this item's analysis", value=remarks_val,
                                key=f"remarks_{uid}", height=100,
                                placeholder="e.g. Discussed with supplier on 12 Aug — expects prices to firm up next quarter.")
    if st.button("Save remarks", key=f"save_remarks_{uid}"):
        state.save_remarks(uid, new_remarks)
        st.success("Remarks saved.")

    st.markdown("##### Export")
    if st.button("Generate PPTX", key=f"ppt_gen_{uid}", type="primary"):
        period_label = PERIOD_LABELS[st.session_state.period] if st.session_state.period != "custom" \
            else f"{period_from} to {period_to}"
        with st.spinner("Building PowerPoint…"):
            buf = pptx_export.build_pptx(
                item, manual, imp_rows, imp_mapping, bool(imp_rec), (imp_rec or {}).get("headers", []),
                exp_rows, exp_mapping, bool(exp_rec), wits_rows, wits_mapping,
                st.session_state.data_view, period_label,
            )
        st.session_state[f"pptx_bytes_{uid}"] = buf.getvalue()

    pptx_bytes = st.session_state.get(f"pptx_bytes_{uid}")
    if pptx_bytes:
        fname = re.sub(r"[^a-z0-9]+", "_", item["name"], flags=re.I) + "_director_review.pptx"
        st.download_button(
            "Download PPTX", data=pptx_bytes, file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            key=f"ppt_dl_{uid}",
        )


# ==================== Page ====================

top1, top2 = st.columns([5, 1])
with top1:
    st.title("RM Procurement Analyzer")
    st.caption("Gatronova — director review · price benchmarking against import / export / WITS trade data")

render_upload_section()
st.divider()
render_category_and_item_section()

if st.session_state.selected:
    render_detail(st.session_state.selected)
else:
    st.info("Select an RM item above to view its price position and trade comparison.")
