"""
Chorus AI Systems — Earnings Call Dossier
Report Formatter v1.0

The Python wrapper you actually call. Takes the pipeline's report_output.json
and produces a finished Word doc (.docx) matching the Chorus AI template.

Steps it runs internally:
  1. Generates the radar chart PNG (generate_radar_chart.py)
  2. Calls the docx formatter (format_report.js via Node.js)
  3. Cleans up temp files

Usage:
    from report_formatter import format_report
    docx_path = format_report("report_output.json", "MSFT_Q2_FY2026_Brief.docx")

    # Command line:
    python report_formatter.py --input report_output.json --output MSFT_Q2_FY2026.docx
"""

import json
import os
import subprocess
import tempfile
import argparse
import sys
from pathlib import Path

# Force UTF-8 output on Windows so ✓/✗ characters print correctly
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))

from generate_radar_chart import generate_radar_chart, DIMENSION_KEYS


def format_report(
    report_json_path: str,
    output_docx_path: str = None,
) -> str:
    """
    Convert a pipeline report_output.json into a formatted Word doc.

    Args:
        report_json_path: Path to the JSON file produced by pipeline.py
        output_docx_path: Where to save the .docx file.
                          Defaults to same directory as the JSON, named after
                          the company and quarter.

    Returns:
        The path to the saved .docx file.
    """
    # Load the report data
    report_path = Path(report_json_path)
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_json_path}")

    with open(report_path, "r", encoding="utf-8") as f:
        report_data = json.load(f)

    # Check the pipeline didn't halt
    if report_data.get("status") == "halted":
        raise ValueError(
            "Cannot format a halted pipeline output. "
            "The pipeline did not produce a report — check the run log for the halt reason."
        )

    # The pipeline wraps report content under a "report" key
    _report = report_data.get("report", report_data)
    snapshot = _report.get("snapshot", {})
    radar_scores = _report.get("radar_scores", {})

    # Auto-generate output filename if not provided
    if not output_docx_path:
        company = snapshot.get("ticker", "report").split()[0].replace("/", "-")
        quarter = snapshot.get("quarter", "").replace(" ", "_")
        output_docx_path = str(report_path.parent / f"{company}_{quarter}_Brief.docx")

    print(f"\nFormatting report: {report_json_path}")
    print(f"Output:            {output_docx_path}")

    # -------------------------------------------------------------------------
    # Step 1: Generate radar chart PNG
    # -------------------------------------------------------------------------
    print("\nStep 1: Generating radar chart...")

    # Extract current quarter scores
    current_scores = {}
    if radar_scores.get("dimension_scores"):
        for d in radar_scores["dimension_scores"]:
            current_scores[d["dimension"]] = d["published_score"]

    # Quarter labels
    quarter_label = snapshot.get("quarter", "Current Quarter")

    # Generate chart to a temp file
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        chart_path = tmp.name

    try:
        generate_radar_chart(
            scores=current_scores,
            output_path=chart_path,
            quarter_label=quarter_label,
        )
        print(f"  ✓ Radar chart saved to temp file")

        # -------------------------------------------------------------------------
        # Step 2: Write the report data to a temp JSON for the JS formatter
        # The formatter needs only the report's inner data, not the full wrapper
        # -------------------------------------------------------------------------
        print("\nStep 2: Building Word document...")

        # The pipeline wraps everything under a "report" key
        report = report_data.get("report", report_data)
        formatter_input = {
            "snapshot":     report.get("snapshot", {}),
            "sections":     report.get("sections", {}),
            "radar_scores": report.get("radar_scores", {}),
            "verification": report.get("verification", {}),
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp_json:
            json.dump(formatter_input, tmp_json, indent=2)
            formatter_json_path = tmp_json.name

        try:
            # Find format_report.js (same directory as this script)
            script_dir = Path(__file__).parent
            js_formatter = script_dir / "format_report.js"

            if not js_formatter.exists():
                raise FileNotFoundError(
                    f"format_report.js not found at {js_formatter}. "
                    "Make sure format_report.js is in the same folder as report_formatter.py."
                )

            result = subprocess.run(
                ["node", str(js_formatter), formatter_json_path, chart_path, output_docx_path],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"format_report.js failed:\n{result.stderr}\n{result.stdout}"
                )

            print(f"  ✓ {result.stdout.strip()}")

        finally:
            os.unlink(formatter_json_path)

    finally:
        os.unlink(chart_path)

    # Confirm output exists
    output_path = Path(output_docx_path)
    if not output_path.exists():
        raise RuntimeError(f"Formatter ran but output file not found: {output_docx_path}")

    size_kb = output_path.stat().st_size // 1024
    print(f"\n✓ Report complete: {output_docx_path} ({size_kb} KB)")
    return output_docx_path


# =============================================================================
# COMMAND-LINE INTERFACE
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Format a Chorus AI pipeline report as a Word document.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python report_formatter.py --input report_output.json
  python report_formatter.py --input report_output.json --output MSFT_Q2_Brief.docx
        """
    )
    parser.add_argument("--input",  required=True, help="Path to report_output.json from pipeline.py")
    parser.add_argument("--output", default=None,  help="Output .docx path (auto-named if omitted)")
    args = parser.parse_args()

    result_path = format_report(args.input, args.output)
    print(f"\nDone. Open: {result_path}")
