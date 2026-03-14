"""
Chorus AI Systems — Earnings Call Dossier
Pydantic Data Schemas v1.0

These schemas define the exact shape of data flowing between every
stage of the pipeline. Every agent input and output, every gate decision,
and every log entry has a schema here.

Think of these as contracts: if an agent produces output that doesn't
match its schema, Python rejects it immediately rather than letting
bad data silently corrupt downstream stages.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# =============================================================================
# ENUMS
# Enums are fixed lists of allowed values. Using enums instead of plain
# strings means a typo like "finnancial_metric" gets caught immediately.
# =============================================================================

class FactType(str, Enum):
    """The seven allowed types for a fact in the FactList (S1a output)."""
    FINANCIAL_METRIC       = "financial_metric"
    MANAGEMENT_STATEMENT   = "management_statement"
    FORWARD_GUIDANCE       = "forward_guidance"
    ANALYST_QUESTION       = "analyst_question"
    COMPETITIVE_REFERENCE  = "competitive_reference"
    OPERATIONAL_METRIC     = "operational_metric"
    PRIOR_QUARTER_REF      = "prior_quarter_reference"


class ClaimType(str, Enum):
    """
    The three allowed types for a claim in an S2 analysis section.
    - grounded:     directly supported by a FactList entry (requires source_fact_ids)
    - derived:      calculated from one or more facts (requires derivation_note)
    - interpretive: editorial judgment — must be labeled as such, never presented as fact
    """
    GROUNDED      = "grounded"
    DERIVED       = "derived"
    INTERPRETIVE  = "interpretive"


class ClaimVerdict(str, Enum):
    """Gate 2's verdict for each individual claim."""
    ALIGNED      = "aligned"      # Cited fact(s) support the claim
    ABSENT       = "absent"       # Cited fact(s) don't actually address the claim
    CONTRADICTED = "contradicted" # Cited fact(s) contradict the claim


class DegradationLevel(int, Enum):
    """
    The four operating levels for graceful degradation (Principle 6).
    0 = Normal (all gates pass first attempt)
    1 = Retry (a gate rejected a section; retrying)
    2 = Partial Output (section failed all retries; omitted from report)
    3 = Pipeline Halt (FactList failure, >2 sections failed, or safety violation)
    """
    NORMAL          = 0
    RETRY           = 1
    PARTIAL_OUTPUT  = 2
    PIPELINE_HALT   = 3


class FinalOutputStatus(str, Enum):
    FULL    = "full"
    PARTIAL = "partial"
    HALTED  = "halted"


# =============================================================================
# STAGE S1a: FACT EXTRACTOR
# The Fact Extractor reads the raw transcript and produces the FactList.
# Every downstream agent depends on this output. It is locked (immutable)
# after Gate 1a passes — no agent may add, modify, or remove facts.
# =============================================================================

class Fact(BaseModel):
    """
    A single atomic fact extracted from the transcript.
    This is the core unit of the entire pipeline — every claim in the
    final dossier must trace back to one or more of these.
    """
    fact_id: str = Field(
        description="Unique identifier, e.g. 'F001', 'F002'."
    )
    fact_type: FactType = Field(
        description="One of the seven defined fact types."
    )
    content: str = Field(
        description="Plain-language description of the fact."
    )
    verbatim_quote: str = Field(
        description=(
            "Character-exact quote from the transcript. "
            "No paraphrasing. Gate 1a verifies this exists in the source."
        )
    )
    speaker: str = Field(
        description="Name and title of speaker, e.g. 'Satya Nadella, CEO' or 'Analyst: Brent Thill, Jefferies'."
    )
    transcript_location: str = Field(
        description="Section of transcript, e.g. 'prepared_remarks' or 'qa'."
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Extraction confidence score from 0.0 to 1.0. "
            "Facts below 0.8 are flagged as low-confidence for downstream agents."
        )
    )


class FactList(BaseModel):
    """
    The complete output of S1a. This is the locked foundation.
    Once Gate 1a passes, this object is frozen — no agent may alter it.
    """
    facts: list[Fact] = Field(description="All facts extracted from the transcript.")
    transcript_token_count: int = Field(description="Token count of the input transcript.")
    extraction_model: str = Field(description="Model ID used for extraction, e.g. 'Qwen/Qwen2.5-72B-Instruct'.")


# =============================================================================
# GATE 1a: FACTLIST VALIDATION
# Gate 1a validates the FactList before any downstream processing begins.
# This is the most critical gate — a bad FactList poisons everything downstream.
# =============================================================================

class FactValidationResult(BaseModel):
    """Validation result for a single fact."""
    fact_id: str
    passed: bool
    failure_reason: Optional[str] = Field(
        default=None,
        description="Populated only if passed=False."
    )


class Gate1aResult(BaseModel):
    """
    Output of Gate 1a. Determines whether the pipeline may proceed.

    Pass conditions (all must be true):
    - ≥ 90% of facts pass individual validation
    - Key financial metrics present (revenue, EPS, margin)
    - No quote fidelity failures above 10%
    """
    fact_validations: list[FactValidationResult]
    pass_rate: float = Field(
        ge=0.0, le=1.0,
        description="Fraction of facts that passed validation."
    )
    key_metrics_present: bool = Field(
        description="True if revenue, EPS, and operating margin are all present."
    )
    passed: bool = Field(
        description="True if pass_rate >= 0.90 AND key_metrics_present is True."
    )
    failure_reason: Optional[str] = Field(
        default=None,
        description="If passed=False, explains why the pipeline is halting."
    )
    degradation_triggered: DegradationLevel = Field(
        default=DegradationLevel.NORMAL,
        description="DegradationLevel.PIPELINE_HALT if Gate 1a fails."
    )


# =============================================================================
# STAGE S1b: STRUCTURED DATA PULL
# S1b organizes financial metrics from the FactList into structured tables
# for Section 1 (The Snapshot). It references fact_ids — it never introduces
# new numbers that aren't already in the FactList.
# =============================================================================

class FinancialMetricRow(BaseModel):
    """One row in the key financials table."""
    metric_name: str                    # e.g. "Revenue", "EPS (Diluted)"
    reported_value: str                 # e.g. "$69.6B", "$3.23"
    yoy_change: Optional[str] = None    # e.g. "+16%"
    vs_estimate: Optional[str] = None   # e.g. "Beat (+2.1%)"
    source_fact_ids: list[str] = Field(default_factory=list)


class KeyTakeaway(BaseModel):
    """One of the three key takeaways in The Snapshot."""
    number: int                    # 1, 2, or 3
    text: str                      # The takeaway sentence(s)
    source_fact_ids: list[str]     # Supporting fact IDs


class S1bOutput(BaseModel):
    """Structured data tables for Section 1 of the dossier."""
    company_name: str
    ticker: str
    quarter: str                   # e.g. "Q2 FY2026"
    sector: str
    headline: str                  # One-sentence summary of the quarter
    key_financials: list[FinancialMetricRow]
    key_takeaways: list[KeyTakeaway] = Field(
        description="Exactly 3 takeaways, each with source_fact_ids."
    )


# =============================================================================
# STAGE S2: ANALYSIS AGENTS (S2a, S2b, S2c, S2d)
# All four agents share the same output schema. Each produces one section
# of the dossier, with every claim tagged by type and source_fact_ids.
# =============================================================================

class Claim(BaseModel):
    """
    A single factual or interpretive claim within an S2 section.
    This is what Gate 2 verifies — one claim at a time.
    """
    claim_id: str = Field(description="Unique ID within this section, e.g. 'S2a-C001'.")
    claim_text: str = Field(description="The specific claim as written in the narrative.")
    claim_type: ClaimType
    source_fact_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Required for grounded and derived claims. "
            "Leave empty only for interpretive claims."
        )
    )
    derivation_note: Optional[str] = Field(
        default=None,
        description="For derived claims only: explain how this was calculated from the source facts."
    )


class S2SectionOutput(BaseModel):
    """
    Shared output schema for all four S2 analysis agents.
    The section_id tells the pipeline which section this is.
    """
    section_id: str = Field(
        description="One of: 'S2a', 'S2b', 'S2c', 'S2d'."
    )
    section_title: str = Field(
        description="The heading that appears in the final dossier."
    )
    narrative: str = Field(
        description="The full written analysis (FT/New Yorker quality prose)."
    )
    claims: list[Claim] = Field(
        description="Structured list of every factual claim in the narrative."
    )
    generating_model: str = Field(description="Model ID used to generate this section.")


# =============================================================================
# GATE 2: FACT VERIFIER
# Gate 2 verifies every claim in every S2 section against the FactList.
# This is where Principle 1 (Separation of Generation and Validation) is
# enforced most directly. Gate 2 must use a different model than the S2 agents.
# =============================================================================

class ClaimVerdictDetail(BaseModel):
    """Gate 2's verdict on one individual claim."""
    claim_id: str
    verdict: ClaimVerdict
    explanation: str = Field(
        description="Brief explanation of why this verdict was reached."
    )


class Gate2Result(BaseModel):
    """
    Gate 2 output for one S2 section.

    Pass condition: grounding_score >= 0.95 AND contradiction_count == 0
    On failure: section is returned to the S2 agent with failure details.
    After 2 failed retries: Level 2 degradation (section omitted).
    """
    section_id: str
    total_claims: int
    grounding_score: float = Field(
        ge=0.0, le=1.0,
        description="Fraction of claims that are aligned or correctly derived."
    )
    contradiction_count: int = Field(
        description="Number of claims where cited facts contradict the claim. Target: 0."
    )
    absent_count: int = Field(
        description="Number of claims where cited facts don't address the claim."
    )
    claim_verdicts: list[ClaimVerdictDetail]
    passed: bool = Field(
        description="True if grounding_score >= 0.90 AND contradiction_count == 0."
    )
    failure_summary: Optional[str] = Field(
        default=None,
        description="If passed=False, a summary returned to the S2 agent explaining what to fix."
    )
    retry_count: int = Field(
        default=0,
        description="How many times this section has been retried (max 2 before escalation)."
    )
    verifier_model: str = Field(description="Model ID used for verification (must differ from generating model).")


# =============================================================================
# STAGE S3: RADAR SCORER
# S3 scores the company across 7 dimensions. At least two models score
# independently. Disagreements > 3 points are adjudicated and disclosed.
# =============================================================================

class DimensionScore(BaseModel):
    """Score for one of the seven radar dimensions."""
    dimension: str = Field(
        description=(
            "One of: 'revenue_momentum', 'margin_health', 'guidance_confidence', "
            "'mgmt_transparency', 'strategic_clarity', 'earnings_quality', 'forward_visibility'."
        )
    )
    score_model_a: int = Field(ge=1, le=10, description="Score from first scoring model.")
    score_model_b: int = Field(ge=1, le=10, description="Score from second scoring model.")
    published_score: int = Field(ge=1, le=10, description="Final score (adjudicated midpoint if models disagreed by > 3).")
    models_agreed: bool = Field(description="True if |score_model_a - score_model_b| <= 3.")
    disagreement_note: Optional[str] = Field(
        default=None,
        description="If models_agreed=False, explains the disagreement for the Verification Report."
    )
    supporting_fact_ids: list[str] = Field(
        description="Fact IDs that justify this score. A score without evidence is not a score."
    )
    scoring_rationale: str = Field(description="Brief explanation of why this score was given.")


class S3Output(BaseModel):
    """Radar scores across all 7 dimensions."""
    dimension_scores: list[DimensionScore] = Field(
        description="Exactly 7 entries, one per dimension."
    )
    scoring_model_a: str
    scoring_model_b: str


# =============================================================================
# STAGE S5: HOLISTIC VERIFIER
# S5 is the second-pass that checks the report as a whole — looking for
# problems that only emerge when sections are read together.
# Must use a different model than Gate 2 (Principle 13).
# =============================================================================

class CrossSectionIssue(BaseModel):
    issue_description: str
    sections_involved: list[str]   # e.g. ["S2a", "S2c"]
    severity: str                  # "blocking" or "advisory"


class LabelingIssue(BaseModel):
    claim_id: str
    current_label: ClaimType
    correct_label: ClaimType
    explanation: str


class FramingConcern(BaseModel):
    claim_id: str
    concern_description: str       # Technically grounded but creates false impression


class SafetyFlag(BaseModel):
    flag_type: str                 # e.g. "investment_advice"
    offending_text: str
    location: str                  # Which section


class S5Output(BaseModel):
    """
    Holistic verification output.

    Pass condition: no cross-section contradictions AND no safety flags.
    A safety flag (e.g. investment advice detected) always triggers Level 3 halt.
    """
    cross_section_issues: list[CrossSectionIssue] = Field(default_factory=list)
    labeling_issues: list[LabelingIssue] = Field(default_factory=list)
    framing_concerns: list[FramingConcern] = Field(default_factory=list)
    safety_flags: list[SafetyFlag] = Field(default_factory=list)
    verification_limitations: str = Field(
        description=(
            "Honest statement of what this verification can and cannot detect. "
            "Required in every output. This is Principle 13 in practice."
        )
    )
    passed: bool = Field(
        description="True if no blocking cross_section_issues and no safety_flags."
    )
    verifier_model: str = Field(description="Model ID used (must differ from Gate 2 model).")


# =============================================================================
# PIPELINE RUN LOG
# Every execution of the pipeline produces one of these.
# This is what Layer 5 (Adaptive Intelligence) monitors over time.
# =============================================================================

class PipelineRunLog(BaseModel):
    """
    Per-run observability record. Logged for every pipeline execution.
    Aggregate metrics tracked across runs feed into Layer 5 drift detection.
    """
    run_id: str                             # Unique identifier for this run
    company_ticker: str                     # e.g. "MSFT"
    quarter: str                            # e.g. "Q2 FY2026"
    transcript_token_count: int
    fact_count: int
    fact_types_distribution: dict[str, int] # e.g. {"financial_metric": 12, ...}
    gate_1a_pass_rate: float
    per_section_grounding_score: dict[str, float]       # section_id -> score
    per_section_contradiction_count: dict[str, int]     # section_id -> count
    retry_count_per_section: dict[str, int]             # section_id -> retries used
    radar_score_agreement: dict[str, bool]              # dimension -> agreed?
    degradation_level_reached: DegradationLevel
    total_tokens_consumed: int
    total_latency_seconds: float
    models_used: dict[str, str]     # stage_name -> model_id
    final_output_status: FinalOutputStatus
    omitted_sections: list[str] = Field(
        default_factory=list,
        description="Section IDs omitted due to Level 2 degradation."
    )
    safety_flags_triggered: list[str] = Field(
        default_factory=list,
        description="Descriptions of any safety flags that triggered Level 3 halt."
    )
