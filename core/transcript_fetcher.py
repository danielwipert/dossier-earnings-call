"""
Chorus AI Systems — Earnings Call Dossier
Transcript Fetcher v1.0

Retrieves earnings call transcripts from three sources:
  1. SEC EDGAR (free, no key required)
     Searches EDGAR full-text for 8-K exhibits containing transcript content.
     Works for most companies that file transcripts with the SEC.
     Best for: large-caps, REITs, financials.
     Note: some large companies (AAPL, MSFT) don't file transcripts with SEC.

  2. Financial Modeling Prep (FMP) — requires Ultimate plan ($149/mo)
     Add FMP_API_KEY to your .env file.

  3. Manual file — pass any .txt or .pdf file directly.
     Use this when you already have a transcript saved locally.

Usage examples:
    # Fetch from EDGAR (default, free)
    from transcript_fetcher import fetch_transcript
    transcript = fetch_transcript(ticker="MCD", year=2025, quarter=4)

    # Load from a local file
    transcript = fetch_transcript(filepath="msft_q2_2026.txt")

    # Command-line usage
    python transcript_fetcher.py --ticker MCD --year 2025 --quarter 4
    python transcript_fetcher.py --file my_transcript.txt
"""

import os
import re
import time
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

FMP_BASE_URL      = "https://financialmodelingprep.com/stable"
FINNHUB_BASE_URL  = "https://finnhub.io/api/v1"
EDGAR_SEARCH_URL  = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
EDGAR_ARCHIVES    = "https://www.sec.gov/Archives/edgar/data"
EDGAR_HEADERS     = {"User-Agent": "dossier.ec research@dossier.ec"}


# =============================================================================
# MAIN ENTRY POINT
# Call this from pipeline.py — it handles both sources transparently.
# =============================================================================

def fetch_transcript(
    ticker: str = None,
    year: int = None,
    quarter: int = None,
    filepath: str = None,
    source: str = "auto",
) -> str:
    """
    Fetch an earnings call transcript. Returns the raw text.

    You must provide EITHER:
      - ticker + year + quarter  (fetches from API)
      - filepath                 (loads from local file)

    Args:
        ticker:   Stock ticker symbol, e.g. "MSFT", "AAPL"
        year:     Calendar year of the earnings call, e.g. 2026
        quarter:  Calendar quarter (1, 2, 3, or 4)
        filepath: Path to a local .txt or .pdf file containing the transcript
        source:   "auto" | "finnhub" | "fmp"
                  "auto" tries Finnhub first (if FINNHUB_API_KEY is set),
                  then falls back to FMP (if FMP_API_KEY is set).

    Returns:
        The transcript as a plain text string, cleaned and ready for the pipeline.

    Raises:
        ValueError if required arguments are missing
        RuntimeError if the transcript cannot be fetched or loaded
    """
    if filepath:
        return _load_from_file(filepath)
    elif ticker and year and quarter:
        source = source.lower()
        if source == "edgar":
            return _fetch_from_edgar(ticker, year, quarter)
        elif source == "finnhub":
            return _fetch_from_finnhub(ticker, year, quarter)
        elif source == "fmp":
            return _fetch_from_fmp(ticker, year, quarter)
        else:
            # Auto: EDGAR first (free, no key), then keyed sources
            try:
                return _fetch_from_edgar(ticker, year, quarter)
            except RuntimeError as edgar_err:
                if os.getenv("FMP_API_KEY"):
                    print(f"  EDGAR: {edgar_err}\n  Falling back to FMP...")
                    return _fetch_from_fmp(ticker, year, quarter)
                raise RuntimeError(
                    f"EDGAR fetch failed: {edgar_err}\n"
                    "If this company doesn't file transcripts with the SEC, use --file to\n"
                    "pass a local transcript file instead."
                )
    else:
        raise ValueError(
            "Provide either (ticker + year + quarter) or filepath.\n"
            "Example: fetch_transcript(ticker='MSFT', year=2026, quarter=2)\n"
            "Example: fetch_transcript(filepath='transcript.txt')"
        )


# =============================================================================
# SOURCE 1: SEC EDGAR (FREE — no API key required)
# Strategy:
#   1. Resolve ticker → CIK via EDGAR submissions API
#   2. Search EDGAR full-text (EFTS) for 8-K exhibits containing transcript
#      content filed around the expected earnings date for that quarter
#   3. Score candidates by transcript signal words; fetch the best match
#   4. Strip HTML and clean the text
#
# Limitation: only works for companies that file transcripts as 8-K exhibits.
# Most large-caps (AAPL, MSFT, GOOGL) do NOT file transcripts with the SEC —
# they publish them on their IR pages instead. For those, use --file.
# =============================================================================

def _fetch_from_edgar(ticker: str, year: int, quarter: int) -> str:
    """
    Fetch an earnings call transcript from SEC EDGAR. Free, no API key needed.

    Uses EDGAR full-text search to find 8-K exhibits containing transcript
    content (detected by keywords like "Operator", "prepared remarks", Q&A markers)
    filed around the expected earnings date for the given quarter.
    """
    ticker = ticker.upper()
    print(f"Fetching transcript: {ticker} Q{quarter} {year} from SEC EDGAR (free)...")

    # Step 1: Resolve ticker to CIK
    cik, company_name = _edgar_resolve_cik(ticker)
    print(f"  Resolved {ticker} -> CIK {cik} ({company_name})")

    # Step 2: Calculate the date window when earnings are typically filed
    # Earnings calls happen ~4-6 weeks after quarter end:
    #   Q1 (Jan-Mar) → filed Apr-May
    #   Q2 (Apr-Jun) → filed Jul-Aug
    #   Q3 (Jul-Sep) → filed Oct-Nov
    #   Q4 (Oct-Dec) → filed Jan-Feb of next year
    quarter_end_month = quarter * 3
    filing_start_month = quarter_end_month + 1
    filing_year = year
    if quarter == 4:
        filing_start_month = 1
        filing_year = year + 1

    import datetime
    start_date = datetime.date(filing_year, filing_start_month, 1)
    # Allow a generous 3-month window to cover fiscal year variations
    end_month = filing_start_month + 2
    end_year = filing_year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    end_date = datetime.date(end_year, end_month, 28)

    print(f"  Searching EDGAR filings from {start_date} to {end_date}...")

    # Step 3: Full-text search for transcript-like 8-K exhibits
    # "Operator" appears in virtually every earnings call transcript
    transcript = _edgar_search_and_fetch(cik, ticker, start_date, end_date, year, quarter)
    if not transcript:
        raise RuntimeError(
            f"No earnings call transcript found on EDGAR for {ticker} Q{quarter} {year}.\n"
            f"This company likely does not file transcripts with the SEC.\n"
            f"Options:\n"
            f"  1. Download the transcript manually and use: --file transcript.txt\n"
            f"     (Seeking Alpha, Motley Fool, or the company's IR page)\n"
            f"  2. Try a different source: --source fmp (requires FMP Ultimate plan)"
        )

    cleaned = _clean_transcript(transcript)
    print(f"OK Transcript fetched: {len(cleaned.split())} words, {len(cleaned)} characters")
    return cleaned


def _edgar_resolve_cik(ticker: str) -> tuple[str, str]:
    """Resolve a ticker symbol to an SEC CIK number."""
    resp = requests.get(
        "https://www.sec.gov/cgi-bin/browse-edgar",
        params={"company": "", "CIK": ticker, "type": "8-K", "action": "getcompany", "output": "atom"},
        headers=EDGAR_HEADERS,
        timeout=20,
    )
    resp.raise_for_status()

    # Parse CIK from the atom feed
    cik_match = re.search(r"CIK=(\d+)", resp.url)
    if not cik_match:
        cik_match = re.search(r"<cik>(\d+)</cik>", resp.text)
    if not cik_match:
        # Try the submissions JSON directly
        resp2 = requests.get(
            f"https://data.sec.gov/submissions/CIK{ticker.zfill(10)}.json",
            headers=EDGAR_HEADERS,
            timeout=20,
        )
        if resp2.status_code == 200:
            data = resp2.json()
            return str(data["cik"]), data.get("name", ticker)
        raise RuntimeError(
            f"Could not resolve ticker '{ticker}' to an SEC CIK number.\n"
            "Verify the ticker is a US-listed company."
        )

    cik = cik_match.group(1).lstrip("0") or "0"
    # Get the company name from submissions
    time.sleep(0.1)  # Respect SEC rate limit (10 req/sec)
    resp3 = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json",
        headers=EDGAR_HEADERS,
        timeout=20,
    )
    name = ticker
    if resp3.status_code == 200:
        name = resp3.json().get("name", ticker)
        cik  = str(resp3.json().get("cik", cik))

    return cik, name


def _edgar_search_and_fetch(cik: str, ticker: str, start_date, end_date, year: int, quarter: int) -> str | None:
    """
    Fetch 8-K filings directly from the company's CIK filing history,
    then scan each filing's exhibits for earnings call transcript content.

    Uses the EDGAR submissions API to get the authoritative list of filings
    for this specific company — avoids false positives from full-text search.
    """
    cik_clean = str(cik).lstrip("0") or "0"
    cik_padded = cik_clean.zfill(10)

    # Get the company's full filing history from EDGAR submissions API
    resp = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
        headers=EDGAR_HEADERS,
        timeout=30,
    )
    time.sleep(0.1)
    if resp.status_code != 200:
        return None

    data = resp.json()
    recent = data.get("filings", {}).get("recent", {})

    forms       = recent.get("form", [])
    dates       = recent.get("filingDate", [])
    accessions  = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    # Find 8-K filings within our date window
    from datetime import date as date_type
    candidate_filings = []
    for form, filing_date_str, accession, primary_doc in zip(forms, dates, accessions, primary_docs):
        if form != "8-K":
            continue
        try:
            fd = date_type.fromisoformat(filing_date_str)
        except ValueError:
            continue
        if start_date <= fd <= end_date:
            candidate_filings.append((filing_date_str, accession, primary_doc))

    if not candidate_filings:
        print(f"  No 8-K filings found for CIK {cik} between {start_date} and {end_date}.")
        return None

    print(f"  Found {len(candidate_filings)} 8-K filing(s) in window — scanning for transcript...")

    # Use edgartools to navigate each filing's exhibits
    try:
        import edgar as edgartools
        edgartools.set_identity("dossier.ec research@dossier.ec")
        from edgar import Company as EdgarCompany
        edgar_company = EdgarCompany(ticker)
        filings_obj = edgar_company.get_filings(form="8-K")
    except Exception:
        edgartools = None
        edgar_company = None
        filings_obj = None

    if filings_obj is not None:
        for filing in filings_obj:
            filing_date_str = str(filing.filing_date)
            # Only look at filings in our window
            from datetime import date as date_type
            try:
                fd = date_type.fromisoformat(filing_date_str)
            except ValueError:
                continue
            if not (start_date <= fd <= end_date):
                continue

            try:
                attachments = filing.attachments
                for doc in attachments.documents:
                    doc_name = getattr(doc, "document", "") or ""
                    if not doc_name.lower().endswith((".htm", ".html", ".txt")):
                        continue
                    print(f"  Trying exhibit: {doc_name} ({filing_date_str})")
                    try:
                        text = doc.text()
                        if not text:
                            continue
                    except Exception:
                        continue
                    if _is_transcript(text):
                        print(f"  OK Transcript content confirmed in {doc_name}")
                        return text
            except Exception:
                continue

    # Fallback: fetch exhibit list via EDGAR filing index HTML
    for filing_date_str, accession, primary_doc in candidate_filings:
        accession_path = accession.replace("-", "")
        # EDGAR filing index page lists all documents
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{accession_path}/"
        time.sleep(0.11)
        idx_resp = requests.get(index_url, headers=EDGAR_HEADERS, timeout=20)
        if idx_resp.status_code != 200:
            continue

        # Extract .htm document links from the index listing
        # Skip EDGAR navigation/boilerplate pages
        EDGAR_NAV_PAGES = {
            "index.htm", "search.htm", "brokers.htm", "quickedgar.htm",
            "howinvestigationswork.html", "privacy.htm", "accessibility.htm",
        }
        doc_links = re.findall(r'href="([^"]+\.(?:htm|html|txt))"', idx_resp.text, re.IGNORECASE)
        for link in doc_links:
            filename = link.split("/")[-1]
            if filename.lower() in EDGAR_NAV_PAGES:
                continue
            if filename.lower() == primary_doc.lower():
                continue  # Skip the main 8-K wrapper
            # Only look at files that look like exhibits (ex99, exhibit, script, transcript, call)
            name_lower = filename.lower()
            if not re.search(r'ex\d+|exhibit\d+|_ex|99\d?|script|transcript|call', name_lower):
                continue
            exhibit_url = f"{EDGAR_ARCHIVES}/{cik_clean}/{accession_path}/{filename}"
            print(f"  Trying exhibit: {filename} ({filing_date_str})")
            time.sleep(0.11)
            doc_resp = requests.get(exhibit_url, headers=EDGAR_HEADERS, timeout=30)
            if doc_resp.status_code != 200:
                continue
            text = _strip_html(doc_resp.text)
            if _is_transcript(text):
                print(f"  OK Transcript content confirmed in {filename}")
                return text

    return None


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    # Remove script and style blocks
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common HTML entities
    entities = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&nbsp;": " ",
                "&quot;": '"', "&#39;": "'", "&rsquo;": "'", "&ldquo;": '"',
                "&rdquo;": '"', "&mdash;": "—", "&ndash;": "–", "&hellip;": "…"}
    for ent, char in entities.items():
        text = text.replace(ent, char)
    # Collapse whitespace (but preserve paragraph breaks)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_transcript(text: str) -> bool:
    """
    Heuristic check: does this document look like an earnings call transcript?
    Requires multiple transcript markers to avoid false positives (press releases, etc.)
    """
    text_lower = text.lower()
    signals = [
        "operator",
        "prepared remarks",
        "question-and-answer",
        "your line is open",
        "please go ahead",
        "thank you. our next",
    ]
    hits = sum(1 for s in signals if s in text_lower)
    # Also require minimum length (transcripts are 5k+ words)
    word_count = len(text.split())
    return hits >= 2 and word_count >= 2000


# =============================================================================
# SOURCE 2: FINNHUB API
# Free tier: 60 calls/min, transcripts included. Requires FINNHUB_API_KEY in .env
# Sign up at: https://finnhub.io/
#
# Two-step process:
#   1. List transcripts for ticker → get IDs + titles
#   2. Fetch the specific transcript by ID → convert speaker segments to text
# =============================================================================

def _fetch_from_finnhub(ticker: str, year: int, quarter: int) -> str:
    """
    Fetch a transcript from the Finnhub API.

    Step 1: GET /transcripts/list?symbol={ticker} → find the matching transcript ID
    Step 2: GET /transcripts?id={id}              → fetch full speaker-segmented transcript

    Matching logic: Finnhub returns a title like "Apple Q1 2024 Earnings Call".
    We match on "Q{quarter}" and the year string. Falls back to timestamp-based
    quarter estimation if the title doesn't contain an explicit quarter label.
    """
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError(
            "FINNHUB_API_KEY not found in environment.\n"
            "1. Get a free key at https://finnhub.io/\n"
            "2. Add FINNHUB_API_KEY=your_key_here to your .env file"
        )

    ticker = ticker.upper()
    print(f"Fetching transcript list for {ticker} from Finnhub...")

    # Step 1: list available transcripts
    list_url = f"{FINNHUB_BASE_URL}/transcripts/list"
    try:
        resp = requests.get(list_url, params={"symbol": ticker, "token": api_key}, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Finnhub transcript list request failed: {e}")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to Finnhub API. Check your internet connection.")
    except requests.exceptions.Timeout:
        raise RuntimeError("Finnhub API request timed out.")

    list_data = resp.json()

    if isinstance(list_data, dict) and list_data.get("error"):
        raise RuntimeError(f"Finnhub API error: {list_data['error']}")

    transcripts = list_data.get("transcript", [])
    if not transcripts:
        raise RuntimeError(
            f"No transcripts found for {ticker} on Finnhub.\n"
            f"This ticker may not be covered or transcripts may not be available yet."
        )

    # Step 2: find the right transcript by matching year + quarter
    transcript_id = _find_finnhub_transcript_id(transcripts, ticker, year, quarter)

    print(f"  Found transcript ID: {transcript_id} — fetching full text...")

    # Step 3: fetch the full transcript
    fetch_url = f"{FINNHUB_BASE_URL}/transcripts"
    try:
        resp = requests.get(fetch_url, params={"id": transcript_id, "token": api_key}, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Finnhub transcript fetch failed: {e}")
    except requests.exceptions.Timeout:
        raise RuntimeError("Finnhub transcript fetch timed out.")

    transcript_data = resp.json()

    if isinstance(transcript_data, dict) and transcript_data.get("error"):
        raise RuntimeError(f"Finnhub API error: {transcript_data['error']}")

    raw_text = _finnhub_segments_to_text(transcript_data)

    if not raw_text.strip():
        raise RuntimeError(f"Finnhub returned an empty transcript for {ticker} Q{quarter} {year}.")

    transcript = _clean_transcript(raw_text)
    print(f"OK Transcript fetched: {len(transcript.split())} words, {len(transcript)} characters")
    return transcript


def _find_finnhub_transcript_id(transcripts: list, ticker: str, year: int, quarter: int) -> str:
    """
    Find the Finnhub transcript ID that matches the requested year + quarter.

    Finnhub transcript list items look like:
      {"id": "some-uuid", "title": "Apple Inc Q1 2024 Earnings Call", "time": 1706745600}

    Matching strategy:
      1. Primary: title contains "Q{quarter}" (case-insensitive) AND str(year)
      2. Fallback: estimate quarter from Unix timestamp (month → quarter mapping)
    """
    import datetime

    # Primary match: parse title
    q_label = f"Q{quarter}"
    for t in transcripts:
        title = t.get("title", "")
        if q_label.lower() in title.lower() and str(year) in title:
            return t["id"]

    # Fallback: match by timestamp
    for t in transcripts:
        ts = t.get("time")
        if not ts:
            continue
        dt = datetime.datetime.utcfromtimestamp(ts)
        estimated_quarter = (dt.month - 1) // 3 + 1
        if dt.year == year and estimated_quarter == quarter:
            return t["id"]

    # If still not found, list what is available to help the user
    available = [
        f"  {t.get('title', 'untitled')} (id: {t.get('id', '?')})"
        for t in transcripts[:10]
    ]
    raise RuntimeError(
        f"No transcript found for {ticker} Q{quarter} {year} on Finnhub.\n"
        f"Available transcripts:\n" + "\n".join(available)
    )


def _finnhub_segments_to_text(data: dict) -> str:
    """
    Convert Finnhub's speaker-segmented transcript format to plain text.

    Finnhub returns:
      {
        "transcript": [
          {"name": "Operator", "speech": ["Good day, everyone..."]},
          {"name": "Tim Cook", "speech": ["Thank you...", "We had a great quarter..."]},
          ...
        ],
        "participant": [{"name": "Tim Cook", "role": "executive"}, ...]
      }

    Output format mirrors what you'd see in a published transcript:
      Operator:
      Good day, everyone...

      Tim Cook (CEO):
      Thank you... We had a great quarter...
    """
    # Build a role lookup from participants
    role_map = {}
    for p in data.get("participant", []):
        name = p.get("name", "")
        role = p.get("role", "")
        if name and role:
            role_map[name] = role

    lines = []
    for segment in data.get("transcript", []):
        name = segment.get("name", "Unknown")
        speeches = segment.get("speech", [])
        if not speeches:
            continue

        role = role_map.get(name, "")
        header = f"{name} ({role}):" if role else f"{name}:"
        body = " ".join(s.strip() for s in speeches if s.strip())

        lines.append(header)
        lines.append(body)
        lines.append("")  # blank line between speakers

    return "\n".join(lines)


# =============================================================================
# SOURCE 2: FINANCIAL MODELING PREP API
# Requires FMP Ultimate plan ($149/mo) for transcript access.
# Requires FMP_API_KEY in .env
# =============================================================================

def _fetch_from_fmp(ticker: str, year: int, quarter: int) -> str:
    """
    Fetch a transcript from the Financial Modeling Prep API.

    FMP endpoint: GET /stable/earning-call-transcript?symbol={ticker}&quarter={q}&year={y}
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
    url = f"{FMP_BASE_URL}/earning-call-transcript"
    params = {
        "symbol": ticker,
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

    print(f"OK Transcript fetched: {len(transcript.split())} words, {len(transcript)} characters")
    return transcript


def list_available_transcripts(ticker: str, limit: int = 10, source: str = "auto") -> list[dict]:
    """
    List available transcripts for a ticker.
    Useful for discovering what quarters are available before fetching.

    Returns a list of dicts with keys: ticker, quarter, year, date
    """
    ticker = ticker.upper()
    source = source.lower()

    use_finnhub = (
        source == "finnhub" or
        (source == "auto" and os.getenv("FINNHUB_API_KEY"))
    )

    if use_finnhub:
        api_key = os.getenv("FINNHUB_API_KEY")
        if not api_key:
            raise RuntimeError("FINNHUB_API_KEY not found in environment.")
        resp = requests.get(
            f"{FINNHUB_BASE_URL}/transcripts/list",
            params={"symbol": ticker, "token": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in (data.get("transcript", []))[:limit]:
            results.append({
                "ticker": ticker,
                "title": item.get("title", ""),
                "id": item.get("id", ""),
                "date": item.get("time", "unknown"),
            })
        return results
    else:
        api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            raise RuntimeError("FMP_API_KEY not found in environment.")
        url = f"{FMP_BASE_URL}/transcripts-dates-by-symbol"
        response = requests.get(url, params={"symbol": ticker, "apikey": api_key}, timeout=30)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and "Error Message" in data:
            raise RuntimeError(f"FMP API error: {data['Error Message']}")
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
    print(f"OK Transcript loaded: {len(transcript.split())} words, {len(transcript)} characters")
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
    parser.add_argument(
        "--source", default="auto", choices=["auto", "edgar", "finnhub", "fmp"],
        help="Transcript source: auto (default), edgar (free), finnhub, or fmp"
    )

    args = parser.parse_args()

    if args.list:
        print(f"\nAvailable transcripts for {args.list.upper()}:")
        available = list_available_transcripts(args.list, source=args.source)
        for t in available:
            if "title" in t:
                print(f"  {t['title']}  (id: {t['id']})")
            else:
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
                print(f"  WARN {issue}")
        if validation["errors"]:
            for error in validation["errors"]:
                print(f"  ERR {error}")
        if validation["valid"]:
            print(f"  OK Ready for pipeline")

        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(transcript)
            print(f"\nSaved to {args.save}")

    elif args.ticker and args.year and args.quarter:
        transcript = fetch_transcript(ticker=args.ticker, year=args.year, quarter=args.quarter, source=args.source)
        validation = validate_transcript(transcript)

        print(f"\nValidation results:")
        print(f"  Word count:        {validation['word_count']:,}")
        print(f"  Estimated tokens:  {validation['estimated_tokens']:,}")
        print(f"  Has Q&A section:   {validation['has_qa_section']}")

        if validation["issues"]:
            for issue in validation["issues"]:
                print(f"  WARN {issue}")
        if validation["errors"]:
            for error in validation["errors"]:
                print(f"  ERR {error}")
        if validation["valid"]:
            print(f"  OK Ready for pipeline")

        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(transcript)
            print(f"\nSaved to {args.save}")
        else:
            print(f"\nTip: use --save filename.txt to save the transcript to a file")

    else:
        parser.print_help()
