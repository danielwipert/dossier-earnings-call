"""
Chorus AI Systems — Financial Trend Chart
Bloomberg / FT print-quality style

Two-panel design:
  Top:    Quarterly revenue — clean bars, value labels centered inside
  Bottom: Operating margin — line with labelled data points
"""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from pathlib import Path

# ── Brand palette ──────────────────────────────────────────────────────────────
NAVY      = "#1A2E4A"
STEEL     = "#3D6199"   # history bars
GOLD      = "#C9A84C"
CHARCOAL  = "#1F2937"
MID_GRAY  = "#6B7280"
GRID      = "#EBEBEB"
GREEN     = "#166534"
RED       = "#991B1B"
WHITE     = "#FFFFFF"


def generate_trend_chart(
    historical_financials: list[dict],
    output_path: str = "trend_chart.png",
    company_name: str = "",
) -> str:
    """Generate a print-quality two-panel trend chart PNG."""
    if not historical_financials:
        raise ValueError("No historical financial data to chart")

    quarters, revenues, op_margins = [], [], []
    for snap in historical_financials:
        quarters.append(snap.get("quarter_label", "?"))
        revenues.append(_parse_value_to_billions(snap.get("revenue", "")))
        op_margins.append(_parse_pct(snap.get("operating_margin_pct", "")))

    n = len(quarters)
    x = np.arange(n)
    valid_rev  = [r if r is not None else 0 for r in revenues]
    max_rev    = max(valid_rev) if any(r > 0 for r in valid_rev) else 1
    has_margins = any(m is not None for m in op_margins)

    # ── Figure & panels ────────────────────────────────────────────────────────
    if has_margins:
        fig = plt.figure(figsize=(9.5, 4.8), facecolor=WHITE)
        gs  = gridspec.GridSpec(
            2, 1, figure=fig,
            height_ratios=[2.6, 1.0],
            hspace=0.0,
        )
        ax1 = fig.add_subplot(gs[0])
        ax2 = fig.add_subplot(gs[1])
    else:
        fig, ax1 = plt.subplots(1, 1, figsize=(9.5, 3.0), facecolor=WHITE)
        ax2 = None

    # ── Revenue bars ───────────────────────────────────────────────────────────
    ax1.set_facecolor(WHITE)

    # Lighter steel for history, navy for current quarter
    bar_colors = [STEEL] * (n - 1) + [NAVY]
    bars = ax1.bar(
        x, valid_rev, color=bar_colors, width=0.58,
        zorder=2, linewidth=0,
    )

    # Value labels: inside bar if tall enough, above otherwise
    for i, (bar, rev) in enumerate(zip(bars, revenues)):
        if rev is None or rev == 0:
            continue
        label = f"${rev:.2f}B" if rev >= 1 else f"${rev * 1000:.0f}M"
        bar_h = bar.get_height()
        bx    = bar.get_x() + bar.get_width() / 2
        if bar_h > max_rev * 0.18:
            ax1.text(bx, bar_h * 0.52, label,
                     ha="center", va="center",
                     fontsize=9, color=WHITE, fontweight="bold",
                     fontfamily="sans-serif")
        else:
            ax1.text(bx, bar_h + max_rev * 0.015, label,
                     ha="center", va="bottom",
                     fontsize=8.5, color=CHARCOAL, fontweight="bold",
                     fontfamily="sans-serif")

    # "CURRENT" callout on the right side of the final bar
    last_bar = bars[-1]
    ax1.annotate(
        "CURRENT",
        xy=(last_bar.get_x() + last_bar.get_width(), valid_rev[-1] * 0.5),
        xytext=(last_bar.get_x() + last_bar.get_width() + 0.18, valid_rev[-1] * 0.5),
        ha="left", va="center",
        fontsize=7, color=GOLD, fontweight="bold", fontfamily="sans-serif",
        arrowprops=dict(arrowstyle="-", color=GOLD, lw=0.7),
    )

    ax1.set_xlim(-0.55, n - 0.28)
    ax1.set_ylim(0, max_rev * 1.22)

    # Clean axes
    ax1.set_yticks([])
    ax1.yaxis.set_visible(False)
    _light_gridlines(ax1, max_rev, n_lines=4)

    ax1.set_xticks(x)
    if has_margins:
        ax1.tick_params(axis='x', labelbottom=False, length=0)
    else:
        ax1.set_xticklabels(quarters, fontsize=9, color=CHARCOAL,
                             fontfamily="sans-serif")
        ax1.tick_params(axis='x', length=0)

    _clean_spines(ax1, bottom_color=GRID)

    # Panel label
    ax1.text(0.012, 0.97, "QUARTERLY REVENUE",
             transform=ax1.transAxes, ha="left", va="top",
             fontsize=7.5, color=MID_GRAY, fontweight="bold",
             fontfamily="sans-serif")

    # ── Operating margin panel ─────────────────────────────────────────────────
    if has_margins and ax2 is not None:
        ax2.set_facecolor(WHITE)

        vx = [xi for xi, m in zip(x, op_margins) if m is not None]
        vm = [m  for m  in op_margins if m is not None]

        if vx:
            ax2.plot(vx, vm, color=NAVY, linewidth=1.6, zorder=3,
                     marker="o", markersize=5.5,
                     markerfacecolor=NAVY, markeredgewidth=0)

            # Gold marker on current quarter
            ax2.plot(vx[-1], vm[-1], "o",
                     color=GOLD, markersize=7.5, zorder=4, markeredgewidth=0)

            # Value labels — always place ABOVE the dot so they never clash with x-axis
            y_span = max(vm) - min(vm) if len(vm) > 1 else 10
            pad    = max(y_span * 0.20, 2.5)
            for xi, m in zip(vx, vm):
                sign  = "+" if m >= 0 else ""
                color = GREEN if m >= 0 else RED
                ax2.text(xi, m + pad, f"{sign}{m:.1f}%",
                         ha="center", va="bottom",
                         fontsize=8, color=color, fontweight="bold",
                         fontfamily="sans-serif")

        # Zero baseline
        ax2.axhline(0, color=CHARCOAL, linewidth=0.9, zorder=2)

        # Y limits: enough headroom above for labels, padding below for negative labels
        all_m = [m for m in vm if m is not None] if vx else [0]
        y_min = min(all_m) if all_m else -5
        y_max = max(all_m) if all_m else 5
        y_span_full = max(y_max - y_min, 5)
        ax2.set_ylim(y_min - y_span_full * 0.55, y_max + y_span_full * 0.65)

        # Tidy axes
        ax2.set_xlim(-0.55, n - 0.28)
        ax2.set_xticks(x)
        ax2.set_xticklabels(quarters, fontsize=9, color=CHARCOAL,
                             fontfamily="sans-serif")
        ax2.tick_params(axis='x', length=0, pad=6)
        ax2.set_yticks([])
        ax2.yaxis.set_visible(False)

        _clean_spines(ax2, top_color=GRID, bottom_color=GRID)

        ax2.text(0.012, 0.97, "OP. MARGIN",
                 transform=ax2.transAxes, ha="left", va="top",
                 fontsize=7.5, color=MID_GRAY, fontweight="bold",
                 fontfamily="sans-serif")

    # ── Save ───────────────────────────────────────────────────────────────────
    plt.savefig(output_path, dpi=220, bbox_inches="tight",
                facecolor=WHITE, edgecolor="none")
    plt.close()
    return output_path


# ── Helpers ────────────────────────────────────────────────────────────────────

def _light_gridlines(ax, max_val, n_lines=4):
    for g in np.linspace(0, max_val, n_lines + 1)[1:]:
        ax.axhline(g, color=GRID, linewidth=0.7, zorder=0)


def _clean_spines(ax, top_color=None, bottom_color=None):
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    if top_color:
        ax.spines["top"].set_color(top_color)
    else:
        ax.spines["top"].set_visible(False)
    if bottom_color:
        ax.spines["bottom"].set_color(bottom_color)
    else:
        ax.spines["bottom"].set_visible(False)


def _parse_value_to_billions(s: str) -> float | None:
    if not s:
        return None
    s = s.replace("$", "").replace(",", "").strip()
    try:
        if s.upper().endswith("B"):
            return float(s[:-1])
        elif s.upper().endswith("M"):
            return float(s[:-1]) / 1000
        elif s.upper().endswith("K"):
            return float(s[:-1]) / 1_000_000
        else:
            return float(s) / 1e9
    except ValueError:
        return None


def _parse_pct(s: str) -> float | None:
    if not s:
        return None
    s = s.replace("%", "").replace("+", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


# ── CLI test ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_data = [
        {"quarter_label": "Q4 FY2024", "revenue": "$1.39B", "revenue_yoy_pct": None,   "operating_margin_pct": "-10.0%"},
        {"quarter_label": "Q1 FY2025", "revenue": "$1.41B", "revenue_yoy_pct": None,   "operating_margin_pct": "-3.3%"},
        {"quarter_label": "Q2 FY2025", "revenue": "$1.51B", "revenue_yoy_pct": None,   "operating_margin_pct": "+10.0%"},
        {"quarter_label": "Q3 FY2025", "revenue": "$1.14B", "revenue_yoy_pct": None,   "operating_margin_pct": "-23.8%"},
    ]
    path = generate_trend_chart(
        historical_financials=test_data,
        output_path="test_trend_chart.png",
        company_name="DraftKings Inc."
    )
    print(f"Chart saved: {path}")
