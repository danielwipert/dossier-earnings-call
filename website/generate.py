"""
Generate the Earnings Call Dossier static site into docs/.

Usage:
    python website/generate.py

Output:
    docs/index.html
    docs/static/css/style.css
"""

import os
import shutil
from jinja2 import Environment, FileSystemLoader

# ── Paths ────────────────────────────────────────────────────────────────────

HERE     = os.path.dirname(os.path.abspath(__file__))
REPO     = os.path.dirname(HERE)
TEMPLATES = os.path.join(HERE, "templates")
STATIC   = os.path.join(HERE, "static")
OUT_DIR  = os.path.join(REPO, "docs")

# ── Site data ────────────────────────────────────────────────────────────────

DATA = {
    "page_title":       "Earnings Call Dossier — Chorus AI Systems",
    "meta_description": (
        "A multi-agent Python pipeline that transforms earnings call transcripts "
        "into verified analytical briefs styled after Financial Times / Lex editorial quality."
    ),
    "github_url": "https://github.com/danielwipert/dossier.ec",

    "nav_links": [
        {"href": "#output",       "label": "Output"},
        {"href": "#principles",   "label": "Principles"},
        {"href": "#pipeline",     "label": "Pipeline"},
        {"href": "#verification", "label": "Verification"},
        {"href": "#theory",       "label": "Theory"},
        {"href": "#models",       "label": "Models"},
    ],

    "hero": {
        "tag": "Chorus AI Systems — v1",
        "headline": "Earnings call intelligence,<br><em>grounded in fact.</em>",
        "subheadline": (
            "A multi-agent pipeline that transforms any earnings call transcript into a "
            "verified analytical brief. Every claim traces back to a verbatim quote. "
            "Nothing advances between stages without a governance gate."
        ),
        "stats": [
            {"value": "9",    "label": "Pipeline stages"},
            {"value": "3",    "label": "Verification gates"},
            {"value": "3",    "label": "Model families"},
            {"value": "≥90%", "label": "Gate 2 pass threshold"},
            {"value": "7",    "label": "Fact types extracted"},
            {"value": "0",    "label": "Investment advice allowed"},
        ],
    },

    "output_sections": [
        {"name": "Editorial Commentary",       "source": "S6 — The Lex Writer"},
        {"name": "Business Narrative",         "source": "S2a"},
        {"name": "Signals & Thesis",           "source": "S2b"},
        {"name": "Management Gaps",            "source": "S2c"},
        {"name": "Competitive Positioning",    "source": "S2f"},
        {"name": "Financial Snapshot",         "source": "S1b"},
        {"name": "Radar Chart (7 dimensions)", "source": "formatter"},
        {"name": "Business Principles",        "source": "S7 — FAISS + textbooks"},
        {"name": "Verification Notes",         "source": "Gate 2 + S5"},
    ],

    "principles": [
        {
            "name": "No unverified output",
            "desc": (
                "If the verification pipeline is unavailable, halt. There is no fallback to "
                "unverified generation. A system that sometimes verifies is not a verified system."
            ),
        },
        {
            "name": "FactList immutability",
            "desc": (
                "The FactList is locked after Gate 1a passes. No downstream agent may add, "
                "modify, or remove facts. Trust is established once and cannot be retroactively altered."
            ),
        },
        {
            "name": "Multi-family verification",
            "desc": (
                "Generation and verification always use different model families. A model that "
                "generates a hallucination and verifies it is structurally equivalent to no verification."
            ),
        },
        {
            "name": "No investment advice",
            "desc": (
                "S5 scans for buy / sell / hold language. If found, immediate Level 3 halt — "
                "no report released. The system produces analysis, never recommendations."
            ),
        },
        {
            "name": "Verbatim grounding",
            "desc": (
                "Every FactList entry requires a character-exact verbatim_quote from the transcript. "
                "If a quote cannot be confirmed, the fact is rejected at Gate 1a — not softened."
            ),
        },
        {
            "name": "Observed observation",
            "desc": (
                "Every report discloses what the verification system can and cannot catch. "
                "The system observes its own observation process — a second-order cybernetic commitment."
            ),
        },
    ],

    "pipeline_stages": [
        {
            "id":          "S0",
            "name":        "Context Assembly",
            "is_gate":     False,
            "model":       "Llama-4-Maverick",
            "description": (
                "Fetches historical financials (3 prior quarters via yfinance), post-earnings stock "
                "price reaction, EPS consensus estimates (Alpha Vantage), prior quarter transcript "
                "summaries from SEC EDGAR, and peer company summaries. Non-blocking — missing data "
                "is logged but never halts the pipeline."
            ),
            "input":  "ticker, year, quarter, peers",
            "output": "context_bundle",
            "rule":   None,
        },
        {
            "id":          "S1a",
            "name":        "Fact Extractor",
            "is_gate":     False,
            "model":       "Llama-4-Maverick",
            "description": (
                "Three targeted passes over the transcript. Pass 1: financial_metric, forward_guidance. "
                "Pass 2: management_statement, operational_metric. Pass 3: analyst_question, "
                "competitive_reference, prior_quarter_reference. Each fact requires a character-exact "
                "verbatim_quote and named speaker. Duplicates removed by quote matching."
            ),
            "input":  "transcript",
            "output": "FactList (provisional)",
            "rule":   None,
        },
        {
            "id":          "⊘ Gate 1a",
            "name":        "FactList Validation",
            "is_gate":     True,
            "model":       "Mistral-Small-24B",
            "description": (
                "Validates every FactList entry: quote exists verbatim in transcript, speaker is "
                "named, fact type is correct. ≥90%: proceed. 80–89%: strip failing facts, proceed "
                "at Level 1 degradation. <80%: hard halt. After this gate passes, the FactList is "
                "immutable."
            ),
            "input":  "FactList, transcript",
            "output": "locked FactList",
            "rule":   "<80% fidelity → halt",
        },
        {
            "id":          "S1b",
            "name":        "Structured Data Pull",
            "is_gate":     False,
            "model":       "Llama-4-Maverick",
            "description": (
                "Reads the locked FactList and produces the financial snapshot: key metrics table "
                "with YoY changes and vs-estimate comparisons, headline, and 3–5 key takeaways. "
                "Sector classification overridden with authoritative yfinance GICS data."
            ),
            "input":  "locked FactList, context_bundle",
            "output": "financial_snapshot",
            "rule":   None,
        },
        {
            "id":          "S2a–S2f",
            "name":        "Analysis Agents (parallel)",
            "is_gate":     False,
            "model":       "Llama-4-Maverick",
            "description": (
                "Four agents run simultaneously via asyncio.gather(): S2a Business Narrative "
                "(strategic context, execution), S2b Signals & Thesis (investment themes, risks, "
                "catalysts), S2c Management Gaps (deflected questions, unfulfilled commitments), "
                "S2f Competitive Intelligence (peer benchmarking). Every claim must declare its "
                "type: grounded, derived, or interpretive."
            ),
            "input":  "transcript, locked FactList, context_bundle",
            "output": "sections: S2a, S2b, S2c, S2f",
            "rule":   None,
        },
        {
            "id":          "⊘ Gate 2",
            "name":        "Fact Verifier",
            "is_gate":     True,
            "model":       "Mistral-Small-24B",
            "description": (
                "Runs per section. For each claim, checks whether cited FactList facts actually "
                "support it: aligned, absent, or contradicted. Pass condition: grounding_score ≥ 0.90 "
                "AND contradiction_count == 0. Interpretive claims auto-pass. S2c anchor claims "
                "citing analyst_question or prior_quarter_reference auto-pass. Fail → retry up to "
                "2× with failure summary → omit section."
            ),
            "input":  "S2 sections, locked FactList",
            "output": "verified sections + grounding scores",
            "rule":   "score < 0.90 or contradiction → retry/omit",
        },
        {
            "id":          "S6",
            "name":        "Editorial Synthesis",
            "is_gate":     False,
            "model":       "Llama-4-Maverick",
            "description": (
                "Writes the opening commentary in FT Lex style — overarching narrative, paradoxes, "
                "investor implications. Reads all verified S2 sections. Intentionally runs after Gate 2 "
                "so it has access to the complete verified picture. Non-blocking if it fails."
            ),
            "input":  "verified S2 sections",
            "output": "editorial_commentary",
            "rule":   None,
        },
        {
            "id":          "S5",
            "name":        "Holistic Verifier",
            "is_gate":     True,
            "model":       "DeepSeek-V3.1",
            "description": (
                "Cross-section consistency check using a different model family from generation and "
                "Gate 2. Checks for: conflicting claims across sections, mislabeled claim types, "
                "misleading framing of neutral facts, investment advice language. If buy/sell/hold "
                "language is found → immediate halt, no report released."
            ),
            "input":  "all verified sections",
            "output": "consistency verdict",
            "rule":   "investment advice language → halt",
        },
        {
            "id":          "S7",
            "name":        "Business Principles",
            "is_gate":     False,
            "model":       "Llama-4-Maverick + MiniLM-L6-v2",
            "description": (
                "Two-step: (1) LLM generates 6–8 semantic queries from the assembled report, "
                "(2) each query retrieves top-5 chunks from a FAISS textbook index (economics and "
                "business strategy textbooks), (3) LLM writes the Business Principles section citing "
                "retrieved passages. Skipped gracefully if the FAISS index is missing."
            ),
            "input":  "report, FAISS textbook index",
            "output": "econ_expert section",
            "rule":   None,
        },
    ],

    "verify_rules": [
        {
            "status": "pass",
            "desc":   "grounding_score ≥ 0.90 AND contradiction_count == 0 → section passes Gate 2 and is included in the report.",
        },
        {
            "status": "pass",
            "desc":   "interpretive claims auto-pass Gate 2 — editorial judgment is not fact-verifiable. Capped at ~20% of all claims.",
        },
        {
            "status": "pass",
            "desc":   "S2c anchor claims citing analyst_question or prior_quarter_reference facts auto-pass — question existence is the grounding.",
        },
        {
            "status": "retry",
            "desc":   "Gate 2 fail → section is regenerated with a failure summary appended. Retried up to 2×. Gate 2 re-evaluates on each retry.",
        },
        {
            "status": "retry",
            "desc":   "Gate 1a 80–89% fidelity → failing facts stripped, FactList locked at reduced size, pipeline continues at Level 1 degradation.",
        },
        {
            "status": "fail",
            "desc":   "Gate 1a <80% fidelity → hard halt. No partial output. FactList failure poisons everything downstream.",
        },
        {
            "status": "fail",
            "desc":   "S5 detects buy / sell / hold language → immediate Level 3 halt. Report is suppressed, no output released.",
        },
        {
            "status": "fail",
            "desc":   "Section fails all Gate 2 retries → omitted from report. Noted in omitted_sections in the JSON artifact.",
        },
    ],

    "theory": [
        {
            "framework": "Viable System Model",
            "name":      "Multi-layer governance",
            "author":    "Stafford Beer",
            "desc": (
                "Beer's VSM maps five nested management systems that every viable organism must have. "
                "The pipeline maps directly: S1a/S1b are the operational units; Gate 1a and Gate 2 are "
                "the coordination layer; S5 is the intelligence layer watching for systemic inconsistency; "
                "and the design constraints are the policy layer. Each layer governs only what it can see."
            ),
        },
        {
            "framework": "Law of Requisite Variety",
            "name":      "Verification must match generation",
            "author":    "W. Ross Ashby",
            "desc": (
                "Ashby's Law: only variety can destroy variety. A single-model verifier has less variety "
                "than the generation system it checks — it will systematically miss the failure modes it "
                "shares with the generator. Multi-family verification amplifies the controller's variety "
                "to match the full space of generation failures."
            ),
        },
        {
            "framework": "Second-Order Cybernetics",
            "name":      "Observing the observer",
            "author":    "Heinz von Foerster",
            "desc": (
                "Von Foerster: the observer is always part of the system it observes. A verification "
                "system that uses the same model family as generation creates a closed epistemic loop — "
                "the system observes itself and mistakes that for independent confirmation. The structural "
                "diversity requirement and the Verification Notes section (which discloses what the system "
                "cannot catch) are direct implementations of this principle."
            ),
        },
    ],

    "models": [
        {
            "role":    "Generation",
            "model":   "Llama-4-Maverick-17B-128E-Instruct-FP8",
            "stages":  "S0, S1a, S1b, S2a–f, S6, S7",
            "family":  "Meta / Llama",
        },
        {
            "role":    "Verification A",
            "model":   "Mistral-Small-24B-Instruct-2501",
            "stages":  "Gate 1a, Gate 2",
            "family":  "Mistral",
        },
        {
            "role":    "Verification B",
            "model":   "DeepSeek-V3.1",
            "stages":  "S5 (holistic verifier)",
            "family":  "DeepSeek",
        },
        {
            "role":    "Embedding",
            "model":   "all-MiniLM-L6-v2",
            "stages":  "S7 (FAISS retrieval)",
            "family":  "sentence-transformers",
        },
    ],

    "tech_stack": [
        {
            "category": "Orchestration",
            "name":     "Python + asyncio",
            "desc":     "Pipeline orchestration with asyncio.gather() for parallel S2 agents.",
        },
        {
            "category": "LLM API",
            "name":     "Together AI",
            "desc":     "OpenAI-compatible endpoint for all LLM calls. Swap models by changing a config string.",
        },
        {
            "category": "Data contracts",
            "name":     "Pydantic",
            "desc":     "Typed schemas for every inter-stage artifact. Invalid data raises at the boundary, not downstream.",
        },
        {
            "category": "Transcript fetching",
            "name":     "EDGAR / Finnhub / FMP",
            "desc":     "Auto-cascade: tries EDGAR first, then Finnhub, then FMP. Local PDF also supported via PyMuPDF.",
        },
        {
            "category": "Market data",
            "name":     "yfinance + Alpha Vantage",
            "desc":     "Historical financials, stock reaction, EPS consensus estimates for S0 context assembly.",
        },
        {
            "category": "Vector search",
            "name":     "FAISS + sentence-transformers",
            "desc":     "IndexFlatL2 over 500-word overlapping textbook chunks for S7 economic retrieval.",
        },
        {
            "category": "PDF output",
            "name":     "Node.js + docx-js",
            "desc":     "format_report.js builds the Word doc; report_formatter.py converts to PDF.",
        },
        {
            "category": "Charts",
            "name":     "Matplotlib",
            "desc":     "7-dimension radar chart and trend chart, embedded as PNGs in the PDF brief.",
        },
        {
            "category": "GUI",
            "name":     "Streamlit",
            "desc":     "Optional web interface: upload transcript, stream live logs, download PDF.",
        },
    ],
}

# ── Build ─────────────────────────────────────────────────────────────────────

def build():
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=False)
    template = env.get_template("index.html")
    html = template.render(**DATA)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_html = os.path.join(OUT_DIR, "index.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  wrote {out_html}")

    # Copy static assets
    out_static = os.path.join(OUT_DIR, "static")
    if os.path.exists(out_static):
        shutil.rmtree(out_static)
    shutil.copytree(STATIC, out_static)
    print(f"  copied static/ to {out_static}")

    print("Done. Open docs/index.html in a browser to preview.")


if __name__ == "__main__":
    build()
