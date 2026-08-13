"""Price trend chart — matplotlib port of the original tool's inline SVG chart.
Reused both for the on-screen Streamlit chart and the PNG embedded in the PPTX export."""
import io
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
import matplotlib.dates as mdates

from aggregation import num
from insights import build_series

SERIES_DEFS = [
    ("import", "Import (customs)", "#c99a4a"),
    ("export", "Export (customs)", "#4a9d84"),
    ("wits", "Global WITS", "#7a8fd0"),
]


def _collect_series(imp_rows, imp_mapping, exp_rows, exp_mapping, wits_rows, wits_mapping):
    data = {
        "import": build_series(imp_rows, imp_mapping),
        "export": build_series(exp_rows, exp_mapping),
        "wits": build_series(wits_rows, wits_mapping),
    }
    return [(key, label, color, data[key]) for key, label, color in SERIES_DEFS if data[key]]


def build_trend_figure(imp_rows, imp_mapping, exp_rows, exp_mapping, wits_rows, wits_mapping, manual,
                        dark=True, figsize=(9.5, 4.2)):
    series = _collect_series(imp_rows, imp_mapping, exp_rows, exp_mapping, wits_rows, wits_mapping)
    our_price = num(manual.get("price")) if manual else None

    if not series and our_price is None:
        return None

    bg = "#12161b" if dark else "#ffffff"
    fg = "#e7ecf2" if dark else "#1a1a1a"
    grid = "#232a33" if dark else "#e5e5e5"

    fig = Figure(figsize=figsize, dpi=150)
    ax = fig.add_subplot(111)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    for _key, label, color, points in series:
        dates = [p["date"] for p in points]
        prices = [p["price"] for p in points]
        ax.plot(dates, prices, color=color, linewidth=2, marker="o", markersize=4,
                 label=f"{label} ({len(points)} shipment{'s' if len(points) != 1 else ''})")

    if our_price is not None:
        ax.axhline(our_price, color=fg, linestyle="--", linewidth=1.4, alpha=0.85,
                    label=f"Our price: {our_price}")

    ax.set_xlabel("Shipment date", color=fg, fontsize=9)
    ax.set_ylabel("Unit price", color=fg, fontsize=9)
    ax.tick_params(colors=fg, labelsize=8)
    ax.grid(True, color=grid, linewidth=0.7)
    for spine in ax.spines.values():
        spine.set_color(grid)
    if series:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        fig.autofmt_xdate(rotation=0, ha="center")
    legend = ax.legend(loc="upper left", fontsize=8, frameon=False, labelcolor=fg)
    fig.tight_layout()
    return fig


def trend_png_bytes(*args, **kwargs):
    fig = build_trend_figure(*args, dark=False, figsize=(10, 4), **kwargs)
    if fig is None:
        return None
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    return buf.getvalue()
