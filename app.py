"""
Chorus AI Systems — Earnings Call Intelligence
Streamlit GUI — upload a transcript PDF, run the pipeline, download the brief.
"""

import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import fitz          # PyMuPDF — extract text from PDF
import streamlit as st

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Chorus AI · Earnings Intelligence",
    page_icon="📊",
    layout="centered",
)

# ── Brand CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Background */
  .stApp { background: #F8F9FB; }

  /* Hide default Streamlit chrome */
  #MainMenu, footer, header { visibility: hidden; }

  /* Masthead */
  .chorus-header {
    background: #1A2E4A;
    border-radius: 8px;
    padding: 28px 36px 22px;
    margin-bottom: 28px;
  }
  .chorus-header h1 {
    color: #FFFFFF;
    font-size: 1.9rem;
    font-weight: 800;
    margin: 0 0 4px;
    letter-spacing: -0.5px;
  }
  .chorus-header p {
    color: #C9A84C;
    font-size: 0.85rem;
    margin: 0;
    letter-spacing: 1px;
    text-transform: uppercase;
    font-weight: 600;
  }

  /* Section card */
  .card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 22px 26px;
    margin-bottom: 18px;
  }
  .card-title {
    font-size: 0.72rem;
    font-weight: 700;
    color: #6B7280;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 14px;
  }

  /* Log output */
  .log-box {
    background: #0F172A;
    color: #94A3B8;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 0.78rem;
    border-radius: 6px;
    padding: 16px;
    height: 320px;
    overflow-y: auto;
    white-space: pre-wrap;
    line-height: 1.55;
  }

  /* Status pills */
  .pill-running  { background:#DBEAFE; color:#1D4ED8; padding:4px 12px; border-radius:999px; font-size:0.78rem; font-weight:700; }
  .pill-done     { background:#DCFCE7; color:#166534; padding:4px 12px; border-radius:999px; font-size:0.78rem; font-weight:700; }
  .pill-error    { background:#FEE2E2; color:#991B1B; padding:4px 12px; border-radius:999px; font-size:0.78rem; font-weight:700; }
  .pill-idle     { background:#F3F4F6; color:#6B7280; padding:4px 12px; border-radius:999px; font-size:0.78rem; font-weight:700; }
</style>
""", unsafe_allow_html=True)

# ── Masthead ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="chorus-header">
  <h1>Chorus AI</h1>
  <p>Earnings Call Intelligence · Upload · Analyse · Download</p>
</div>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract plain text from a PDF using PyMuPDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n\n".join(pages)


def stream_subprocess(cmd: list[str], cwd: str, log_queue: queue.Queue) -> int:
    """Run a subprocess and push stdout+stderr lines into log_queue. Returns exit code."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )
    for line in proc.stdout:
        log_queue.put(line.rstrip())
    proc.wait()
    return proc.returncode


def run_pipeline_thread(
    transcript_path: str,
    ticker: str,
    year: int | None,
    quarter: int | None,
    peers: str,
    skip_context: bool,
    output_json: str,
    log_queue: queue.Queue,
    result_box: dict,
):
    """Background thread: runs pipeline.py then report_formatter.py."""
    project_root = str(Path(__file__).parent)
    python = sys.executable

    # Build pipeline command
    cmd = [python, "pipeline.py", "--transcript", transcript_path, "--output", output_json]
    if ticker:
        cmd += ["--ticker", ticker.upper()]
    if year:
        cmd += ["--year", str(year)]
    if quarter:
        cmd += ["--quarter", str(quarter)]
    if peers.strip():
        cmd += ["--peers", peers.strip()]
    if skip_context:
        cmd.append("--no-context")

    log_queue.put("━" * 60)
    log_queue.put("▶  PIPELINE STARTING")
    log_queue.put("━" * 60)

    rc = stream_subprocess(cmd, project_root, log_queue)

    if rc != 0:
        log_queue.put("\n✗ Pipeline exited with errors (see above).")
        result_box["status"] = "error"
        log_queue.put("__DONE__")
        return

    log_queue.put("\n━" * 60)
    log_queue.put("▶  FORMATTING REPORT")
    log_queue.put("━" * 60)

    # Determine output PDF path from JSON filename
    json_path = Path(output_json)
    pdf_path = str(json_path.with_suffix(".pdf"))

    fmt_cmd = [python, "formatter/report_formatter.py", "--input", output_json, "--output", pdf_path]
    rc2 = stream_subprocess(fmt_cmd, project_root, log_queue)

    if rc2 != 0 or not Path(pdf_path).exists():
        log_queue.put("\n✗ Formatter failed (see above).")
        result_box["status"] = "error"
    else:
        log_queue.put(f"\n✓ Brief ready: {pdf_path}")
        result_box["status"] = "done"
        result_box["pdf_path"] = pdf_path

    log_queue.put("__DONE__")


# ── Session state ─────────────────────────────────────────────────────────────
for key, default in [
    ("run_status", "idle"),   # idle | running | done | error
    ("log_lines", []),
    ("pdf_path", None),
    ("log_queue", None),
    ("result_box", {}),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ── Upload card ──────────────────────────────────────────────────────────────
st.markdown('<div class="card"><div class="card-title">Transcript PDF</div>', unsafe_allow_html=True)
uploaded = st.file_uploader(
    "Drag and drop an earnings call transcript PDF",
    type=["pdf"],
    label_visibility="collapsed",
)
st.markdown("</div>", unsafe_allow_html=True)

# ── Options card ─────────────────────────────────────────────────────────────
st.markdown('<div class="card"><div class="card-title">Options</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    ticker_input = st.text_input("Ticker (optional — enables financial context)", placeholder="e.g. MSFT")
with col2:
    year_input = st.number_input("Year", min_value=2000, max_value=2099, value=None, placeholder="2025")
with col3:
    quarter_input = st.selectbox("Quarter", [None, 1, 2, 3, 4], format_func=lambda x: "—" if x is None else f"Q{x}")

peers_input = st.text_input("Peer tickers for competitive intelligence (comma-separated)", placeholder="e.g. YUM,QSR,SBUX")
skip_ctx = st.toggle("Skip context assembly (faster — no historical/peer data)", value=False)
st.markdown("</div>", unsafe_allow_html=True)

# ── Run button ────────────────────────────────────────────────────────────────
run_disabled = uploaded is None or st.session_state.run_status == "running"
run_clicked  = st.button("▶  Run Pipeline", disabled=run_disabled, use_container_width=True, type="primary")

if run_clicked and uploaded is not None:
    # Reset state
    st.session_state.run_status = "running"
    st.session_state.log_lines  = []
    st.session_state.pdf_path   = None
    st.session_state.result_box = {}

    # Write PDF text to a temp file
    pdf_bytes = uploaded.read()
    transcript_text = extract_text_from_pdf(pdf_bytes)

    tmp_dir = Path("outputs")
    tmp_dir.mkdir(exist_ok=True)
    safe_name = Path(uploaded.name).stem.replace(" ", "_")
    transcript_tmp = str(tmp_dir / f"_upload_{safe_name}.txt")
    output_json    = str(tmp_dir / f"{safe_name}_report.json")

    with open(transcript_tmp, "w", encoding="utf-8") as f:
        f.write(transcript_text)

    # Spin up background thread
    q = queue.Queue()
    st.session_state.log_queue = q
    thread = threading.Thread(
        target=run_pipeline_thread,
        kwargs=dict(
            transcript_path=transcript_tmp,
            ticker=ticker_input or "",
            year=int(year_input) if year_input else None,
            quarter=quarter_input,
            peers=peers_input or "",
            skip_context=skip_ctx,
            output_json=output_json,
            log_queue=q,
            result_box=st.session_state.result_box,
        ),
        daemon=True,
    )
    thread.start()
    st.rerun()

# ── Status + log ──────────────────────────────────────────────────────────────
status = st.session_state.run_status

if status != "idle":
    # Drain the queue into log_lines
    q = st.session_state.log_queue
    if q:
        while True:
            try:
                line = q.get_nowait()
                if line == "__DONE__":
                    # Thread finished — pick up final status
                    st.session_state.run_status = st.session_state.result_box.get("status", "error")
                    st.session_state.pdf_path   = st.session_state.result_box.get("pdf_path")
                    st.session_state.log_queue  = None
                    break
                st.session_state.log_lines.append(line)
            except queue.Empty:
                break

    # Pill
    pill_map = {
        "running": ('<span class="pill-running">⟳ Running…</span>', True),
        "done":    ('<span class="pill-done">✓ Complete</span>', False),
        "error":   ('<span class="pill-error">✗ Failed</span>', False),
    }
    pill_html, still_running = pill_map.get(st.session_state.run_status, ("", False))
    st.markdown(f"**Status** &nbsp; {pill_html}", unsafe_allow_html=True)
    st.markdown("")

    # Log box
    log_text = "\n".join(st.session_state.log_lines[-300:])  # cap at 300 lines
    st.markdown(f'<div class="log-box">{log_text}</div>', unsafe_allow_html=True)

    # Auto-refresh while running
    if still_running:
        time.sleep(0.4)
        st.rerun()

# ── Download ──────────────────────────────────────────────────────────────────
if st.session_state.run_status == "done" and st.session_state.pdf_path:
    pdf_path = Path(st.session_state.pdf_path)
    if pdf_path.exists():
        st.markdown("---")
        with open(pdf_path, "rb") as f:
            pdf_bytes_out = f.read()
        st.download_button(
            label="⬇  Download Earnings Brief (PDF)",
            data=pdf_bytes_out,
            file_name=pdf_path.name,
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )
