"""
Chorus AI Systems — S7: Econ Expert Agent
Runs after S6 editorial synthesis, before report assembly.

Two-step process:
  1. LLM reads the assembled report text and generates 6-8 targeted FAISS queries.
  2. Queries are run against the textbook FAISS index. Retrieved passages are
     deduplicated and passed back to the LLM to write "The Econ Expert's Take".

The FAISS index and metadata are loaded once at first call and cached for the
lifetime of the process (lazy singleton pattern).
"""

import json
import numpy as np
from pathlib import Path
from typing import Optional

INDEX_PATH    = "knowledge_base/textbooks.index"
METADATA_PATH = "knowledge_base/metadata.json"
EMBED_MODEL   = "all-MiniLM-L6-v2"
TOP_K         = 5   # chunks retrieved per query


# =============================================================================
# LAZY SINGLETON — load index + model once, reuse across calls
# =============================================================================

_index    = None
_metadata = None
_model    = None


def _load_knowledge_base():
    """Load FAISS index, metadata, and embedding model on first call."""
    global _index, _metadata, _model

    if _index is not None:
        return  # already loaded

    # Ensure HF_HOME is set from .env before loading the model
    import os
    from dotenv import load_dotenv
    load_dotenv()

    import faiss
    from sentence_transformers import SentenceTransformer

    if not Path(INDEX_PATH).exists():
        raise FileNotFoundError(
            f"FAISS index not found at '{INDEX_PATH}'. "
            "Run 'python knowledge_base.py' first to build it."
        )

    print("  [S7] Loading FAISS index and embedding model (first call only)...")
    _index = faiss.read_index(INDEX_PATH)
    with open(METADATA_PATH, encoding="utf-8") as f:
        _metadata = json.load(f)
    _model = SentenceTransformer(EMBED_MODEL)
    print(f"  [S7] Index ready: {_index.ntotal} vectors from {len(_metadata)} chunks.")


# =============================================================================
# FAISS RETRIEVAL
# =============================================================================

def _retrieve_passages(queries: list[str], top_k: int = TOP_K) -> list[dict]:
    """
    Run all queries against the FAISS index. Return deduplicated top chunks,
    sorted by lowest distance (closest match).
    """
    _load_knowledge_base()

    query_vecs = _model.encode(queries)
    query_vecs = np.array(query_vecs, dtype=np.float32)

    distances, indices = _index.search(query_vecs, top_k)

    seen      = set()
    results   = []

    for q_distances, q_indices in zip(distances, indices):
        for dist, idx in zip(q_distances, q_indices):
            if idx < 0 or idx >= len(_metadata):
                continue
            if idx in seen:
                continue
            seen.add(idx)
            chunk = _metadata[idx].copy()
            chunk["_distance"] = float(dist)
            results.append(chunk)

    # Sort globally by distance (closest first), keep top 30 total
    results.sort(key=lambda x: x["_distance"])
    return results[:30]


def _format_passages_for_prompt(passages: list[dict]) -> str:
    """
    Format retrieved chunks into a readable text block for the LLM.
    Each passage shows its source and a text excerpt.
    """
    lines = []
    for i, p in enumerate(passages, 1):
        book  = p.get("book_title", "Unknown")
        page  = p.get("page_num", "?")
        text  = p.get("text", "").strip()
        # Trim very long chunks for token efficiency
        if len(text) > 800:
            text = text[:800] + "..."
        lines.append(f"[Passage {i} — {book}, p.{page}]\n{text}")
    return "\n\n".join(lines)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def run_s7(
    report_text: str,
    call_model_fn,          # pipeline's call_model(prompt, model_id, max_tokens) callable
    parse_json_fn,          # pipeline's parse_json_response(raw) callable
    generation_model: str,
) -> Optional[object]:
    """
    Orchestrate S7: query generation → FAISS retrieval → section writing.

    Returns an S7Output instance, or None if the FAISS index is unavailable
    (graceful degradation — the rest of the report is unaffected).
    """
    from core.schemas import S7Output, TextbookCitation
    from core.prompts import s7_query_generator, s7_econ_expert_writer

    # --- Graceful degradation: skip if index not built ---
    if not Path(INDEX_PATH).exists():
        print("  [S7] FAISS index not found — skipping Econ Expert section (Level 2 degradation).")
        print("       Run 'python knowledge_base.py' to enable this section.")
        return None

    print("  Running S7: Econ Expert (query generation + FAISS retrieval + writing)...")

    # Step 1: LLM generates targeted search queries
    query_prompt = s7_query_generator(report_text)
    raw_queries  = call_model_fn(query_prompt, generation_model, max_tokens=500)

    try:
        # Strip markdown fences if the model adds them
        clean = raw_queries.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        queries = json.loads(clean)
        if not isinstance(queries, list):
            raise ValueError("Expected a JSON array")
        queries = [str(q).strip() for q in queries if str(q).strip()][:8]
    except Exception as e:
        print(f"  [S7] Query parsing failed ({e}) — using fallback queries.")
        queries = [
            "operating leverage cost structure revenue growth",
            "competitive strategy market positioning",
            "capital allocation management incentives",
            "earnings quality revenue recognition",
            "platform economics network effects",
        ]

    print(f"  [S7] Generated {len(queries)} queries: {queries}")

    # Step 2: Retrieve textbook passages from FAISS
    try:
        passages = _retrieve_passages(queries)
    except FileNotFoundError as e:
        print(f"  [S7] {e} — skipping.")
        return None

    passages_text = _format_passages_for_prompt(passages)
    print(f"  [S7] Retrieved {len(passages)} deduplicated passages from {len(set(p['book_title'] for p in passages))} books.")

    # Step 3: LLM writes the section
    write_prompt = s7_econ_expert_writer(report_text, passages_text)
    raw_section  = call_model_fn(write_prompt, generation_model, max_tokens=4000)
    data         = parse_json_fn(raw_section)

    # Build citations from retrieved passages (use only cited books)
    cited_books = set()
    citations   = []
    for p in passages:
        book = p.get("book_title", "")
        if book and book not in cited_books:
            cited_books.add(book)
            llm_cite_list = data.get("textbook_citations") or []
            first_relevance = llm_cite_list[0].get("relevance", "Retrieved passage") if llm_cite_list else "Retrieved passage"
            citations.append(TextbookCitation(
                book_title=book,
                page_num=p.get("page_num", 0),
                relevance=first_relevance if not citations else "Retrieved passage",
            ))

    # Prefer the LLM's own citation list if it provided one and is richer
    llm_citations = data.get("textbook_citations", [])
    if llm_citations and len(llm_citations) >= len(citations):
        citations = [
            TextbookCitation(
                book_title=c.get("book_title", "Unknown"),
                page_num=c.get("page_num", 0),
                relevance=c.get("relevance", ""),
            )
            for c in llm_citations
        ]

    from core.schemas import TheoryPoint

    def _parse_theory_points(raw: list) -> list[TheoryPoint]:
        out = []
        for item in (raw or []):
            if isinstance(item, dict):
                out.append(TheoryPoint(
                    concept=item.get("concept", ""),
                    explanation=item.get("explanation", ""),
                ))
        return out

    result = S7Output(
        section_id="S7",
        section_title=data.get("section_title", "Business Principles"),
        narrative=data.get("narrative", ""),
        smart_moves=_parse_theory_points(data.get("smart_moves", [])),
        questionable_calls=_parse_theory_points(data.get("questionable_calls", [])),
        textbook_citations=citations,
        generating_model=generation_model,
    )

    print(f"  ✓ S7 complete: Business Principles written "
          f"({len(result.smart_moves)} smart, {len(result.questionable_calls)} questionable, "
          f"{len(result.textbook_citations)} textbook citations)")
    return result
