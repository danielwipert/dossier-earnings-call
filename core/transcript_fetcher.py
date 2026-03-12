"""
Chorus AI Systems — Earnings Call Dossier
Transcript Fetcher v1.0

Retrieves earnings call transcripts from two sources:
  1. Financial Modeling Prep (FMP) API — free tier, 250 requests/day
     Sign up at: https://financialmodelingprep.com/developer/docs/
     Add FMP_API_KEY to your .env file.

  2. Manual file — pass any .txt or .pdf file directly.
     Use this when you already have a transcript saved locally.

Usage examples:
    # Fetch from FMP by ticker + quarter
    from transcript_fetcher import fetch_transcript
    transcript = fetch_transcript(ticker="MSFT", year=2026, quarter=2)

    # Load from a local file
    transcript = fetch_transcript(filepath="msft_q2_2026.txt")

    # Command-line usage
    python transcript_fetcher.py --ticker MSFT --year 2026 --quarter 2
    python transcript_fetcher.py --file my_transcript.txt
"""

import os
import re
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


# =============================================================================
# MAIN ENTRY POINT
# Call this from pipeline.py — it handles both sources transparently.
# =============================================================================

def fetch_transcript(
    ticker: str = None,
    year: int = None,
    quarter: int = None,
    filepath: str = None
) -> str:
    """
    Fetch an earnings call transcript. Returns the raw text.

    You must provide EITHER:
      - ticker + year + quarter  (fetches from FMP API)
      - filepath                 (loads from local file)

    Args:
        ticker:   Stock ticker symbol, e.g. "MSFT", "AAPL"
        year:     Calendar year of the earnings call, e.g. 2026
        quarter:  Calendar quarter (1, 2, 3, or 4)
        filepath: Path to a local .txt file containing the transcript

    Returns:
        The transcript as a plain text string, cleaned and ready for the pipeline.

    Raises:
        ValueError if required arguments are missing
        RuntimeError if the transcript cannot be fetched or loaded
    """
    if filepath:
        return _load_from_file(filepath)
    elif ticker and year and quarter:
        return _fetch_from_fmp(ticker, year, quarter)
    else:
        raise ValueError(
            "Provide either (ticker + year + quarter) or filepath.\n"
            "Example: fetch_transcript(ticker='MSFT', year=2026, quarter=2)\n"
            "Example: fetch_transcript(filepath='transcript.txt')"
        )


# =============================================================================
# SOURCE 1: FINANCIAL MODELING PREP API
# Free tier: 250 requests/day. Requires FMP_API_KEY in .env
# =============================================================================

def _fetch_from_fmp(ticker: str, year: int, quarter: int) -> str:
    """
    Fetch a transcript from the Financial Modeling Prep API.

    FMP endpoint: GET /earning_call_transcript/{ticker}?quarter={q}&year={y}
    Returns a list of transcript objects. We take the first (most recent match).

    Note on quarters: FMP uses fiscal quarters as reported by the company.
    For most US companies this aligns with calendar quarters, but verify
    for companies with non-calendar fiscal years (e.g. Microsoft's FY ends in June).
    """
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        raise RuntimeError(
            "FMP_API_KEY not found in environment.\n"
            "1. Get a free key at https://financialmodelingprep.com/developer/docs/\n"
            "2. Add FMP_API_KEY=your_key_here to your .env file"
        )

    ticker = ticker.upper()
    url = f"{FMP_BASE_URL}/earning_call_transcript/{ticker}"
    params = {
        "quarter": quarter,
        "year": year,
        "apikey": api_key
    }

    print(f"Fetching transcript: {ticker} Q{quarter} {year} from FMP API...")

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"FMP API request failed: {e}")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to FMP API. Check your internet connection.")
    except requests.exceptions.Timeout:
        raise RuntimeError("FMP API request timed out. Try again.")

    data = response.json()

    # Handle API error responses (FMP returns them as dicts, not HTTP errors)
    if isinstance(data, dict) and "Error Message" in data:
        raise RuntimeError(f"FMP API error: {data['Error Message']}")

    if not data:
        raise RuntimeError(
            f"No transcript found for {ticker} Q{quarter} {year}.\n"
            f"This may mean:\n"
            f"  - The transcript isn't available yet (earnings haven't happened)\n"
            f"  - The quarter/year combination doesn't match FMP's records\n"
            f"  - This ticker isn't covered by FMP\n"
            f"Try fetching the transcript list first: list_available_transcripts('{ticker}')"
        )

    # FMP returns a list — take the first result
    transcript_obj = data[0]
    raw_content = transcript_obj.get("content", "")

    if not raw_content:
        raise RuntimeError(f"FMP returned a transcript object for {ticker} Q{quarter} {year} but content is empty.")

    # Clean and return
    transcript = _clean_transcript(raw_content)

    print(f"✓ Transcript fetched: {len(transcript.split())} words, {len(transcript)} characters")
    return transcript


def list_available_transcripts(ticker: str, limit: int = 10) -> list[dict]:
    """
    List available transcripts for a ticker from FMP.
    Useful for discovering what quarters are available before fetching.

    Returns a list of dicts with keys: symbol, quarter, year, date
    """
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        raise RuntimeError("FMP_API_KEY not found in environment.")

    ticker = ticker.upper()
    url = f"{FMP_BASE_URL}/earning_call_transcript/{ticker}"
    params = {"apikey": api_key}

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and "Error Message" in data:
        raise RuntimeError(f"FMP API error: {data['Error Message']}")

    # Return the most recent N transcripts (summary info only, not full content)
    results = []
    for item in data[:limit]:
        results.append({
            "ticker": item.get("symbol", ticker),
            "quarter": item.get("quarter"),
            "year": item.get("year"),
            "date": item.get("date", "unknown"),
        })

    return results


# =============================================================================
# SOURCE 2: LOCAL FILE
# The always-works fallback. Accepts .txt files.
# =============================================================================

def _load_from_file(filepath: str) -> str:
    """
    Load a transcript from a local .txt or .pdf file.

    The file should be the raw transcript text as you'd read it:
    speaker names, their remarks, Q&A section, etc.
    """
    path = Path(filepath)

    if not path.exists():
        raise RuntimeError(f"File not found: {filepath}")

    suffix = path.suffix.lower()

    if suffix == ".txt":
        print(f"Loading transcript from file: {filepath}")
        with open(path, "r", encoding="utf-8") as f:
            raw_content = f.read()

    elif suffix == ".pdf":
        print(f"Loading transcript from PDF: {filepath}")
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError(
                "pdfplumber is required to read PDF files.\n"
                "Run: pip install pdfplumber"
            )
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        raw_content = "\n\n".join(pages)

    else:
        raise RuntimeError(
            f"Unsupported file type: {suffix}\n"
            f"Supported types: .txt, .pdf"
        )

    if not raw_content.strip():
        raise RuntimeError(f"File is empty or no text could be extracted: {filepath}")

    transcript = _clean_transcript(raw_content)
    print(f"✓ Transcript loaded: {len(transcript.split())} words, {len(transcript)} characters")
    return transcript


# =============================================================================
# TEXT CLEANING
# Normalizes whitespace and removes common artifacts.
# Does NOT remove content — just cleans formatting.
# =============================================================================

def _clean_transcript(text: str) -> str:
    """
    Clean a transcript for pipeline input.

    What this does:
    - Normalizes line endings (Windows \r\n → \n)
    - Collapses excessive blank lines (4+ blank lines → 2)
    - Strips leading/trailing whitespace
    - Removes common boilerplate headers (copyright notices, page numbers)

    What this does NOT do:
    - Remove any substantive content
    - Reformat speaker attribution
    - Summarize or truncate
    """
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove common PDF/scraper artifacts
    # Page numbers like "Page 1 of 12" or just "1" on their own line
    text = re.sub(r'\n\s*Page \d+ of \d+\s*\n', '\n', text)

    # Copyright lines commonly found in scraped transcripts
    text = re.sub(r'\n.*Copyright.*\d{4}.*\n', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\n.*All rights reserved.*\n', '\n', text, flags=re.IGNORECASE)

    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


# =============================================================================
# VALIDATION
# Quick checks before handing the transcript to the pipeline.
# =============================================================================

def validate_transcript(transcript: str) -> dict:
    """
    Run basic validation checks on a transcript before pipeline ingestion.

    Returns a dict with:
      - valid: bool
      - word_count: int
      - issues: list of warning strings (non-blocking)
      - errors: list of error strings (blocking — don't pass to pipeline)
    """
    issues = []
    errors = []

    word_count = len(transcript.split())
    char_count = len(transcript)

    # Rough token estimate (1 token ≈ 0.75 words for English)
    estimated_tokens = int(word_count / 0.75)

    # Check minimum length — earnings calls are typically 5,000+ words
    if word_count < 1000:
        errors.append(
            f"Transcript is very short ({word_count} words). "
            f"A typical earnings call is 5,000-15,000 words. "
            f"This may not be a complete transcript."
        )

    # Check maximum length — pipeline limit is 50,000 tokens
    if estimated_tokens > 50000:
        errors.append(
            f"Transcript is too long (~{estimated_tokens} estimated tokens, limit is 50,000). "
            f"Consider trimming to the main prepared remarks and Q&A."
        )

    # Warn if it looks short for an earnings call
    if 1000 <= word_count < 3000:
        issues.append(
            f"Transcript is shorter than typical ({word_count} words). "
            f"Results may be less complete."
        )

    # Check for common earnings call markers
    has_qa = any(phrase in transcript.lower() for phrase in [
        "question and answer", "q&a", "questions from", "operator:", "your line is open"
    ])
    if not has_qa:
        issues.append(
            "No Q&A section detected. The transcript may be prepared remarks only. "
            "The Gap Analysis section works best with a complete transcript including Q&A."
        )

    # Check for financial figures
    has_numbers = bool(re.search(r'\$[\d,.]+[BMK]?', transcript))
    if not has_numbers:
        issues.append("No financial figures detected. Verify this is a financial earnings transcript.")

    valid = len(errors) == 0

    return {
        "valid": valid,
        "word_count": word_count,
        "estimated_tokens": estimated_tokens,
        "has_qa_section": has_qa,
        "issues": issues,
        "errors": errors
    }


# =============================================================================
# COMMAND-LINE INTERFACE
# python transcript_fetcher.py --ticker MSFT --year 2026 --quarter 2
# python transcript_fetcher.py --file my_transcript.txt
# python transcript_fetcher.py --list MSFT
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch an earnings call transcript for the Chorus AI pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Fetch from FMP API:
    python transcript_fetcher.py --ticker MSFT --year 2026 --quarter 2

  Load from local file:
    python transcript_fetcher.py --file my_transcript.txt

  List available transcripts for a ticker:
    python transcript_fetcher.py --list MSFT

  Save fetched transcript to a file:
    python transcript_fetcher.py --ticker AAPL --year 2025 --quarter 4 --save aapl_q4_2025.txt
        """
    )

    parser.add_argument("--ticker", help="Stock ticker symbol (e.g. MSFT)")
    parser.add_argument("--year", type=int, help="Year of the earnings call (e.g. 2026)")
    parser.add_argument("--quarter", type=int, choices=[1, 2, 3, 4], help="Quarter (1-4)")
    parser.add_argument("--file", help="Path to a local transcript .txt file")
    parser.add_argument("--list", metavar="TICKER", help="List available transcripts for a ticker")
    parser.add_argument("--save", help="Save the fetched transcript to this file path")

    args = parser.parse_args()

    if args.list:
        print(f"\nAvailable transcripts for {args.list.upper()}:")
        available = list_available_transcripts(args.list)
        for t in available:
            print(f"  Q{t['quarter']} {t['year']}  ({t['date']})")
        print()

    elif args.file:
        transcript = fetch_transcript(filepath=args.file)
        validation = validate_transcript(transcript)

        print(f"\nValidation results:")
        print(f"  Word count:        {validation['word_count']:,}")
        print(f"  Estimated tokens:  {validation['estimated_tokens']:,}")
        print(f"  Has Q&A section:   {validation['has_qa_section']}")

        if validation["issues"]:
            for issue in validation["issues"]:
                print(f"  ⚠ {issue}")
        if validation["errors"]:
            for error in validation["errors"]:
                print(f"  ✗ {error}")
        if validation["valid"]:
            print(f"  ✓ Ready for pipeline")

        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(transcript)
            print(f"\nSaved to {args.save}")

    elif args.ticker and args.year and args.quarter:
        transcript = fetch_transcript(ticker=args.ticker, year=args.year, quarter=args.quarter)
        validation = validate_transcript(transcript)

        print(f"\nValidation results:")
        print(f"  Word count:        {validation['word_count']:,}")
        print(f"  Estimated tokens:  {validation['estimated_tokens']:,}")
        print(f"  Has Q&A section:   {validation['has_qa_section']}")

        if validation["issues"]:
            for issue in validation["issues"]:
                print(f"  ⚠ {issue}")
        if validation["errors"]:
            for error in validation["errors"]:
                print(f"  ✗ {error}")
        if validation["valid"]:
            print(f"  ✓ Ready for pipeline")

        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(transcript)
            print(f"\nSaved to {args.save}")
        else:
            print(f"\nTip: use --save filename.txt to save the transcript to a file")

    else:
        parser.print_help()
