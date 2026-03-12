"""
Chorus AI Systems — Earnings Call Dossier
Radar Chart Generator

Generates the 7-dimension radar chart PNG that gets embedded in the Word doc.
Matches the style of the template: solid fill for current quarter, dashed outline
for prior quarter comparison (if prior scores are provided).

Usage:
    from generate_radar_chart import generate_radar_chart
    path = generate_radar_chart(scores, output_path="chart.png", prior_scores=None)
"""

import json
import math
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend — no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path


# Dimension labels in display order (matches template)
DIMENSIONS = [
    "Revenue\nMomentum",
    "Margin\nHealth",
    "Guidance\nConfidence",
    "Mgmt\nTransparency",
    "Strategic\nClarity",
    "Earnings\nQuality",
    "Forward\nVisibility",
]

# Internal key names (match schema.py DimensionScore.dimension field)
DIMENSION_KEYS = [
    "revenue_momentum",
    "margin_health",
    "guidance_confidence",
    "mgmt_transparency",
    "strategic_clarity",
    "earnings_quality",
    "forward_visibility",
]

# Chorus brand colors
COLOR_CURRENT   = "#1B3A6B"   # Deep navy — current quarter fill
COLOR_PRIOR     = "#8FA6C8"   # Muted blue — prior quarter outline
COLOR_GRID      = "#D0D8E4"   # Light gray grid lines
COLOR_LABEL     = "#1B3A6B"   # Label text
COLOR_SCORE     = "#FFFFFF"   # Score text on dots


def generate_radar_chart(
    scores: dict,
    output_path: str = "radar_chart.png",
    prior_scores: dict = None,
    quarter_label: str = "Current Quarter",
    prior_quarter_label: str = "Prior Quarter",
) -> str:
    """
    Generate a radar chart PNG.

    Args:
        scores: dict mapping dimension key → published_score (1-10)
                e.g. {"revenue_momentum": 8, "margin_health": 6, ...}
        output_path: where to save the PNG
        prior_scores: optional dict of prior quarter scores for comparison overlay
        quarter_label: label for the current quarter in the legend
        prior_quarter_label: label for the prior quarter in the legend

    Returns:
        The output_path string (for easy chaining into the formatter)
    """
    n = len(DIMENSION_KEYS)
    angles = [k * 2 * math.pi / n for k in range(n)]
    angles_closed = angles + [angles[0]]  # Close the polygon

    # Extract scores in dimension order, default to 5 if missing
    current_vals = [scores.get(k, 5) for k in DIMENSION_KEYS]
    current_closed = current_vals + [current_vals[0]]

    if prior_scores:
        prior_vals = [prior_scores.get(k, 5) for k in DIMENSION_KEYS]
        prior_closed = prior_vals + [prior_vals[0]]

    # -------------------------------------------------------------------------
    # Figure setup
    # -------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    # -------------------------------------------------------------------------
    # Grid rings (1–10 scale, draw rings at 2, 4, 6, 8, 10)
    # -------------------------------------------------------------------------
    ax.set_ylim(0, 10)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(["2", "4", "6", "8", "10"], fontsize=7, color="#888888")
    ax.yaxis.set_tick_params(labelsize=7)

    # Style the grid
    ax.grid(color=COLOR_GRID, linestyle='-', linewidth=0.8, alpha=0.8)
    ax.spines['polar'].set_visible(False)

    # -------------------------------------------------------------------------
    # Prior quarter overlay (dashed, drawn first so current sits on top)
    # -------------------------------------------------------------------------
    if prior_scores:
        ax.plot(
            angles_closed, prior_closed,
            color=COLOR_PRIOR, linewidth=1.5,
            linestyle='--', alpha=0.85, zorder=2
        )
        ax.fill(
            angles_closed, prior_closed,
            color=COLOR_PRIOR, alpha=0.10, zorder=1
        )

    # -------------------------------------------------------------------------
    # Current quarter — solid fill
    # -------------------------------------------------------------------------
    ax.plot(
        angles_closed, current_closed,
        color=COLOR_CURRENT, linewidth=2.0,
        linestyle='-', zorder=3
    )
    ax.fill(
        angles_closed, current_closed,
        color=COLOR_CURRENT, alpha=0.25, zorder=2
    )

    # Score dots on each vertex
    for angle, val in zip(angles, current_vals):
        ax.plot(angle, val, 'o',
                color=COLOR_CURRENT, markersize=8, zorder=4)

    # -------------------------------------------------------------------------
    # Dimension labels
    # -------------------------------------------------------------------------
    ax.set_xticks(angles)
    ax.set_xticklabels(DIMENSIONS, fontsize=8.5, color=COLOR_LABEL,
                       fontweight='bold', linespacing=1.3)

    # Padding between chart edge and labels
    ax.tick_params(axis='x', pad=12)

    # -------------------------------------------------------------------------
    # Legend
    # -------------------------------------------------------------------------
    legend_elements = [
        mpatches.Patch(facecolor=COLOR_CURRENT, alpha=0.6, label=quarter_label),
    ]
    if prior_scores:
        legend_elements.append(
            mpatches.Patch(facecolor=COLOR_PRIOR, alpha=0.4,
                           linestyle='--', label=prior_quarter_label)
        )

    ax.legend(
        handles=legend_elements,
        loc='lower center',
        bbox_to_anchor=(0.5, -0.13),
        ncol=2,
        fontsize=8,
        frameon=False,
    )

    # -------------------------------------------------------------------------
    # Score annotations on each spoke
    # -------------------------------------------------------------------------
    for angle, val, key in zip(angles, current_vals, DIMENSION_KEYS):
        # Offset the score label slightly outward from the dot
        offset = 0.8
        ax.annotate(
            str(val),
            xy=(angle, val),
            xytext=(angle, val + offset),
            ha='center', va='center',
            fontsize=7.5, fontweight='bold',
            color=COLOR_CURRENT,
            zorder=5
        )

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close()

    return output_path


# =============================================================================
# CLI for testing
# python generate_radar_chart.py
# =============================================================================

if __name__ == "__main__":
    # Test with sample scores matching the MSFT template
    test_scores = {
        "revenue_momentum":    8,
        "margin_health":       6,
        "guidance_confidence": 7,
        "mgmt_transparency":   5,
        "strategic_clarity":   8,
        "earnings_quality":    7,
        "forward_visibility":  6,
    }
    test_prior = {
        "revenue_momentum":    7,
        "margin_health":       7,
        "guidance_confidence": 8,
        "mgmt_transparency":   7,
        "strategic_clarity":   7,
        "earnings_quality":    8,
        "forward_visibility":  7,
    }

    path = generate_radar_chart(
        scores=test_scores,
        output_path="/tmp/test_radar.png",
        prior_scores=test_prior,
        quarter_label="Q2 FY2026",
        prior_quarter_label="Q1 FY2026"
    )
    print(f"Chart saved to: {path}")
