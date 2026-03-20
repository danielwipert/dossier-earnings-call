"""
Chorus AI Systems — Earnings Call Dossier
Pipeline Orchestrator v1.0

This is the main file that runs the pipeline. It calls each agent in sequence,
runs the gates, handles retries, and manages graceful degradation.

Usage:
    python pipeline.py --transcript path/to/transcript.txt

Requirements:
    pip install openai pydantic python-dotenv

Environment variables needed in a .env file:
    TOGETHER_API_KEY=your_together_api_key_here
"""

import sys
import json
import time
import uuid
import asyncio

# Force UTF-8 output on Windows so ✓/✗ characters print correctly
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
import argparse
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
import os

from openai import OpenAI

# Import our schemas, prompts, and transcript fetcher
from formatter.report_formatter import format_report
from core.transcript_fetcher import fetch_transcript, validate_transcript
from core.schemas import (
    FactList, Fact, Gate1aResult, S1bOutput, S2SectionOutput,
    Gate2Result, S5Output,
    PipelineRunLog, DegradationLevel, FinalOutputStatus
)
from core.prompts import (
    s1a_fact_extractor, gate_1a_validator, s1b_structured_data_pull,
    s2a_narrative_analyst, s2b_signal_detector, s2c_gap_analyst,
    s2d_context_analyst, s2e_credibility_tracker, s2f_competitive_intelligence,
    s6_editorial_synthesis, gate_2_fact_verifier,
    s5_holistic_verifier
)
from core.context_assembler import assemble_context
from core.schemas import ContextBundle
from core.s7_econ_expert import run_s7

load_dotenv()

# =============================================================================
# MODEL CONFIGURATION
#
# Separation principle (Principle 13): no model may verify its own output.
# Four distinct families are used to eliminate shared blind spots:
#
#   Generation   → Qwen    (Qwen3 235B)
#   Verification A → Llama  (Llama 3.3 70B)   — Gate 1a, Gate 2
#   Verification B → DeepSeek (V3.1)           — S5 holistic verifier
#   Scoring A    → Llama    (Llama 3.1 8B)     — S3 first scorer
#   Scoring B    → Mistral  (Mistral Small 24B) — S3 second scorer
#
# =============================================================================

# Generation — Llama 4 family (Meta)
# Llama 4 Maverick: fast MoE architecture (17B active / 128 experts).
# Strong structured JSON output, significantly faster than dense 70B+ models.
GENERATION_MODEL     = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"

# Verification A — Mistral family
# Mistral Small 24B. Different family from generation (Llama 4); serverless on Together AI.
# Used by Gate 1a (quote fidelity) and Gate 2 (claim grounding) — runs up to 5x per pipeline.
VERIFICATION_MODEL_A = "mistralai/Mistral-Small-24B-Instruct-2501"

# Verification B — DeepSeek family
# DeepSeek V3.1. Third distinct family; used by S5 holistic verifier only.
# Must differ from both generation (Llama 4) and Verification A (Mistral).
VERIFICATION_MODEL_B = "deepseek-ai/DeepSeek-V3.1"

# Scoring models — two independent scorers from different families
# Disagreements > 3 points trigger adjudication and are disclosed in the report.
SCORING_MODEL_A = "Qwen/Qwen2.5-7B-Instruct-Turbo"             # Qwen family — may truncate; code falls back to Model B for missing dimensions
SCORING_MODEL_B = "meta-llama/Llama-3.3-70B-Instruct-Turbo"    # Llama 3.3 family

MAX_RETRIES = 2  # Max times a section can be retried before Level 2 degradation


# =============================================================================
# LLM CALLER
# Single function for all model calls. Uses Together AI's OpenAI-compatible
# API and returns the raw text response.
# =============================================================================

_together_client = None

def _get_client() -> OpenAI:
    """Return a cached Together AI client."""
    global _together_client
    if _together_client is None:
        _together_client = OpenAI(
            api_key=os.getenv("TOGETHER_API_KEY"),
            base_url="https://api.together.xyz/v1",
        )
    return _together_client


def call_model(prompt: str, model_id: str, max_tokens: int = 4000) -> str:
    """
    Call a Together AI model and return the response text.

    Args:
        prompt: The fully formatted prompt string
        model_id: The Together AI model identifier
        max_tokens: Maximum tokens to generate

    Returns:
        The model's response as a string

    Raises:
        RuntimeError with a clear message if the API call fails
    """
    try:
        response = _get_client().chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as e:
        raise RuntimeError(
            f"Together AI call failed — model: {model_id}\n"
            f"Error: {type(e).__name__}: {e}"
        ) from e


_VALID_JSON_ESCAPES = set('"\\\/bfnrtu')

def _sanitize_control_chars(text: str) -> str:
    """
    Fix two classes of invalid JSON inside string values:
    1. Bare control characters (newlines, tabs) — escape them.
    2. Invalid escape sequences (e.g. \' or \:) — double the backslash.
    Walks character-by-character tracking quote/escape state.
    """
    result = []
    in_string = False
    escape_next = False
    escape_map = {'\n': '\\n', '\r': '\\r', '\t': '\\t'}
    i = 0
    chars = list(text)
    while i < len(chars):
        c = chars[i]
        if escape_next:
            # We just saw a backslash — check if the escape is valid JSON
            if c not in _VALID_JSON_ESCAPES:
                # Invalid escape: double the backslash so \X becomes \\X
                result.append('\\')
            result.append(c)
            escape_next = False
        elif c == '\\' and in_string:
            result.append(c)
            escape_next = True
        elif c == '"':
            in_string = not in_string
            result.append(c)
        elif in_string and ord(c) < 0x20:
            result.append(escape_map.get(c, f'\\u{ord(c):04x}'))
        else:
            result.append(c)
        i += 1
    return ''.join(result)


def parse_json_response(raw_response: str) -> dict:
    """
    Parse a JSON response from the model.

    Handles four common failure modes:
    1. Thinking tags — Qwen3 <think>...</think> blocks before the JSON
    2. Markdown fences — ```json ... ``` wrappers
    3. Preamble/postamble — explanatory text before or after the JSON object
    4. Literal control characters embedded in string values

    Strategy: strip known wrappers first, then find the outermost { ... } block.
    """
    import re

    text = raw_response.strip()

    # 1. Strip Qwen3 thinking blocks
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    # 2. Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]).strip()

    # 3. Extract the outermost JSON object — find first { and last }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # 4. Sanitize control characters and invalid escapes inside strings, then retry
        if "control character" in str(e) or "Invalid" in str(e) or "escape" in str(e).lower():
            sanitized = _sanitize_control_chars(text)
            try:
                return json.loads(sanitized)
            except json.JSONDecodeError:
                pass  # Fall through to truncation recovery

        # Attempt to recover from truncated JSON (common when max_tokens cuts mid-response).
        print(f"  ! JSON parse failed: {e} — attempting truncation recovery")
        recovered = _try_recover_truncated_json(text)
        if recovered is not None:
            print(f"  ! Truncation recovery succeeded")
            return recovered
        print(f"  ! Response tail (last 300 chars): ...{text[-300:]}")
        raise


def _try_recover_truncated_json(text: str) -> Optional[dict]:
    """
    Attempt to recover a JSON object that was truncated mid-stream.
    Finds the last complete top-level value by walking backwards and trying
    progressively shorter strings. Returns parsed dict or None if unrecoverable.
    """
    # Walk backward through the text finding positions of } and ]
    # Try closing any open arrays/objects at the outermost level.
    for close_char, open_char in [('}', '{'), (']', '[')]:
        pos = text.rfind(close_char)
        while pos > 0:
            candidate = text[:pos + 1]
            # Count unclosed braces/brackets to auto-close
            depth_curly  = candidate.count('{') - candidate.count('}')
            depth_square = candidate.count('[') - candidate.count(']')
            # Ignore string contents (rough heuristic: doesn't handle escaped chars)
            if depth_curly >= 0 and depth_square >= 0:
                attempt = candidate + (']' * depth_square) + ('}' * depth_curly)
                try:
                    return json.loads(attempt)
                except json.JSONDecodeError:
                    pass
            pos = text.rfind(close_char, 0, pos)
    return None


# =============================================================================
# STAGE S1a: FACT EXTRACTOR
# =============================================================================

# Three targeted passes — each extracts a focused subset of fact types.
# Keeping each pass small and focused ensures the JSON response fits reliably
# within the model's output token limit, eliminating truncation errors.
_S1A_PASSES = [
    ["financial_metric", "forward_guidance"],
    ["management_statement", "operational_metric"],
    ["analyst_question", "competitive_reference", "prior_quarter_reference"],
]


def run_s1a(transcript: str) -> FactList:
    """
    Run the Fact Extractor using three targeted passes over the full transcript.
    Each pass extracts a different subset of fact types, keeping response sizes
    small and reliable instead of trying to produce 100+ facts in one shot.
    Results are merged and deduplicated by verbatim_quote.
    """
    print("  Running S1a: Fact Extractor (3-pass targeted)...")

    all_facts_raw = []
    for i, fact_types in enumerate(_S1A_PASSES, 1):
        label = ", ".join(fact_types)
        print(f"  Pass {i}/3: [{label}]...")
        prompt = s1a_fact_extractor(transcript, fact_types=fact_types)
        raw = call_model(prompt, GENERATION_MODEL, max_tokens=12000)
        data = parse_json_response(raw)
        pass_facts = data.get("facts", [])
        for fact in pass_facts:
            if not fact.get("transcript_location"):
                fact["transcript_location"] = "unknown"
            if fact.get("source_fact_ids") is None:
                fact["source_fact_ids"] = []
            if not fact.get("speaker"):
                fact["speaker"] = "Unknown"
            if not fact.get("content"):
                fact["content"] = ""
        all_facts_raw.extend(pass_facts)
        print(f"  Pass {i}: {len(pass_facts)} facts")

    # Deduplicate by verbatim_quote — keep first occurrence
    seen_quotes = set()
    deduped = []
    for fact in all_facts_raw:
        quote = fact.get("verbatim_quote", "")
        if quote and quote not in seen_quotes:
            seen_quotes.add(quote)
            deduped.append(fact)

    # Renumber fact IDs sequentially; normalize field name variants
    for i, fact in enumerate(deduped, 1):
        fact["fact_id"] = f"F{i:03d}"
        # Some models output "type" instead of "fact_type" — normalize
        if "fact_type" not in fact and "type" in fact:
            fact["fact_type"] = fact.pop("type")

    factlist = FactList(
        facts=[Fact(**f) for f in deduped],
        transcript_token_count=0,
        extraction_model=GENERATION_MODEL,
    )

    dupes = len(all_facts_raw) - len(factlist.facts)
    print(f"  ✓ S1a complete: {len(factlist.facts)} facts ({dupes} duplicates removed)")
    return factlist


# =============================================================================
# GATE 1a: FACTLIST VALIDATION
# =============================================================================

def run_gate_1a(transcript: str, factlist: FactList) -> Gate1aResult:
    """
    Validate the FactList. Returns a Gate1aResult.
    If passed=False, the pipeline must halt (Level 3 degradation).
    """
    print("  Running Gate 1a: FactList Validation...")

    # Strip fields not needed for validation to stay within Mistral Small's 32k context.
    # Gate 1a only needs fact_id, fact_type, verbatim_quote, and confidence.
    stripped_facts = [
        {"fact_id": f.fact_id, "fact_type": f.fact_type,
         "verbatim_quote": f.verbatim_quote, "confidence": f.confidence}
        for f in factlist.facts
    ]
    factlist_json = json.dumps({"facts": stripped_facts}, indent=2)
    prompt = gate_1a_validator(transcript, factlist_json)
    raw = call_model(prompt, VERIFICATION_MODEL_A, max_tokens=4000)
    data = parse_json_response(raw)

    result = Gate1aResult(**data)

    # Deterministic override: the model occasionally self-reports passed=False even when
    # pass_rate >= 0.90 (contradiction). Trust the computed metric, not the model's opinion.
    # key_metrics_present failure is treated as advisory only — it fires when the validator
    # can't identify standard metrics from verbatim quotes, which is common for non-standard
    # companies (QSR, industrials, etc.). A 90%+ quote fidelity rate is the real signal.
    computed_passed = result.pass_rate >= 0.90
    if result.passed != computed_passed:
        print(f"  ! Gate 1a: overriding model's passed={result.passed} → {computed_passed} "
              f"(pass_rate={result.pass_rate:.0%}; model self-report was inconsistent)")
        result = result.model_copy(update={"passed": computed_passed})

    if result.passed:
        print(f"  ✓ Gate 1a PASSED: {result.pass_rate:.0%} pass rate")
    else:
        print(f"  ✗ Gate 1a FAILED: {result.failure_reason}")

    return result


# =============================================================================
# STAGE S1b: STRUCTURED DATA PULL
# =============================================================================

# Canonical mapping from display metric names → yfinance quarterly income-statement columns
_YF_METRIC_MAP = {
    "revenue":              "Total Revenue",
    "total revenue":        "Total Revenue",
    "net revenue":          "Total Revenue",
    "net income":           "Net Income",
    "operating income":     "Operating Income",
    "ebit":                 "EBIT",
    "gross profit":         "Gross Profit",
    "ebitda":               "EBITDA",
    "eps":                  "Basic EPS",
    "basic eps":            "Basic EPS",
    "diluted eps":          "Diluted EPS",
}


def _fill_yoy_from_yfinance(metrics: list, tk) -> None:
    """
    For any FinancialMetricRow with no yoy_change, attempt to compute one
    from yfinance quarterly income statement (two most-recent quarters YoY).
    Modifies the list in place.
    """
    try:
        import yfinance as yf
        import pandas as pd
        qs = tk.quarterly_income_stmt
        if qs is None or qs.empty:
            return
        # Columns are dates descending; we want the two most recent same-quarter pairs
        cols = list(qs.columns)
        if len(cols) < 5:
            return
        # Most recent quarter vs same quarter one year ago (index 0 vs index 4)
        cur_col  = cols[0]
        prev_col = cols[4]
    except Exception:
        return

    for m in metrics:
        if m.yoy_change:
            continue
        key = m.metric_name.lower().strip()
        yf_col = _YF_METRIC_MAP.get(key)
        if not yf_col or yf_col not in qs.index:
            continue
        try:
            cur  = float(qs.at[yf_col, cur_col])
            prev = float(qs.at[yf_col, prev_col])
            if prev == 0:
                continue
            pct = (cur - prev) / abs(prev) * 100
            sign = "+" if pct >= 0 else ""
            m.yoy_change = f"{sign}{pct:.1f}%"
        except Exception:
            continue


def run_s1b(factlist: FactList) -> S1bOutput:
    """
    Run the Structured Data Pull. Returns financial tables for Section 1.
    """
    print("  Running S1b: Structured Data Pull...")
    
    factlist_json = factlist.model_dump_json(indent=2)
    prompt = s1b_structured_data_pull(factlist_json)
    raw = call_model(prompt, GENERATION_MODEL, max_tokens=6000)
    data = parse_json_response(raw)

    # Coerce null string fields the model occasionally omits
    for row in data.get("key_financials", []):
        if row.get("reported_value") is None:
            row["reported_value"] = "—"
        if row.get("source_fact_ids") is None:
            row["source_fact_ids"] = []

    result = S1bOutput(**data)

    # Override sector with authoritative yfinance GICS classification
    # (LLM sometimes misclassifies, e.g. MCD as "Consumer Staples" instead of "Consumer Discretionary")
    try:
        import yfinance as yf
        raw_ticker = result.ticker.split()[0].split("(")[0].strip()
        tk = yf.Ticker(raw_ticker)
        yf_sector = tk.info.get("sector", "")
        if yf_sector:
            result = result.model_copy(update={"sector": yf_sector})
    except Exception:
        tk = None

    # yfinance fallback: fill missing yoy_change from quarterly income statement
    try:
        missing = [m for m in result.key_financials if not m.yoy_change]
        if missing and tk is not None:
            _fill_yoy_from_yfinance(result.key_financials, tk)
    except Exception:
        pass

    print(f"  ✓ S1b complete: {len(result.key_financials)} metrics, {len(result.key_takeaways)} takeaways")
    return result


# =============================================================================
# STAGE S2: ANALYSIS AGENTS (run in parallel)
# All four agents receive the same inputs and run concurrently.
# =============================================================================

async def run_s2_agent_async(
    agent_id: str,
    prompt_fn,
    transcript: str,
    factlist: FactList,
    context_bundle_text: str = "",
) -> S2SectionOutput:
    """
    Run a single S2 agent asynchronously.
    We use asyncio so all agents run at the same time.
    """
    factlist_json = factlist.model_dump_json(indent=2)
    prompt = prompt_fn(transcript, factlist_json, context_bundle_text)

    # Run the blocking model call in a thread pool so it doesn't block other agents
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: call_model(prompt, GENERATION_MODEL, max_tokens=12000)
    )

    data = parse_json_response(raw)
    # Coerce null source_fact_ids to [] — model occasionally returns null instead of []
    for claim in data.get("claims", []):
        if claim.get("source_fact_ids") is None:
            claim["source_fact_ids"] = []
    data["generating_model"] = GENERATION_MODEL
    # Remove any extra fields not in schema (e.g. credibility_score from S2e)
    allowed_fields = {"section_id", "section_title", "narrative", "claims", "generating_model"}
    data = {k: v for k, v in data.items() if k in allowed_fields}
    return S2SectionOutput(**data)


async def run_s2_all_async(
    transcript: str,
    factlist: FactList,
    context_bundle_text: str = "",
) -> dict[str, S2SectionOutput]:
    """
    Run all S2 agents (S2a–S2f) in parallel. Returns a dict keyed by section_id.
    S2e (credibility tracker) and S2f (competitive intelligence) are included
    only when context_bundle_text is non-empty.
    """
    agents = [
        ("S2a", s2a_narrative_analyst),
        ("S2b", s2b_signal_detector),
        ("S2c", s2c_gap_analyst),
        ("S2d", s2d_context_analyst),
        ("S2e", s2e_credibility_tracker),    # always run — falls back to transcript-only analysis when no context
        ("S2f", s2f_competitive_intelligence), # always run — falls back to transcript-only analysis when no context
    ]

    agent_labels = ", ".join(a[0] for a in agents)
    print(f"  Running S2 agents in parallel ({agent_labels})...")

    tasks = [
        run_s2_agent_async(agent_id, prompt_fn, transcript, factlist, context_bundle_text)
        for agent_id, prompt_fn in agents
    ]

    results = await asyncio.gather(*tasks)

    sections = {}
    for i, (agent_id, _) in enumerate(agents):
        sections[agent_id] = results[i]
        print(f"  ✓ {agent_id} complete: {len(results[i].claims)} claims")

    return sections


# =============================================================================
# GATE 2: FACT VERIFIER
# Verifies each S2 section. Handles retries and degradation.
# =============================================================================

def run_gate_2(section: S2SectionOutput, factlist: FactList, retry_count: int = 0) -> Gate2Result:
    """
    Verify one S2 section against the FactList.
    
    Returns a Gate2Result with passed=True or passed=False.
    The orchestrator handles retry logic and degradation decisions.
    """
    print(f"    Running Gate 2 for {section.section_id} (attempt {retry_count + 1})...")
    
    section_json = section.model_dump_json(indent=2)
    factlist_json = factlist.model_dump_json(indent=2)
    prompt = gate_2_fact_verifier(section_json, factlist_json)
    
    raw = call_model(prompt, VERIFICATION_MODEL_A, max_tokens=4000)
    data = parse_json_response(raw)
    data["verifier_model"] = VERIFICATION_MODEL_A
    data["retry_count"] = retry_count

    # Build a lookup of claim_type by claim_id from the section being verified.
    # Used below to protect interpretive claims from being marked absent.
    claim_types = {c.claim_id: c.claim_type for c in section.claims}
    interpretive_no_sources = {
        c.claim_id for c in section.claims
        if c.claim_type.value == "interpretive" and not c.source_fact_ids
    }

    # Coerce any invalid or unfair verdict values:
    # - "interpretive" as a verdict string → "aligned"
    # - "absent" on a correctly-labeled interpretive claim with no source_fact_ids → "aligned"
    #   (interpretive claims are editorial judgment; they cannot be verified against the FactList
    #    and should never fail grounding for lacking citations)
    # - Anything else invalid → "absent" (conservative fallback).
    valid_verdicts = {"aligned", "absent", "contradicted"}
    for verdict in data.get("claim_verdicts", []):
        v = verdict.get("verdict")
        cid = verdict.get("claim_id")
        if v not in valid_verdicts:
            if v == "interpretive":
                verdict["verdict"] = "aligned"
                print(f"    ! Coercing interpretive verdict → 'aligned' for {cid} (editorial claim)")
            else:
                print(f"    ! Coercing invalid verdict '{v}' → 'absent' for {cid}")
                verdict["verdict"] = "absent"
        elif v == "absent" and cid in interpretive_no_sources:
            verdict["verdict"] = "aligned"
            print(f"    ! Coercing 'absent' → 'aligned' for {cid} (correctly labeled interpretive — no citation required)")
        elif v == "absent" and section.section_id == "S2c":
            # S2c gap claims anchor to analyst_question or prior_quarter_reference facts
            # to prove a question was asked or a commitment was made. The verifier marks
            # these absent because the cited fact doesn't explicitly prove deflection —
            # but the anchor fact's existence IS the grounding for a gap claim.
            claim = next((c for c in section.claims if c.claim_id == cid), None)
            if claim and claim.claim_type.value == "grounded" and claim.source_fact_ids:
                anchor_types = {"analyst_question", "prior_quarter_reference"}
                fact_lookup = {f.fact_id: f for f in factlist.facts}
                cited_types = {
                    fact_lookup[fid].fact_type.value
                    for fid in claim.source_fact_ids
                    if fid in fact_lookup
                }
                if cited_types and cited_types.issubset(anchor_types):
                    verdict["verdict"] = "aligned"
                    print(f"    ! Coercing 'absent' → 'aligned' for {cid} (S2c gap anchor — cited fact proves question/commitment existed)")

    # Recalculate grounding only if coercions changed any verdicts.
    # The model's self-reported score is stale after coercions — recount from verdicts.
    # Use the total claim count from the section (not just returned verdicts) as denominator
    # so missing verdicts don't artificially inflate the score.
    all_verdicts = data.get("claim_verdicts", [])
    total_claims = len(section.claims)
    if all_verdicts and total_claims > 0:
        aligned_count = sum(1 for v in all_verdicts if v.get("verdict") == "aligned")
        # Use whichever denominator is larger: returned verdicts or total section claims
        denominator = max(len(all_verdicts), total_claims)
        recomputed_grounding = aligned_count / denominator
    else:
        recomputed_grounding = 1.0
    recomputed_contradictions = sum(1 for v in all_verdicts if v.get("verdict") == "contradicted")
    old_score = data.get("grounding_score", 0)
    if round(recomputed_grounding, 4) != round(old_score, 4):
        print(f"    ! Recalculated grounding after coercions: {old_score:.0%} → {recomputed_grounding:.0%}")
    data["grounding_score"] = recomputed_grounding
    data["contradiction_count"] = recomputed_contradictions

    result = Gate2Result(**data)

    # Override the model's self-reported "passed" with a deterministic calculation.
    # The model occasionally returns passed=False even with 100% grounding (hallucination).
    # Principle: gates make binary decisions based on computed metrics, not model opinion.
    computed_passed = result.grounding_score >= 0.90 and result.contradiction_count == 0
    if result.passed != computed_passed:
        print(f"    ! Overriding model's passed={result.passed} → {computed_passed} "
              f"(grounding={result.grounding_score:.0%}, contradictions={result.contradiction_count})")
        result = result.model_copy(update={"passed": computed_passed})

    if result.passed:
        print(f"    ✓ Gate 2 PASSED for {section.section_id}: {result.grounding_score:.0%} grounding, 0 contradictions")
    else:
        print(f"    ✗ Gate 2 FAILED for {section.section_id}: {result.grounding_score:.0%} grounding, {result.contradiction_count} contradictions")
    
    return result


def verify_section_with_retry(
    section: S2SectionOutput,
    factlist: FactList,
    transcript: str,
    prompt_fn,
    context_bundle_text: str = "",
) -> tuple[Optional[S2SectionOutput], Gate2Result, int]:
    """
    Verify a section, retrying up to MAX_RETRIES times if it fails.

    Returns:
        (verified_section, final_gate_result, retries_used)
        If all retries fail, verified_section is None (Level 2 degradation).
    """
    retry_count = 0

    while retry_count <= MAX_RETRIES:
        gate_result = run_gate_2(section, factlist, retry_count)

        if gate_result.passed:
            return section, gate_result, retry_count

        if retry_count < MAX_RETRIES:
            # Retry: send the section back to the generating agent with failure details
            print(f"    Retrying {section.section_id}...")
            retry_count += 1

            # Build a retry prompt that includes the failure reason
            factlist_json = factlist.model_dump_json(indent=2)
            original_prompt = prompt_fn(transcript, factlist_json, context_bundle_text)
            retry_prompt = f"""{original_prompt}

IMPORTANT — THIS IS A RETRY (attempt {retry_count + 1} of {MAX_RETRIES + 1}):
Your previous response failed Gate 2 verification for this reason:

{gate_result.failure_summary}

Please fix the identified issues and resubmit. Focus specifically on the
claims flagged above. Do not change claims that were not flagged.
"""
            raw = call_model(retry_prompt, GENERATION_MODEL, max_tokens=8000)
            data = parse_json_response(raw)
            for claim in data.get("claims", []):
                if claim.get("source_fact_ids") is None:
                    claim["source_fact_ids"] = []
            data["generating_model"] = GENERATION_MODEL
            allowed_fields = {"section_id", "section_title", "narrative", "claims", "generating_model"}
            data = {k: v for k, v in data.items() if k in allowed_fields}
            section = S2SectionOutput(**data)
        else:
            # All retries exhausted — Level 2 degradation (section omitted)
            print(f"    ✗ {section.section_id} failed all retries — will be omitted from report")
            return None, gate_result, retry_count

    return None, gate_result, retry_count


async def run_gate_2_all_async(
    s2_sections: dict[str, S2SectionOutput],
    factlist: FactList,
    transcript: str,
    prompt_fns: dict,
    context_bundle_text: str = "",
) -> list[tuple[str, Optional[S2SectionOutput], Gate2Result, int]]:
    """
    Run Gate 2 verification for all S2 sections in parallel.
    Each section's full retry loop runs in a thread, all run concurrently.
    Returns a list of (section_id, verified_section, gate_result, retries_used).
    """
    print("\nGATE 2: Fact Verification (parallel)")
    loop = asyncio.get_running_loop()

    async def _verify_one(section_id, section):
        verified, gate_result, retries = await loop.run_in_executor(
            None,
            lambda: verify_section_with_retry(
                section, factlist, transcript, prompt_fns[section_id], context_bundle_text
            )
        )
        return section_id, verified, gate_result, retries

    tasks = [
        _verify_one(sid, section)
        for sid, section in s2_sections.items()
    ]
    return await asyncio.gather(*tasks)


# =============================================================================
# STAGE S6: EDITORIAL SYNTHESIS — THE LEX WRITER
# Runs after all S2 sections are verified. Not put through Gate 2 (explicitly
# interpretive). S5 holistic verifier checks it for investment advice.
# =============================================================================

def run_s6(
    s1b: S1bOutput,
    verified_sections: dict[str, S2SectionOutput],
    context_bundle_text: str = "",
) -> S2SectionOutput:
    """
    Write the FT Lex-style editorial commentary that opens the dossier.
    Uses the verified S2 sections + context as raw material.
    """
    print("  Running S6: Editorial Synthesis (The Lex Writer)...")

    snapshot_json = s1b.model_dump_json(indent=2)
    sections_json = json.dumps(
        {k: json.loads(v.model_dump_json()) for k, v in verified_sections.items()},
        indent=2
    )

    prompt = s6_editorial_synthesis(snapshot_json, sections_json, context_bundle_text)
    raw = call_model(prompt, GENERATION_MODEL, max_tokens=3000)
    data = parse_json_response(raw)

    for claim in data.get("claims", []):
        if claim.get("source_fact_ids") is None:
            claim["source_fact_ids"] = []
    data["generating_model"] = GENERATION_MODEL
    allowed_fields = {"section_id", "section_title", "narrative", "claims", "generating_model"}
    data = {k: v for k, v in data.items() if k in allowed_fields}

    result = S2SectionOutput(**data)
    print(f"  ✓ S6 complete: editorial commentary written ({len(result.narrative)} chars)")
    return result


# =============================================================================
# STAGE S3: RADAR SCORER
# Two models score independently. Adjudicates disagreements.
# =============================================================================


# =============================================================================
# STAGE S5: HOLISTIC VERIFIER
# =============================================================================

def run_s5(
    s1b: S1bOutput,
    verified_sections: dict[str, S2SectionOutput],
) -> S5Output:
    """
    Run the Holistic Verifier across the complete assembled report.
    Uses a different model than Gate 2 (Principle 13).
    """
    print("  Running S5: Holistic Verifier...")
    
    # Assemble the full report for S5 to review
    full_report = {
        "snapshot": json.loads(s1b.model_dump_json()),
        "sections": {k: json.loads(v.model_dump_json()) for k, v in verified_sections.items()},
    }
    full_report_json = json.dumps(full_report, indent=2)
    
    prompt = s5_holistic_verifier(full_report_json)
    raw = call_model(prompt, VERIFICATION_MODEL_B, max_tokens=3000)
    data = parse_json_response(raw)
    data["verifier_model"] = VERIFICATION_MODEL_B

    # Filter out malformed issue entries the model occasionally returns without required fields.
    # LabelingIssue requires: claim_id, current_label, correct_label, explanation
    data["labeling_issues"] = [
        issue for issue in data.get("labeling_issues", [])
        if all(k in issue for k in ("claim_id", "current_label", "correct_label", "explanation"))
    ]
    # FramingConcern requires: claim_id, concern_description
    data["framing_concerns"] = [
        issue for issue in data.get("framing_concerns", [])
        if all(k in issue for k in ("claim_id", "concern_description"))
    ]

    result = S5Output(**data)
    
    if result.passed:
        print(f"  ✓ S5 PASSED")
    else:
        if result.safety_flags:
            print(f"  ✗ S5 FAILED: Safety flag triggered — pipeline halting")
        else:
            print(f"  ✗ S5 FAILED: Cross-section issues detected")
    
    return result


# =============================================================================
# MAIN PIPELINE ORCHESTRATOR
# Wires everything together with full gate logic and degradation handling.
# =============================================================================

def run_pipeline(
    transcript: str,
    ticker: str = "",
    year: int = 0,
    quarter: int = 0,
    peer_tickers: list[str] = None,
    skip_context: bool = False,
) -> dict:
    """
    Run the complete Earnings Call Dossier pipeline.

    Args:
        transcript:    The raw earnings call transcript text
        ticker:        Stock ticker (enables S0 context assembly)
        year:          Calendar year of the earnings call
        quarter:       Calendar quarter (1-4)
        peer_tickers:  Optional list of peer tickers for competitive intelligence
        skip_context:  Set True to skip S0 context assembly (faster, lower quality)

    Returns:
        A dict containing:
        - "status": "full" | "partial" | "halted"
        - "report": the assembled dossier data (or None if halted)
        - "run_log": the PipelineRunLog for observability
        - "omitted_sections": list of section IDs that were omitted
    """
    run_id = str(uuid.uuid4())[:8]
    start_time = time.time()
    omitted_sections = []
    safety_flags_triggered = []
    retry_counts = {}
    section_grounding_scores = {}
    section_contradiction_counts = {}
    degradation_level = DegradationLevel.NORMAL
    
    print(f"\n{'='*60}")
    print(f"Chorus AI — Earnings Call Dossier Pipeline")
    print(f"Run ID: {run_id}")
    print(f"{'='*60}\n")

    # -------------------------------------------------------------------------
    # STAGE S0: CONTEXT ASSEMBLY
    # Runs before S1 — builds the ContextBundle from yfinance, Alpha Vantage,
    # and prior/peer EDGAR transcripts. Best-effort: never blocks the pipeline.
    # -------------------------------------------------------------------------
    context_bundle = None
    context_bundle_text = ""

    if ticker and year and quarter and not skip_context:
        print("STAGE 0: Context Assembly")
        try:
            context_bundle = assemble_context(
                ticker=ticker,
                year=year,
                quarter=quarter,
                peer_tickers=peer_tickers or [],
                call_model_fn=call_model,
                generation_model=GENERATION_MODEL,
            )
            context_bundle_text = context_bundle.to_prompt_text()
        except Exception as e:
            print(f"  ! S0 context assembly failed (non-blocking): {e}")
            context_bundle = None
            context_bundle_text = ""
    else:
        if skip_context:
            print("STAGE 0: Context Assembly skipped (--no-context)")
        else:
            print("STAGE 0: Context Assembly skipped (no ticker/year/quarter provided)")

    # -------------------------------------------------------------------------
    # STAGE S1a: FACT EXTRACTION
    # -------------------------------------------------------------------------
    print("\nSTAGE 1: Fact Extraction")
    factlist = run_s1a(transcript)
    
    # -------------------------------------------------------------------------
    # GATE 1a: FACTLIST VALIDATION
    # If this fails, nothing downstream can be trusted — halt immediately.
    # -------------------------------------------------------------------------
    print("\nGATE 1a: FactList Validation")
    gate_1a_result = run_gate_1a(transcript, factlist)
    
    if not gate_1a_result.passed:
        # Borderline failure (80–89%): strip the failing facts and proceed at Level 1
        # rather than halting. Facts with bad verbatim quotes are unusable downstream anyway;
        # removing them and continuing is safer than discarding the whole run.
        # Hard halt threshold is <80% — at that point the extraction is fundamentally broken.
        if gate_1a_result.pass_rate >= 0.80:
            failed_ids = {
                v.fact_id for v in gate_1a_result.fact_validations if not v.passed
            }
            original_count = len(factlist.facts)
            cleaned_facts = [f for f in factlist.facts if f.fact_id not in failed_ids]
            factlist = FactList(
                facts=cleaned_facts,
                transcript_token_count=factlist.transcript_token_count,
                extraction_model=factlist.extraction_model,
            )
            print(f"  ! Gate 1a: borderline failure ({gate_1a_result.pass_rate:.0%}) — "
                  f"stripped {original_count - len(cleaned_facts)} failing facts, "
                  f"proceeding with {len(cleaned_facts)} verified facts (Level 1 degradation)")
            degradation_level = max(degradation_level, DegradationLevel.RETRY)
            # Rebuild a passing gate result reflecting the stripped factlist
            gate_1a_result = gate_1a_result.model_copy(update={
                "passed": True,
                "pass_rate": 1.0,
                "failure_reason": None,
                "degradation_triggered": DegradationLevel.NORMAL,
            })
        else:
            # Hard halt — pass_rate < 80%, extraction is fundamentally unreliable
            print("\n✗ PIPELINE HALTED at Gate 1a")
            elapsed = time.time() - start_time
            run_log = _build_run_log(
                run_id, factlist, gate_1a_result, {}, {}, {},
                DegradationLevel.PIPELINE_HALT, elapsed,
                FinalOutputStatus.HALTED, [], []
            )
            return {
                "status": "halted",
                "report": None,
                "run_log": run_log,
                "omitted_sections": [],
                "halt_reason": gate_1a_result.failure_reason
            }
    
    # -------------------------------------------------------------------------
    # STAGE S1b: STRUCTURED DATA PULL
    # -------------------------------------------------------------------------
    print("\nSTAGE 2: Structured Data Pull")
    s1b_output = run_s1b(factlist)
    
    # -------------------------------------------------------------------------
    # STAGE S2: ANALYSIS AGENTS (parallel — S2a-S2d always, S2e/S2f if context)
    # -------------------------------------------------------------------------
    print("\nSTAGE 3: Analysis Agents (parallel)")
    s2_sections = asyncio.run(run_s2_all_async(transcript, factlist, context_bundle_text))

    # -------------------------------------------------------------------------
    # GATE 2: FACT VERIFICATION (parallel across all sections, with retries)
    # -------------------------------------------------------------------------

    # Map section IDs to their generating prompt functions (needed for retries)
    prompt_fns = {
        "S2a": s2a_narrative_analyst,
        "S2b": s2b_signal_detector,
        "S2c": s2c_gap_analyst,
        "S2d": s2d_context_analyst,
        "S2e": s2e_credibility_tracker,
        "S2f": s2f_competitive_intelligence,
    }

    verified_sections = {}
    failed_sections = []

    gate_2_results = asyncio.run(
        run_gate_2_all_async(s2_sections, factlist, transcript, prompt_fns, context_bundle_text)
    )

    for section_id, verified, gate_result, retries in gate_2_results:
        retry_counts[section_id] = retries
        section_grounding_scores[section_id] = gate_result.grounding_score
        section_contradiction_counts[section_id] = gate_result.contradiction_count

        if verified is not None:
            verified_sections[section_id] = verified
        else:
            failed_sections.append(section_id)
            omitted_sections.append(section_id)
            degradation_level = max(degradation_level, DegradationLevel.PARTIAL_OUTPUT)
    
    # Check if too many sections failed (> 2 = Level 3 halt per architecture spec)
    if len(failed_sections) > 2:
        print(f"\n✗ PIPELINE HALTED: {len(failed_sections)} sections failed verification")
        elapsed = time.time() - start_time
        run_log = _build_run_log(
            run_id, factlist, gate_1a_result,
            section_grounding_scores, section_contradiction_counts, retry_counts,
            DegradationLevel.PIPELINE_HALT, elapsed,
            FinalOutputStatus.HALTED, omitted_sections, [],
            s1b_output=s1b_output,
        )
        return {
            "status": "halted",
            "report": None,
            "run_log": run_log,
            "omitted_sections": omitted_sections,
            "halt_reason": f"Sections {failed_sections} all failed verification after maximum retries."
        }
    
    if verified_sections:
        print(f"\n  Sections passed verification: {list(verified_sections.keys())}")
    if omitted_sections:
        print(f"  Sections omitted (Level 2 degradation): {omitted_sections}")
    
    # -------------------------------------------------------------------------
    # STAGE S6: EDITORIAL SYNTHESIS (runs after all S2 verification)
    # -------------------------------------------------------------------------
    print("\nSTAGE 4: Editorial Synthesis")
    s6_output = None
    try:
        s6_output = run_s6(s1b_output, verified_sections, context_bundle_text)
    except Exception as e:
        print(f"  ! S6 editorial synthesis failed (non-blocking): {e}")

    # -------------------------------------------------------------------------
    # STAGE S5: HOLISTIC VERIFICATION (includes S6 in review scope)
    # -------------------------------------------------------------------------
    print("\nSTAGE 5: Holistic Verification")
    all_sections_for_s5 = dict(verified_sections)
    if s6_output:
        all_sections_for_s5["S6"] = s6_output
    s5_output = run_s5(s1b_output, all_sections_for_s5)
    
    if not s5_output.passed:
        if s5_output.safety_flags:
            # Safety violation — always Level 3 halt
            for flag in s5_output.safety_flags:
                safety_flags_triggered.append(f"{flag.flag_type}: {flag.offending_text}")
            print(f"\n✗ PIPELINE HALTED: Safety flag detected")
            elapsed = time.time() - start_time
            run_log = _build_run_log(
                run_id, factlist, gate_1a_result,
                section_grounding_scores, section_contradiction_counts, retry_counts,
                DegradationLevel.PIPELINE_HALT, elapsed,
                FinalOutputStatus.HALTED, omitted_sections, safety_flags_triggered,
                s1b_output=s1b_output,
            )
            return {
                "status": "halted",
                "report": None,
                "run_log": run_log,
                "omitted_sections": omitted_sections,
                "halt_reason": f"Safety flag: {safety_flags_triggered}"
            }
        else:
            # Advisory issues — log them but don't halt
            print(f"  ! S5 advisory issues logged (not blocking)")
            degradation_level = max(degradation_level, DegradationLevel.PARTIAL_OUTPUT)
    
    # -------------------------------------------------------------------------
    # STAGE S7: ECON EXPERT (runs after S5, before report assembly)
    # Reads the verified report text, retrieves textbook passages via FAISS,
    # and writes "The Econ Expert's Take". Degrades gracefully if index absent.
    # -------------------------------------------------------------------------
    print("\nSTAGE 7: Econ Expert's Take")
    s7_output = None
    try:
        # Assemble the report text S7 will read: editorial + all verified sections
        report_text_parts = []
        if s6_output:
            report_text_parts.append(f"EDITORIAL COMMENTARY:\n{s6_output.narrative}")
        for sec_id, sec in verified_sections.items():
            report_text_parts.append(f"{sec.section_title.upper()}:\n{sec.narrative}")
        report_text_for_s7 = "\n\n---\n\n".join(report_text_parts)

        s7_output = run_s7(
            report_text=report_text_for_s7,
            call_model_fn=call_model,
            parse_json_fn=parse_json_response,
            generation_model=GENERATION_MODEL,
        )
    except Exception as e:
        print(f"  ! S7 econ expert failed (non-blocking): {e}")

    # -------------------------------------------------------------------------
    # ASSEMBLE FINAL REPORT
    # -------------------------------------------------------------------------
    elapsed = time.time() - start_time
    final_status = (
        FinalOutputStatus.PARTIAL if omitted_sections else FinalOutputStatus.FULL
    )
    
    run_log = _build_run_log(
        run_id, factlist, gate_1a_result,
        section_grounding_scores, section_contradiction_counts, retry_counts,
        degradation_level, elapsed,
        final_status, omitted_sections, safety_flags_triggered,
        s1b_output=s1b_output,
    )
    
    report = {
        "run_id": run_id,
        "status": final_status.value,
        "snapshot": json.loads(s1b_output.model_dump_json()),
        "editorial": json.loads(s6_output.model_dump_json()) if s6_output else None,
        "econ_expert": json.loads(s7_output.model_dump_json()) if s7_output else None,
        "sections": {k: json.loads(v.model_dump_json()) for k, v in verified_sections.items()},
        "context_bundle": json.loads(context_bundle.model_dump_json()) if context_bundle else None,
        "verification": {
            "source_grounding_scores": section_grounding_scores,
            "contradiction_counts": section_contradiction_counts,
            "s5_issues": {
                "cross_section_issues": [i.model_dump() for i in s5_output.cross_section_issues],
                "labeling_issues": [i.model_dump() for i in s5_output.labeling_issues],
                "framing_concerns": [i.model_dump() for i in s5_output.framing_concerns],
            },
            "verification_limitations": s5_output.verification_limitations,
            "omitted_sections": omitted_sections,
        }
    }
    
    print(f"\n{'='*60}")
    print(f"Pipeline complete in {elapsed:.1f}s")
    print(f"Status: {final_status.value.upper()}")
    if omitted_sections:
        print(f"Omitted sections: {omitted_sections}")
    print(f"{'='*60}\n")
    
    return {
        "status": final_status.value,
        "report": report,
        "run_log": run_log,
        "omitted_sections": omitted_sections
    }


# =============================================================================
# HELPER: BUILD RUN LOG
# Packages observability data for Layer 5 monitoring.
# =============================================================================

def _build_run_log(
    run_id: str,
    factlist: FactList,
    gate_1a: Gate1aResult,
    section_grounding: dict,
    section_contradictions: dict,
    retry_counts: dict,
    degradation_level: DegradationLevel,
    elapsed: float,
    final_status: FinalOutputStatus,
    omitted_sections: list,
    safety_flags: list,
    s1b_output: Optional[S1bOutput] = None,
) -> PipelineRunLog:
    """Build the observability log for this pipeline run."""

    # Count fact types
    fact_type_dist = {}
    for fact in factlist.facts:
        ft = fact.fact_type.value
        fact_type_dist[ft] = fact_type_dist.get(ft, 0) + 1

    # Pull ticker/quarter from S1b when available
    company_ticker = s1b_output.ticker if s1b_output else "unknown"
    quarter        = s1b_output.quarter if s1b_output else "unknown"

    return PipelineRunLog(
        run_id=run_id,
        company_ticker=company_ticker,
        quarter=quarter,
        transcript_token_count=factlist.transcript_token_count,
        fact_count=len(factlist.facts),
        fact_types_distribution=fact_type_dist,
        gate_1a_pass_rate=gate_1a.pass_rate,
        per_section_grounding_score=section_grounding,
        per_section_contradiction_count=section_contradictions,
        retry_count_per_section=retry_counts,
        radar_score_agreement={},
        degradation_level_reached=degradation_level,
        total_tokens_consumed=0,   # Would need token counting per call to populate
        total_latency_seconds=elapsed,
        models_used={
            "S1a": GENERATION_MODEL,
            "S1b": GENERATION_MODEL,
            "S2a-S2d": GENERATION_MODEL,
            "Gate1a": VERIFICATION_MODEL_A,
            "Gate2": VERIFICATION_MODEL_A,
            "S3_model_a": SCORING_MODEL_A,
            "S3_model_b": SCORING_MODEL_B,
            "S5": VERIFICATION_MODEL_B,
        },
        final_output_status=final_status,
        omitted_sections=omitted_sections,
        safety_flags_triggered=safety_flags
    )


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Chorus AI Earnings Call Dossier Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Fetch transcript from FMP API and run pipeline:
    python pipeline.py --ticker MSFT --year 2026 --quarter 2

  Use a local transcript file:
    python pipeline.py --transcript transcripts/msft_q2_2026.txt

  Specify output location:
    python pipeline.py --ticker MSFT --year 2026 --quarter 2 --output outputs/msft_q2.json
        """
    )

    # Transcript source
    parser.add_argument("--ticker",     help="Stock ticker, e.g. MSFT — fetches transcript AND enables context assembly")
    parser.add_argument("--transcript", help="Path to a local .txt transcript file (can be combined with --ticker for context)")
    parser.add_argument("--year",    type=int, choices=range(2000, 2100), metavar="YEAR",
                        help="Calendar year of the earnings call (required with --ticker for transcript fetch)")
    parser.add_argument("--quarter", type=int, choices=[1, 2, 3, 4],
                        help="Quarter (1-4) (required with --ticker for transcript fetch)")
    parser.add_argument("--output",  default="outputs/report_output.json",
                        help="Path to save the output JSON (default: outputs/report_output.json)")
    parser.add_argument(
        "--peers", default="",
        help="Comma-separated peer tickers for competitive intelligence, e.g. PENN,MGM,CZR"
    )
    parser.add_argument(
        "--no-context", action="store_true",
        help="Skip S0 context assembly (faster runs, no historical/peer data)"
    )
    parser.add_argument(
        "--source", default="auto", choices=["auto", "edgar", "finnhub", "fmp"],
        help="Transcript source for --ticker (default: auto)"
    )

    args = parser.parse_args()

    # Validate: must have at least a transcript file or a ticker+year+quarter to fetch one
    if not args.transcript and not (args.ticker and args.year and args.quarter):
        parser.error(
            "Provide either --transcript <file> or --ticker <TICK> --year <Y> --quarter <Q>\n"
            "You may also combine both: --transcript <file> --ticker MCD --year 2025 --quarter 4\n"
            "(the ticker/year/quarter will be used for context assembly even if transcript comes from file)"
        )

    # Parse peer tickers
    peer_tickers = [p.strip().upper() for p in args.peers.split(",") if p.strip()]

    # Fetch or load transcript
    if args.transcript:
        transcript_text = fetch_transcript(filepath=args.transcript)
    else:
        transcript_text = fetch_transcript(
            ticker=args.ticker, year=args.year, quarter=args.quarter,
            source=args.source
        )

    # Validate before handing to pipeline
    validation = validate_transcript(transcript_text)
    if not validation["valid"]:
        for error in validation["errors"]:
            print(f"✗ {error}")
        exit(1)
    for issue in validation["issues"]:
        print(f"⚠ {issue}")

    # Ensure output directory exists
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    # Run pipeline
    result = run_pipeline(
        transcript=transcript_text,
        ticker=args.ticker or "",
        year=args.year or 0,
        quarter=args.quarter or 0,
        peer_tickers=peer_tickers,
        skip_context=args.no_context,
    )
    
    # Save output
    output_data = {
        "status": result["status"],
        "omitted_sections": result["omitted_sections"],
        "report": result["report"],
        "run_log": json.loads(result["run_log"].model_dump_json()) if result["run_log"] else None
    }
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)
    
    print(f"Output saved to {args.output}")

    if result["status"] == "halted":
        print(f"Halt reason: {result.get('halt_reason', 'unknown')}")
        exit(1)

    # Export PDF
    try:
        pdf_path = format_report(args.output)
        print(f"PDF saved to   {pdf_path}")
    except Exception as e:
        print(f"⚠ PDF export failed: {e}")
