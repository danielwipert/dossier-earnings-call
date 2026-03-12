"""
Chorus AI Systems — Earnings Call Dossier
Pipeline Orchestrator v1.0

This is the main file that runs the pipeline. It calls each agent in sequence,
runs the gates, handles retries, and manages graceful degradation.

Usage:
    python pipeline.py --transcript path/to/transcript.txt

Requirements:
    pip install huggingface_hub pydantic python-dotenv

Environment variables needed in a .env file:
    HF_TOKEN=your_huggingface_token_here
"""

import json
import time
import uuid
import asyncio
import argparse
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
import os

from huggingface_hub import InferenceClient

# Import our schemas and prompts
from core.schemas import (
    FactList, Fact, Gate1aResult, S1bOutput, S2SectionOutput,
    Gate2Result, S3Output, DimensionScore, S5Output,
    PipelineRunLog, DegradationLevel, FinalOutputStatus
)
from core.prompts import (
    s1a_fact_extractor, gate_1a_validator, s1b_structured_data_pull,
    s2a_narrative_analyst, s2b_signal_detector, s2c_gap_analyst,
    s2d_context_analyst, gate_2_fact_verifier, s3_radar_scorer,
    s5_holistic_verifier
)

load_dotenv()

# =============================================================================
# MODEL CONFIGURATION
# Two model families to satisfy Principle 13 (Second-Order Self-Observation):
# generation and verification must not share the same model.
# =============================================================================

# Generation models (larger, more capable — for producing content)
GENERATION_MODEL = "Qwen/Qwen2.5-72B-Instruct"

# Verification models (must differ from generation — for checking content)
VERIFICATION_MODEL_A = "Qwen/Qwen2.5-7B-Instruct"   # Gate 2
VERIFICATION_MODEL_B = "meta-llama/Llama-3.2-3B-Instruct"  # S5 (different family)

# Scoring models (two independent scorers)
SCORING_MODEL_A = "Qwen/Qwen2.5-7B-Instruct"
SCORING_MODEL_B = "meta-llama/Llama-3.2-3B-Instruct"

MAX_RETRIES = 2  # Max times a section can be retried before Level 2 degradation


# =============================================================================
# LLM CALLER
# Single function for all model calls. Handles the HuggingFace API format
# and returns the raw text response.
# =============================================================================

def call_model(prompt: str, model_id: str, max_tokens: int = 4000) -> str:
    """
    Call a HuggingFace model and return the response text.
    
    Args:
        prompt: The fully formatted prompt string
        model_id: The HuggingFace model identifier
        max_tokens: Maximum tokens to generate
    
    Returns:
        The model's response as a string
    
    Raises:
        Exception if the API call fails
    """
    client = InferenceClient(
        model=model_id,
        token=os.getenv("HF_TOKEN")
    )
    
    response = client.chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens
    )
    
    return response.choices[0].message.content


def parse_json_response(raw_response: str) -> dict:
    """
    Parse a JSON response from the model.
    Models sometimes wrap JSON in markdown code fences (```json ... ```)
    even when told not to — this handles that gracefully.
    """
    # Strip markdown code fences if present
    text = raw_response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1])
    
    return json.loads(text)


# =============================================================================
# STAGE S1a: FACT EXTRACTOR
# =============================================================================

def run_s1a(transcript: str) -> FactList:
    """
    Run the Fact Extractor. Returns a validated FactList object.
    """
    print("  Running S1a: Fact Extractor...")
    
    prompt = s1a_fact_extractor(transcript)
    raw = call_model(prompt, GENERATION_MODEL, max_tokens=8000)
    data = parse_json_response(raw)
    
    # Add the model ID (the prompt template leaves this blank)
    data["extraction_model"] = GENERATION_MODEL
    
    # Validate against the Pydantic schema — raises an error if the shape is wrong
    factlist = FactList(**data)
    
    print(f"  ✓ S1a complete: {len(factlist.facts)} facts extracted")
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
    
    factlist_json = factlist.model_dump_json(indent=2)
    prompt = gate_1a_validator(transcript, factlist_json)
    raw = call_model(prompt, VERIFICATION_MODEL_A, max_tokens=4000)
    data = parse_json_response(raw)
    
    result = Gate1aResult(**data)
    
    if result.passed:
        print(f"  ✓ Gate 1a PASSED: {result.pass_rate:.0%} pass rate")
    else:
        print(f"  ✗ Gate 1a FAILED: {result.failure_reason}")
    
    return result


# =============================================================================
# STAGE S1b: STRUCTURED DATA PULL
# =============================================================================

def run_s1b(factlist: FactList) -> S1bOutput:
    """
    Run the Structured Data Pull. Returns financial tables for Section 1.
    """
    print("  Running S1b: Structured Data Pull...")
    
    factlist_json = factlist.model_dump_json(indent=2)
    prompt = s1b_structured_data_pull(factlist_json)
    raw = call_model(prompt, GENERATION_MODEL, max_tokens=3000)
    data = parse_json_response(raw)
    
    result = S1bOutput(**data)
    
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
    factlist: FactList
) -> S2SectionOutput:
    """
    Run a single S2 agent asynchronously.
    We use asyncio so all four agents run at the same time.
    """
    factlist_json = factlist.model_dump_json(indent=2)
    prompt = prompt_fn(transcript, factlist_json)
    
    # Run the blocking model call in a thread pool so it doesn't block other agents
    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(
        None,
        lambda: call_model(prompt, GENERATION_MODEL, max_tokens=4000)
    )
    
    data = parse_json_response(raw)
    data["generating_model"] = GENERATION_MODEL
    return S2SectionOutput(**data)


async def run_s2_all_async(transcript: str, factlist: FactList) -> dict[str, S2SectionOutput]:
    """
    Run all four S2 agents in parallel. Returns a dict keyed by section_id.
    """
    print("  Running S2 agents in parallel (S2a, S2b, S2c, S2d)...")
    
    agents = [
        ("S2a", s2a_narrative_analyst),
        ("S2b", s2b_signal_detector),
        ("S2c", s2c_gap_analyst),
        ("S2d", s2d_context_analyst),
    ]
    
    tasks = [
        run_s2_agent_async(agent_id, prompt_fn, transcript, factlist)
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
    
    result = Gate2Result(**data)
    
    if result.passed:
        print(f"    ✓ Gate 2 PASSED for {section.section_id}: {result.grounding_score:.0%} grounding, 0 contradictions")
    else:
        print(f"    ✗ Gate 2 FAILED for {section.section_id}: {result.grounding_score:.0%} grounding, {result.contradiction_count} contradictions")
    
    return result


def verify_section_with_retry(
    section: S2SectionOutput,
    factlist: FactList,
    transcript: str,
    prompt_fn
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
            original_prompt = prompt_fn(transcript, factlist_json)
            retry_prompt = f"""{original_prompt}

IMPORTANT — THIS IS A RETRY (attempt {retry_count + 1} of {MAX_RETRIES + 1}):
Your previous response failed Gate 2 verification for this reason:

{gate_result.failure_summary}

Please fix the identified issues and resubmit. Focus specifically on the
claims flagged above. Do not change claims that were not flagged.
"""
            raw = call_model(retry_prompt, GENERATION_MODEL, max_tokens=4000)
            data = parse_json_response(raw)
            data["generating_model"] = GENERATION_MODEL
            section = S2SectionOutput(**data)
        else:
            # All retries exhausted — Level 2 degradation (section omitted)
            print(f"    ✗ {section.section_id} failed all retries — will be omitted from report")
            return None, gate_result, retry_count
    
    return None, gate_result, retry_count


# =============================================================================
# STAGE S3: RADAR SCORER
# Two models score independently. Adjudicates disagreements.
# =============================================================================

def run_s3(factlist: FactList, verified_sections: dict[str, S2SectionOutput]) -> S3Output:
    """
    Score the company on 7 dimensions using two independent models.
    Adjudicates disagreements > 3 points.
    """
    print("  Running S3: Radar Scorer (two independent models)...")
    
    factlist_json = factlist.model_dump_json(indent=2)
    sections_json = json.dumps({k: json.loads(v.model_dump_json()) for k, v in verified_sections.items()}, indent=2)
    
    # Model A scores
    prompt_a = s3_radar_scorer(factlist_json, sections_json, model_role="model_a")
    raw_a = call_model(prompt_a, SCORING_MODEL_A, max_tokens=3000)
    data_a = parse_json_response(raw_a)
    
    # Model B scores independently
    prompt_b = s3_radar_scorer(factlist_json, sections_json, model_role="model_b")
    raw_b = call_model(prompt_b, SCORING_MODEL_B, max_tokens=3000)
    data_b = parse_json_response(raw_b)
    
    # Build score lookup from Model B results
    scores_b = {d["dimension"]: d["score_model_a"] for d in data_b["dimension_scores"]}
    
    # Adjudicate: compare scores, flag disagreements > 3 points
    final_scores = []
    for dim_data in data_a["dimension_scores"]:
        dimension = dim_data["dimension"]
        score_a = dim_data["score_model_a"]
        score_b = scores_b.get(dimension, score_a)  # Fall back to A if B missing
        
        diff = abs(score_a - score_b)
        agreed = diff <= 3
        
        if agreed:
            published = score_a  # No adjudication needed
            note = None
        else:
            # Adjudicated midpoint, rounded to nearest integer
            published = round((score_a + score_b) / 2)
            note = f"Model A scored {score_a}, Model B scored {score_b}. Published score {published} is adjudicated midpoint."
            print(f"    ! Score disagreement on {dimension}: {score_a} vs {score_b} → adjudicated to {published}")
        
        final_scores.append(DimensionScore(
            dimension=dimension,
            score_model_a=score_a,
            score_model_b=score_b,
            published_score=published,
            models_agreed=agreed,
            disagreement_note=note,
            supporting_fact_ids=dim_data.get("supporting_fact_ids", []),
            scoring_rationale=dim_data.get("scoring_rationale", "")
        ))
    
    result = S3Output(
        dimension_scores=final_scores,
        scoring_model_a=SCORING_MODEL_A,
        scoring_model_b=SCORING_MODEL_B
    )
    
    print(f"  ✓ S3 complete: 7 dimensions scored")
    return result


# =============================================================================
# STAGE S5: HOLISTIC VERIFIER
# =============================================================================

def run_s5(
    s1b: S1bOutput,
    verified_sections: dict[str, S2SectionOutput],
    s3: S3Output
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
        "radar_scores": json.loads(s3.model_dump_json())
    }
    full_report_json = json.dumps(full_report, indent=2)
    
    prompt = s5_holistic_verifier(full_report_json)
    raw = call_model(prompt, VERIFICATION_MODEL_B, max_tokens=3000)
    data = parse_json_response(raw)
    data["verifier_model"] = VERIFICATION_MODEL_B
    
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

def run_pipeline(transcript: str) -> dict:
    """
    Run the complete Earnings Call Dossier pipeline.
    
    Args:
        transcript: The raw earnings call transcript text
    
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
    # STAGE S1a: FACT EXTRACTION
    # -------------------------------------------------------------------------
    print("STAGE 1: Fact Extraction")
    factlist = run_s1a(transcript)
    
    # -------------------------------------------------------------------------
    # GATE 1a: FACTLIST VALIDATION
    # If this fails, nothing downstream can be trusted — halt immediately.
    # -------------------------------------------------------------------------
    print("\nGATE 1a: FactList Validation")
    gate_1a_result = run_gate_1a(transcript, factlist)
    
    if not gate_1a_result.passed:
        # Level 3: Pipeline Halt
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
    # STAGE S2: ANALYSIS AGENTS (parallel)
    # -------------------------------------------------------------------------
    print("\nSTAGE 3: Analysis Agents (parallel)")
    s2_sections = asyncio.run(run_s2_all_async(transcript, factlist))
    
    # -------------------------------------------------------------------------
    # GATE 2: FACT VERIFICATION (per section, with retries)
    # -------------------------------------------------------------------------
    print("\nGATE 2: Fact Verification")
    
    # Map section IDs to their generating prompt functions (needed for retries)
    prompt_fns = {
        "S2a": s2a_narrative_analyst,
        "S2b": s2b_signal_detector,
        "S2c": s2c_gap_analyst,
        "S2d": s2d_context_analyst,
    }
    
    verified_sections = {}
    failed_sections = []
    
    for section_id, section in s2_sections.items():
        verified, gate_result, retries = verify_section_with_retry(
            section, factlist, transcript, prompt_fns[section_id]
        )
        
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
            FinalOutputStatus.HALTED, omitted_sections, []
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
    # STAGE S3: RADAR SCORING
    # -------------------------------------------------------------------------
    print("\nSTAGE 4: Radar Scoring")
    s3_output = run_s3(factlist, verified_sections)
    
    # -------------------------------------------------------------------------
    # STAGE S5: HOLISTIC VERIFICATION
    # -------------------------------------------------------------------------
    print("\nSTAGE 5: Holistic Verification")
    s5_output = run_s5(s1b_output, verified_sections, s3_output)
    
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
                FinalOutputStatus.HALTED, omitted_sections, safety_flags_triggered
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
        final_status, omitted_sections, safety_flags_triggered
    )
    
    report = {
        "run_id": run_id,
        "status": final_status.value,
        "snapshot": json.loads(s1b_output.model_dump_json()),
        "sections": {k: json.loads(v.model_dump_json()) for k, v in verified_sections.items()},
        "radar_scores": json.loads(s3_output.model_dump_json()),
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
    safety_flags: list
) -> PipelineRunLog:
    """Build the observability log for this pipeline run."""
    
    # Count fact types
    fact_type_dist = {}
    for fact in factlist.facts:
        ft = fact.fact_type.value
        fact_type_dist[ft] = fact_type_dist.get(ft, 0) + 1
    
    return PipelineRunLog(
        run_id=run_id,
        company_ticker="unknown",  # Filled in post-run from S1b output
        quarter="unknown",
        transcript_token_count=factlist.transcript_token_count,
        fact_count=len(factlist.facts),
        fact_types_distribution=fact_type_dist,
        gate_1a_pass_rate=gate_1a.pass_rate,
        per_section_grounding_score=section_grounding,
        per_section_contradiction_count=section_contradictions,
        retry_count_per_section=retry_counts,
        radar_score_agreement={},  # Populated by S3
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
    parser = argparse.ArgumentParser(description="Chorus AI Earnings Call Dossier Pipeline")
    parser.add_argument("--transcript", required=True, help="Path to the transcript text file")
    parser.add_argument("--output", default="report_output.json", help="Path to save the output JSON")
    args = parser.parse_args()
    
    # Load transcript
    print(f"Loading transcript from {args.transcript}...")
    with open(args.transcript, "r", encoding="utf-8") as f:
        transcript_text = f.read()
    
    # Run pipeline
    result = run_pipeline(transcript_text)
    
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
