import json
import os
import re
from datetime import datetime

import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "compete-strategy/1.0 support@example.com"
)
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
FMP_BASE_URL = "https://financialmodelingprep.com/stable"

MAX_RAW_TEXT_CHARS = 18000
MAX_DOCS_PER_COMPANY = 6

DOC_SUMMARY_PROMPT = """You are extracting competitive intelligence signals from a public company's quarterly investor materials.

Document type: {source_type}
Company: {company}
Title: {title}
Fiscal period: {period}

Document text:
{text}

Return a JSON object with this exact shape:
{{
  "summary_text": "A concise 5-8 sentence summary focused on strategic priorities, metrics, product areas, GTM themes, or management commentary explicitly stated in the document.",
  "structured_signals": {{
    "focus_areas": ["explicit priorities or strategic themes"],
    "products_or_initiatives": ["named products, launches, or programs"],
    "metrics": ["explicitly mentioned metrics, guidance, or financial KPIs"],
    "customer_segments": ["explicit customer, vertical, or geography mentions"],
    "management_priorities": ["what management says it is investing in or focusing on"],
    "qa_topics": ["for transcript Q&A topics only; otherwise empty list"]
  }}
}}

Rules:
- Ground every field in the source text only.
- Do not infer missing facts.
- If a field has no support, return an empty list.
- Return valid JSON only."""


def _sec_headers():
    return {
        "User-Agent": SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_period_label(report_date: str, filing_date: str) -> tuple[str, int | None]:
    source = report_date or filing_date or ""
    if not source:
        return "", None
    try:
        dt = datetime.strptime(source[:10], "%Y-%m-%d")
    except ValueError:
        return source[:10], None
    quarter = ((dt.month - 1) // 3) + 1
    return f"Q{quarter} {dt.year}", dt.year


def _fetch_url(url: str, headers: dict, timeout: int = 20) -> str:
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def _summarize_document(doc: dict) -> dict:
    raw_text = (doc.get("raw_text") or "")[:MAX_RAW_TEXT_CHARS]
    if not raw_text.strip():
        doc["summary_text"] = ""
        doc["structured_signals"] = {}
        return doc

    prompt = DOC_SUMMARY_PROMPT.format(
        source_type=doc.get("source_type", ""),
        company=doc.get("company", ""),
        title=doc.get("title", ""),
        period=doc.get("fiscal_period", ""),
        text=raw_text,
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0
        )
        payload = json.loads(response.choices[0].message.content)
        doc["summary_text"] = payload.get("summary_text", "")
        doc["structured_signals"] = payload.get("structured_signals", {})
    except Exception as e:
        print(f"[quarterly_data] Summary extraction failed for '{doc.get('title', '')}': {e}")
        doc["summary_text"] = raw_text[:1200]
        doc["structured_signals"] = {}

    return doc


def _fetch_sec_documents(public_company: dict, max_docs: int = 4) -> list:
    cik = public_company.get("cik", "")
    if not cik:
        return []

    url = SEC_SUBMISSIONS_URL.format(cik=cik)
    try:
        submissions = requests.get(url, headers=_sec_headers(), timeout=20)
        submissions.raise_for_status()
        payload = submissions.json()
    except Exception as e:
        print(f"[quarterly_data] SEC submissions lookup failed for '{public_company.get('company', '')}': {e}")
        return []

    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])
    primary_descriptions = recent.get("primaryDocDescription", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    items_list = recent.get("items", [])

    documents = []
    cik_no_zero = str(int(cik))

    for i, form in enumerate(forms):
        if len(documents) >= max_docs:
            break

        items = items_list[i] if i < len(items_list) else ""
        if form not in {"10-Q", "10-K", "8-K"}:
            continue
        if form == "8-K" and "2.02" not in (items or ""):
            continue

        accession = accession_numbers[i]
        primary_document = primary_documents[i]
        filing_date = filing_dates[i] if i < len(filing_dates) else ""
        report_date = report_dates[i] if i < len(report_dates) else ""
        period_label, fiscal_year = _extract_period_label(report_date, filing_date)
        accession_slug = accession.replace("-", "")
        source_url = f"{SEC_ARCHIVES_BASE}/{cik_no_zero}/{accession_slug}/{primary_document}"

        try:
            raw_html = _fetch_url(source_url, _sec_headers())
        except Exception as e:
            print(f"[quarterly_data] SEC document fetch failed for '{source_url}': {e}")
            continue

        title = primary_descriptions[i] if i < len(primary_descriptions) else ""
        title = title or f"{form} filed on {filing_date}"

        documents.append({
            "company": public_company.get("company", ""),
            "ticker": public_company.get("ticker", ""),
            "cik": cik,
            "fiscal_period": period_label,
            "fiscal_year": fiscal_year,
            "source_type": "earnings_release" if form == "8-K" else "quarterly_filing",
            "title": title,
            "raw_text": _html_to_text(raw_html)[:MAX_RAW_TEXT_CHARS],
            "summary_text": "",
            "structured_signals": {},
            "source_url": source_url,
        })

    return documents


def _parse_transcript_payload(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("transcripts", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    return []


def _fetch_transcript_candidates(ticker: str) -> list:
    if not FMP_API_KEY:
        return []

    url = f"{FMP_BASE_URL}/earning-call-transcript-dates"
    try:
        response = requests.get(
            url,
            params={"symbol": ticker, "apikey": FMP_API_KEY},
            timeout=20
        )
        response.raise_for_status()
        return _parse_transcript_payload(response.json())
    except Exception as e:
        print(f"[quarterly_data] Transcript dates lookup failed for '{ticker}': {e}")
        return []


def _fetch_transcript_text(ticker: str, quarter: int, year: int) -> str:
    url = f"{FMP_BASE_URL}/earning-call-transcript"
    try:
        response = requests.get(
            url,
            params={"symbol": ticker, "quarter": quarter, "year": year, "apikey": FMP_API_KEY},
            timeout=25
        )
        response.raise_for_status()
        payload = _parse_transcript_payload(response.json())
    except Exception as e:
        print(f"[quarterly_data] Transcript fetch failed for '{ticker} Q{quarter} {year}': {e}")
        return ""

    if not payload:
        return ""

    first = payload[0]
    if isinstance(first, dict):
        for key in ("content", "transcript", "text"):
            if first.get(key):
                return str(first[key])
    return ""


def _fetch_transcript_documents(public_company: dict, max_docs: int = 2) -> list:
    ticker = public_company.get("ticker", "")
    if not ticker:
        return []

    candidates = _fetch_transcript_candidates(ticker)[:max_docs]
    documents = []
    for item in candidates:
        quarter = item.get("quarter") or item.get("quarterNumber")
        year = item.get("year")
        if not quarter or not year:
            continue

        transcript_text = _fetch_transcript_text(ticker, int(quarter), int(year))
        if not transcript_text.strip():
            continue

        title = item.get("title") or f"Earnings call transcript Q{quarter} {year}"
        source_url = item.get("url") or ""
        documents.append({
            "company": public_company.get("company", ""),
            "ticker": ticker,
            "cik": public_company.get("cik", ""),
            "fiscal_period": f"Q{quarter} {year}",
            "fiscal_year": int(year),
            "source_type": "earnings_call_transcript",
            "title": title,
            "raw_text": transcript_text[:MAX_RAW_TEXT_CHARS],
            "summary_text": "",
            "structured_signals": {},
            "source_url": source_url,
        })

    return documents


def fetch_quarterly_documents(public_company: dict) -> list:
    if not public_company.get("is_public"):
        return []

    raw_docs = _fetch_sec_documents(public_company, max_docs=4)
    raw_docs.extend(_fetch_transcript_documents(public_company, max_docs=2))
    raw_docs = raw_docs[:MAX_DOCS_PER_COMPANY]

    enriched = []
    for doc in raw_docs:
        enriched.append(_summarize_document(doc))

    print(
        f"[quarterly_data] Collected {len(enriched)} quarterly documents for "
        f"'{public_company.get('company', '')}'"
    )
    return enriched
