# Chorus AI Systems — Earnings Call Dossier
## Project Brief for Claude Code

---

## What This Project Is

A multi-agent Python pipeline that transforms an earnings call transcript into a
verified analytical brief styled after Financial Times / New Yorker editorial quality.

The core architectural commitment: **trust is structural, not a model property.**
Every factual claim in the output traces back to a verbatim quote from the transcript
through an immutable FactList. Nothing advances between pipeline stages without a
governance gate check.

Built by Daniel Wipert as part of the Chorus AI Systems portfolio.
GitHub: github.com/danielwipert/chorus-ai-earnings-brief

---

## File Map

```
schemas.py            — Pydantic data contracts for every agent input/output
prompts.py            — Prompt template functions for every agent and gate
pipeline.py           — Main orchestrator (run this to process a transcript)
transcript_fetcher.py — Fetches transcripts from FMP API or local .txt file
generate_radar_chart.py — Draws the 7-dimension radar chart PNG (matplotlib)
format_report.js      — Builds the Word doc (docx-js, called by report_formatter.py)
report_formatter.py   — Python wrapper: generates chart + calls JS formatter
.env                  — HF_TOKEN and FMP_API_KEY (never commit this)
```

---

## How to Run

```bash
# Fetch transcript from FMP API and run full pipeline
python pipeline.py --ticker MSFT --year 2026 --quarter 2

# Or use a local transcript file
python pipeline.py --transcript my_transcript.txt

# Format the output as a Word doc
python report_formatter.py --input report_output.json --output MSFT_Q2_Brief.docx

# Check what transcripts are available for a ticker
python transcript_fetcher.py --list MSFT
```

---

## Pipeline Architecture

The pipeline runs in this exact sequence. Gates (⊘) are governance checkpoints —
they evaluate, accept, reject, or halt. They never generate content.

```
TRANSCRIPT INPUT
     ↓
S1a: Fact Extractor         — Extracts every atomic fact with verbatim quote + speaker
     ↓
Gate 1a: FactList Validation — Checks quote fidelity, completeness, pass rate ≥ 90%
     ↓ (HALT if fails — FactList failure poisons everything downstream)
S1b: Structured Data Pull   — Organizes financials from FactList into tables
     ↓
S2a/S2b/S2c/S2d (PARALLEL) — Four analyst agents, each writing one report section
     ↓
Gate 2: Fact Verifier       — Verifies every claim against FactList (per section)
     ↓ (retry up to 2x per section; omit section after that)
S3: Radar Scorer            — Scores 7 dimensions using TWO independent models
     ↓
S4: Report Compiler         — Deterministic assembly (no generation)
     ↓
S5: Holistic Verifier       — Cross-section consistency + investment advice scan
     ↓
OUTPUT: report_output.json
```

---

## The FactList — Most Important Concept

The FactList is the locked, immutable foundation of the entire pipeline.

- S1a extracts every fact with a **verbatim_quote** (character-exact from transcript)
- Gate 1a validates every quote exists in the source
- After Gate 1a passes, **no agent may add, modify, or remove facts**
- Every downstream claim cites `source_fact_ids` pointing back to FactList entries
- Gate 2 verifies claims by looking up those fact IDs

This is the traceability chain:
```
Final report claim → Gate 2 verdict → FactList fact_id → verbatim_quote → Gate 1a check
```

If any link in this chain breaks, the system halts rather than produce unverifiable output.

---

## Seven Fact Types (S1a extracts these)

| Type | What it captures |
|---|---|
| `financial_metric` | Revenue, EPS, margins, CapEx — any quantitative financial figure |
| `management_statement` | Qualitative assertion by a named executive |
| `forward_guidance` | Any forward-looking projection or target |
| `analyst_question` | Questions posed during Q&A (enables gap analysis) |
| `competitive_reference` | Any mention of competitors or market position |
| `operational_metric` | Non-financial operating data (seat counts, usage metrics) |
| `prior_quarter_reference` | References to prior quarter data or prior commitments |

---

## Three Claim Types (S2 agents label every claim)

| Type | Meaning | Requires |
|---|---|---|
| `grounded` | Directly supported by a FactList entry | `source_fact_ids` |
| `derived` | Calculated from facts | `source_fact_ids` + `derivation_note` |
| `interpretive` | Editorial judgment | Must be labeled as such; max 20% of claims |

Gate 2 verdicts: `aligned` / `absent` / `contradicted`
Pass condition: grounding_score ≥ 0.95 AND contradiction_count == 0

---

## Graceful Degradation (Four Levels)

| Level | Name | Trigger | Behavior |
|---|---|---|---|
| 0 | Normal | All gates pass | Full report |
| 1 | Retry | Gate rejects section | Return to agent (max 2 retries) |
| 2 | Partial Output | Section fails all retries | Omit section, note in report |
| 3 | Pipeline Halt | FactList failure, >2 sections fail, or safety flag | No output released |

A FactList failure (Gate 1a) **always** triggers Level 3. No partial output when the foundation is bad.

---

## Model Configuration

**Key principle: generation and verification must use different models (Principle 13).**
Same-model self-verification shares the same blind spots — it adds no real verification value.

```python
GENERATION_MODEL    = "Qwen/Qwen2.5-72B-Instruct"   # S1a, S1b, S2a-d
VERIFICATION_MODEL_A = "Qwen/Qwen2.5-7B-Instruct"    # Gate 1a, Gate 2
VERIFICATION_MODEL_B = "meta-llama/Llama-3.2-3B-Instruct"  # S5 (different family)
SCORING_MODEL_A     = "Qwen/Qwen2.5-7B-Instruct"     # S3 first scorer
SCORING_MODEL_B     = "meta-llama/Llama-3.2-3B-Instruct"   # S3 second scorer
```

All models are called via HuggingFace `InferenceClient` using the chat completions format:
```python
client = InferenceClient(model=model_id, token=os.getenv("HF_TOKEN"))
response = client.chat_completion(
    messages=[{"role": "user", "content": prompt}],
    max_tokens=4000
)
```

---

## Seven Radar Dimensions (S3 scoring)

Scored 1–10 by two independent models. Disagreements >3 points → adjudicated midpoint,
disagreement disclosed in the Verification Report.

1. **Revenue Momentum** — YoY growth rate, sequential acceleration, vs. consensus
2. **Margin Health** — Operating margin direction, CapEx-to-revenue trajectory
3. **Guidance Confidence** — Count of specific forward commitments provided
4. **Mgmt Transparency** — Direct vs. evasive Q&A; deduct per redirected question
5. **Strategic Clarity** — Coherence between stated priorities and capital allocation
6. **Earnings Quality** — Recurring revenue % minus one-time item adjustments
7. **Forward Visibility** — Count of discrete forward-looking data points

---

## Output Report Structure

The final Word doc (via report_formatter.py) has this structure:
1. **The Snapshot** — company summary, key financials table, headline, three takeaways
2. **Signals at a Glance** — green/red flags table (derived from S2b + S2c claims)
3. **Quarter-at-a-Glance** — radar chart + 7-dimension score table
4. **The Quarter in Context** — S2a narrative (what drove results, margin story)
5. **What Management Is Signaling** — S2b narrative (language, thesis, guidance)
6. **What Wasn't Said** — S2c narrative (omissions, redirected questions, gaps)
7. **The Bigger Picture** — S2d narrative (macro, industry, what to watch)
8. **Verification Report** — grounding scores, contradiction check, model disagreements, limitations

---

## Environment Variables Required

```
HF_TOKEN=your_huggingface_token     # All model calls
FMP_API_KEY=your_fmp_key            # Transcript fetching (free tier: 250 req/day)
```

FMP (Financial Modeling Prep) free tier is sufficient for testing.
Sign up at: financialmodelingprep.com/developer/docs

---

## Key Design Constraints — Never Violate These

- **No unverified output.** If the verification pipeline is unavailable, halt. No fallback.
- **No investment advice.** S5 scans for buy/sell/hold language. If found → Level 3 halt.
- **No fabricated quotes.** If a verbatim quote can't be found in the transcript → reject the fact.
- **Verification limitations must be disclosed.** Every output includes what the verification
  can and cannot catch. This is Principle 13 (Second-Order Self-Observation) in practice.
- **Generation and verification must use different models.** Always. No exceptions.
- **FactList is immutable after Gate 1a.** No downstream agent may alter it.

---

## Theoretical Foundation (for context)

The architecture is grounded in three cybernetic frameworks adapted for AI:

- **Beer's Viable System Model** → the seven-layer pipeline structure
- **Ashby's Law of Requisite Variety** → governance capacity must match system complexity;
  multi-model verification amplifies the controller's variety
- **Von Foerster's Second-Order Cybernetics** → the system must observe its own observation
  processes; observers (Gate 2, S5) must be structurally diverse to avoid shared blind spots

Full specification: see `Governing_Principles.docx` and `Earnings_Call_Dossier_Architecture_v1.docx`

---

## What's Not Built Yet

- **Report formatter for prior quarter comparison** — radar chart supports it (`prior_scores`
  param exists in `generate_radar_chart.py`) but the pipeline doesn't fetch prior quarter
  scores automatically yet
- **Token counting per agent call** — `total_tokens_consumed` in PipelineRunLog is logged
  as 0; needs to be wired up for cost tracking
- **Layer 5 aggregate monitoring** — per-run metrics are logged but the drift detection
  and structural change proposals aren't implemented yet
- **Streamlit web UI** — command-line only for now
