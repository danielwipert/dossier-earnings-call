"""
Chorus AI Systems — Earnings Call Radar Chart
Clean, publication-quality polar chart.

Score labels appear beside each dimension axis label (not floating over the fill),
keeping the interior polygon clean and uncluttered.
"""

import math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path


# Dimension display labels and schema keys (must stay in sync with schemas.py)
DIMENSIONS = [
    "Revenue\nMomentum",
    "Margin\nHealth",
    "Guidance\nConfidence",
    "Mgmt\nTransparency",
    "Strategic\nClarity",
    "Earnings\nQuality",
    "Forward\nVisibility",
]

DIMENSION_KEYS = [
    "revenue_momentum",
    "margin_health",
    "guidance_confidence",
    "mgmt_transparency",
    "strategic_clarity",
    "earnings_quality",
    "forward_visibility",
]

# Brand colors
NAVY        = "#1A2E4A"
NAVY_FILL   = "#1A2E4A"
NAVY_LIGHT  = "#8FA6C8"
GOLD        = "#C9A84C"
GRID_COLOR  = "#D8E0EB"
LABEL_COLOR = "#1A2E4A"
SCORE_COLOR = "#C9A84C"   # gold for current-quarter score labels
WHITE       = "#FFFFFF"
MID_GRAY    = "#6B7280"


def generate_radar_chart(
    scores: dict,
    output_path: str = "radar_chart.png",
    prior_scores: dict = None,
    quarter_label: str = "Current Quarter",
    prior_quarter_label: str = "Prior Quarter",
) -> str:
    """
    Render a 7-axis radar chart with score badges embedded in the axis labels.

    Args:
        scores: mapping dimension_key → published_score (1-10)
        output_path: file path to save the PNG
        prior_scores: optional prior-quarter scores for overlay
        quarter_label: legend label for current quarter
        prior_quarter_label: legend label for prior quarter

    Returns:
        output_path
    """
    n = len(DIMENSION_KEYS)
    angles = [k * 2 * math.pi / n for k in range(n)]
    angles_closed = angles + [angles[0]]

    current_vals  = [float(scores.get(k, 5)) for k in DIMENSION_KEYS]
    current_closed = current_vals + [current_vals[0]]

    prior_vals    = None
    prior_closed  = None
    if prior_scores:
        prior_vals   = [float(prior_scores.get(k, 5)) for k in DIMENSION_KEYS]
        prior_closed = prior_vals + [prior_vals[0]]

    # ── Figure ─────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(5.8, 5.8), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor(WHITE)
    ax.set_facecolor(WHITE)

    # ── Scale rings ────────────────────────────────────────────────────────────
    ax.set_ylim(0, 10)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels([])          # no ring numbers — kept clean
    ax.yaxis.set_tick_params(size=0)
    ax.grid(color=GRID_COLOR, linestyle="-", linewidth=0.6, alpha=0.9)
    ax.spines["polar"].set_visible(False)

    # ── Prior quarter (dashed underlay) ───────────────────────────────────────
    if prior_closed is not None:
        ax.plot(angles_closed, prior_closed,
                color=NAVY_LIGHT, linewidth=1.2,
                linestyle="--", alpha=0.7, zorder=2)
        ax.fill(angles_closed, prior_closed,
                color=NAVY_LIGHT, alpha=0.08, zorder=1)

    # ── Current quarter (solid fill) ──────────────────────────────────────────
    ax.plot(angles_closed, current_closed,
            color=NAVY_FILL, linewidth=2.0,
            linestyle="-", zorder=3)
    ax.fill(angles_closed, current_closed,
            color=NAVY_FILL, alpha=0.20, zorder=2)

    # Vertex dots
    for angle, val in zip(angles, current_vals):
        ax.plot(angle, val, "o",
                color=NAVY_FILL, markersize=6.5, zorder=4,
                markeredgecolor=WHITE, markeredgewidth=1.2)

    # ── Axis labels with embedded score ───────────────────────────────────────
    # Build compound labels: dimension name + score on a new line
    tick_labels = []
    for i, (dim_label, val) in enumerate(zip(DIMENSIONS, current_vals)):
        tick_labels.append(f"{dim_label}\n{int(val)}")

    ax.set_xticks(angles)
    ax.set_xticklabels(tick_labels,
                       fontsize=8.0,
                       color=LABEL_COLOR,
                       fontweight="bold",
                       linespacing=1.5)
    ax.tick_params(axis="x", pad=14)

    # ── Legend ─────────────────────────────────────────────────────────────────
    handles = [
        mpatches.Patch(facecolor=NAVY_FILL, alpha=0.5, label=quarter_label),
    ]
    if prior_closed is not None:
        handles.append(
            mpatches.Patch(facecolor=NAVY_LIGHT, alpha=0.4, label=prior_quarter_label)
        )
    ax.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=2,
        fontsize=8,
        frameon=False,
    )

    # ── Save ───────────────────────────────────────────────────────────────────
    plt.tight_layout()
    plt.savefig(output_path, dpi=220, bbox_inches="tight",
                facecolor=WHITE, edgecolor="none")
    plt.close()
    return output_path


# ── CLI test ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_scores = {
        "revenue_momentum":    8,
        "margin_health":       5,
        "guidance_confidence": 7,
        "mgmt_transparency":   6,
        "strategic_clarity":   8,
        "earnings_quality":    7,
        "forward_visibility":  6,
    }
    test_prior = {
        "revenue_momentum":    7,
        "margin_health":       6,
        "guidance_confidence": 7,
        "mgmt_transparency":   5,
        "strategic_clarity":   7,
        "earnings_quality":    7,
        "forward_visibility":  5,
    }
    path = generate_radar_chart(
        scores=test_scores,
        output_path="test_radar.png",
        prior_scores=test_prior,
        quarter_label="Q4 FY2025",
        prior_quarter_label="Q3 FY2025",
    )
    print(f"Chart saved: {path}")
