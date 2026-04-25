import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html import unescape
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from dotenv import load_dotenv
from openai import OpenAI

from core.company_profiles import get_company_profile

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DOC_SUMMARY_MODEL = os.getenv("DOC_SUMMARY_MODEL", "gpt-4o-mini")

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "compete-strategy/1.0 support@example.com"
)
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
ALLOW_OFFICIAL_PAGE_FETCH = os.getenv("ALLOW_OFFICIAL_PAGE_FETCH", "false").strip().lower() == "true"

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
FMP_BASE_URL = "https://financialmodelingprep.com/stable"
GITHUB_API_BASE = "https://api.github.com"

MAX_RAW_TEXT_CHARS = 18000
MAX_TOTAL_DOCS = 12
MAX_QUARTERLY_DOCS = 8
MAX_NEWS_DOCS = 15
MAX_CHANGELOG_DOCS = 10
MAX_GITHUB_DOCS = 10
MAX_SUMMARY_WORKERS = 6

SOURCE_PRIORITY = {
    "earnings_call_transcript": 100,
    "shareholder_letter": 98,
    "investor_day": 96,
    "quarterly_filing": 90,
    "earnings_release": 88,
    "job": 80,
    "pricing_page": 74,
    "product_doc": 72,
    "changelog": 70,
    "github_release": 68,
    "customer_story": 64,
    "partner_page": 62,
    "newsroom_post": 50,
}

LEGAL_SOURCE_POLICY = {
    "jobs": "API only",
    "sec": "Official SEC EDGAR endpoints only",
    "newsroom": "Explicitly allowlisted company-owned pages only",
    "changelog": "Explicitly allowlisted company-owned pages only",
    "github": "Explicitly configured official GitHub orgs only",
}

KEYWORD_BUCKETS = {
    "newsroom_post": ("news", "press", "announcement", "launch", "introducing", "partnership"),
    "changelog": ("release notes", "changelog", "what's new", "whats new", "release"),
}

DOC_SUMMARY_PROMPT = """You are extracting competitive intelligence signals from official company materials.

Document type: {source_type}
Company: {company}
Title: {title}
Published period/date: {period}

Document text:
{text}

Return a JSON object with this exact shape:
{{
  "summary_text": "A concise 4-8 sentence summary focused on strategy, product direction, partnerships, launches, customer segments, metrics, GTM themes, or management commentary explicitly stated in the document.",
  "structured_signals": {{
    "focus_areas": ["explicit priorities or strategic themes"],
    "products_or_initiatives": ["named products, launches, or programs"],
    "metrics": ["explicitly mentioned metrics, guidance, or KPIs"],
    "customer_segments": ["explicit customer, vertical, or geography mentions"],
    "management_priorities": ["what the company says it is investing in or focusing on"],
    "qa_topics": ["only for Q&A or transcript-style materials; otherwise empty list"]
  }}
}}

Rules:
- Ground every field in the source text only.
- Do not infer missing facts.
- If a field has no support, return an empty list.
- Return valid JSON only."""


def _http_headers():
    return {
        "User-Agent": SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }


def _github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": SEC_USER_AGENT,
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_allowed_domain(url: str, allowed_domains: list) -> bool:
    if not allowed_domains:
        return False
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        return False
    return domain in {d.lower() for d in allowed_domains}


def _extract_title(html: str, fallback: str = "") -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not match:
        return fallback
    return re.sub(r"\s+", " ", unescape(match.group(1))).strip()[:220]


def _extract_period_label(report_date: str, filing_date: str) -> Tuple[str, Optional[int]]:
    source = report_date or filing_date or ""
    if not source:
        return "", None
    try:
        dt = datetime.strptime(source[:10], "%Y-%m-%d")
    except ValueError:
        return source[:10], None
    quarter = ((dt.month - 1) // 3) + 1
    return f"Q{quarter} {dt.year}", dt.year


def _fetch_text(url: str, timeout: int = 20) -> str:
    response = requests.get(url, headers=_http_headers(), timeout=timeout)
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
        period=doc.get("fiscal_period") or doc.get("published_at") or "",
        text=raw_text,
    )

    try:
        response = client.chat.completions.create(
            model=DOC_SUMMARY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0
        )
        payload = json.loads(response.choices[0].message.content)
        doc["summary_text"] = payload.get("summary_text", "")
        doc["structured_signals"] = payload.get("structured_signals", {})
    except Exception as e:
        print(f"[company_documents] Summary extraction failed for '{doc.get('title', '')}': {e}")
        doc["summary_text"] = raw_text[:1200]
        doc["structured_signals"] = {}

    return doc


def _normalize_source_doc(company: str, source_type: str, source_group: str, title: str, raw_text: str,
                          source_url: str, published_at: str = "", ticker: str = "", cik: str = "",
                          fiscal_period: str = "", fiscal_year=None) -> dict:
    domain = urlparse(source_url).netloc.lower() if source_url else ""
    return {
        "company": company,
        "ticker": ticker,
        "cik": cik,
        "fiscal_period": fiscal_period,
        "fiscal_year": fiscal_year,
        "source_type": source_type,
        "source_group": source_group,
        "title": title[:220],
        "raw_text": raw_text[:MAX_RAW_TEXT_CHARS],
        "summary_text": "",
        "structured_signals": {},
        "source_url": source_url,
        "published_at": published_at or "",
        "source_domain": domain,
    }


def _source_priority(doc: dict) -> int:
    return SOURCE_PRIORITY.get(doc.get("source_type", ""), 10)


def _source_sort_key(doc: dict):
    return (
        _source_priority(doc),
        str(doc.get("published_at") or ""),
        str(doc.get("fiscal_year") or ""),
        str(doc.get("fiscal_period") or ""),
        str(doc.get("title") or "").lower(),
    )


def _fetch_sec_documents(company: str, public_company: dict, max_docs: int = 4) -> list:
    cik = public_company.get("cik", "")
    if not cik:
        return []

    try:
        response = requests.get(SEC_SUBMISSIONS_URL.format(cik=cik), headers=_http_headers(), timeout=20)
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        print(f"[company_documents] SEC submissions lookup failed for '{company}': {e}")
        return []

    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    items_list = recent.get("items", [])

    docs = []
    cik_no_zero = str(int(cik))

    for i, form in enumerate(forms):
        if len(docs) >= max_docs:
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
            raw_html = _fetch_text(source_url)
        except Exception as e:
            print(f"[company_documents] SEC document fetch failed for '{source_url}': {e}")
            continue

        docs.append(_normalize_source_doc(
            company=company,
            source_type="earnings_release" if form == "8-K" else "quarterly_filing",
            source_group="investor_relations",
            title=(descriptions[i] if i < len(descriptions) else "") or f"{form} filed on {filing_date}",
            raw_text=_html_to_text(raw_html),
            source_url=source_url,
            published_at=filing_date,
            ticker=public_company.get("ticker", ""),
            cik=cik,
            fiscal_period=period_label,
            fiscal_year=fiscal_year,
        ))

    return docs


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


def _fetch_transcript_documents(company: str, public_company: dict, max_docs: int = 4) -> list:
    ticker = public_company.get("ticker", "")
    if not ticker or not FMP_API_KEY:
        return []

    try:
        response = requests.get(
            f"{FMP_BASE_URL}/earning-call-transcript-dates",
            params={"symbol": ticker, "apikey": FMP_API_KEY},
            headers=_http_headers(),
            timeout=20
        )
        response.raise_for_status()
        candidates = _parse_transcript_payload(response.json())[:max_docs]
    except Exception as e:
        print(f"[company_documents] Transcript dates lookup failed for '{ticker}': {e}")
        return []

    docs = []
    for item in candidates:
        quarter = item.get("quarter") or item.get("quarterNumber")
        year = item.get("year")
        if not quarter or not year:
            continue

        try:
            response = requests.get(
                f"{FMP_BASE_URL}/earning-call-transcript",
                params={"symbol": ticker, "quarter": int(quarter), "year": int(year), "apikey": FMP_API_KEY},
                headers=_http_headers(),
                timeout=25
            )
            response.raise_for_status()
            payload = _parse_transcript_payload(response.json())
        except Exception as e:
            print(f"[company_documents] Transcript fetch failed for '{ticker} Q{quarter} {year}': {e}")
            continue

        if not payload:
            continue
        first = payload[0] if isinstance(payload[0], dict) else {}
        transcript_text = str(first.get("content") or first.get("transcript") or first.get("text") or "")
        if not transcript_text.strip():
            continue

        docs.append(_normalize_source_doc(
            company=company,
            source_type="earnings_call_transcript",
            source_group="investor_relations",
            title=item.get("title") or f"Earnings call transcript Q{quarter} {year}",
            raw_text=transcript_text,
            source_url=item.get("url") or "",
            published_at=f"{year}-Q{quarter}",
            ticker=ticker,
            cik=public_company.get("cik", ""),
            fiscal_period=f"Q{quarter} {year}",
            fiscal_year=int(year),
        ))

    return docs


def _extract_candidate_links(index_url: str, html: str, allowed_domains: list) -> list:
    hrefs = re.findall(r'''href=["']([^"'#]+)["']''', html, flags=re.I)
    links = []
    seen = set()

    for href in hrefs:
        absolute = urljoin(index_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if not _is_allowed_domain(absolute, allowed_domains):
            continue
        normalized = absolute.split("#", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)

    return links


def _score_link(url: str, source_type: str) -> int:
    path = urlparse(url).path.lower()
    if source_type == "newsroom_post":
        return sum(8 for keyword in ("news", "press", "blog", "post", "announcement", "launch", "introducing") if keyword in path)
    return sum(8 for keyword in ("release", "releases", "release-notes", "changelog", "whats-new", "what-s-new") if keyword in path)


def _fetch_page_document(company: str, url: str, source_type: str, source_group: str, allowed_domains: list) -> Optional[dict]:
    if not _is_allowed_domain(url, allowed_domains):
        return None
    try:
        html = _fetch_text(url)
    except Exception as e:
        print(f"[company_documents] Page fetch failed for '{url}': {e}")
        return None

    text = _html_to_text(html)
    if len(text) < 400:
        return None

    title = _extract_title(html, fallback=urlparse(url).path.strip("/").split("/")[-1] or company)
    return _normalize_source_doc(
        company=company,
        source_type=source_type,
        source_group=source_group,
        title=title,
        raw_text=text,
        source_url=url,
    )


def _crawl_index_pages(company: str, pages: List[str], source_type: str, source_group: str, limit: int, allowed_domains: list) -> list:
    docs = []
    seen_urls = set()

    for page_url in pages:
        if len(docs) >= limit:
            break
        if not _is_allowed_domain(page_url, allowed_domains):
            continue
        try:
            html = _fetch_text(page_url)
        except Exception as e:
            print(f"[company_documents] Index fetch failed for '{page_url}': {e}")
            continue

        page_doc = _fetch_page_document(company, page_url, source_type, source_group, allowed_domains)
        if page_doc and source_type == "changelog":
            docs.append(page_doc)

        candidates = sorted(
            _extract_candidate_links(page_url, html, allowed_domains),
            key=lambda url: _score_link(url, source_type),
            reverse=True
        )

        for candidate in candidates:
            if len(docs) >= limit:
                break
            if candidate in seen_urls:
                continue
            if _score_link(candidate, source_type) <= 0:
                continue
            seen_urls.add(candidate)
            doc = _fetch_page_document(company, candidate, source_type, source_group, allowed_domains)
            if doc:
                docs.append(doc)

    unique = []
    seen_titles = set()
    for doc in docs:
        key = (doc.get("title", "").lower(), doc.get("source_url", ""))
        if key in seen_titles:
            continue
        seen_titles.add(key)
        unique.append(doc)
    return unique[:limit]


def _fetch_github_documents(company: str, profile: dict, limit: int = MAX_GITHUB_DOCS) -> list:
    if not profile.get("github_enabled"):
        return []
    if "github.com" not in {d.lower() for d in profile.get("allowed_domains", [])}:
        return []

    docs = []
    for org in profile.get("github_orgs", []):
        try:
            org_resp = requests.get(f"{GITHUB_API_BASE}/orgs/{org}", headers=_github_headers(), timeout=20)
            org_resp.raise_for_status()
            org_data = org_resp.json()
        except Exception as e:
            print(f"[company_documents] GitHub org fetch failed for '{org}': {e}")
            continue

        if not org_data.get("html_url"):
            continue

        try:
            repos_resp = requests.get(
                f"{GITHUB_API_BASE}/orgs/{org}/repos",
                headers=_github_headers(),
                params={"sort": "updated", "per_page": limit},
                timeout=20
            )
            repos_resp.raise_for_status()
            repos = repos_resp.json()
        except Exception as e:
            print(f"[company_documents] GitHub repo list failed for '{org}': {e}")
            continue

        for repo in repos[:limit]:
            try:
                rel_resp = requests.get(
                    f"{GITHUB_API_BASE}/repos/{org}/{repo['name']}/releases/latest",
                    headers=_github_headers(),
                    timeout=20
                )
                if rel_resp.status_code != 200:
                    continue
                rel = rel_resp.json()
            except Exception:
                continue

            body = rel.get("body") or repo.get("description") or ""
            if not body.strip():
                continue

            docs.append(_normalize_source_doc(
                company=company,
                source_type="github_release",
                source_group="github",
                title=f"{repo.get('name', '')} {rel.get('tag_name', '')}".strip(),
                raw_text=body,
                source_url=rel.get("html_url") or repo.get("html_url") or "",
                published_at=rel.get("published_at", ""),
            ))

    return docs[:limit]


def fetch_company_documents(company: str, public_company: Optional[dict] = None) -> list:
    public_company = public_company or {}
    profile = get_company_profile(company, public_company)

    raw_docs = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        if public_company.get("is_public"):
            futures.append(executor.submit(_fetch_sec_documents, company, public_company, 4))
            futures.append(executor.submit(_fetch_transcript_documents, company, public_company, 4))

        if ALLOW_OFFICIAL_PAGE_FETCH:
            futures.append(executor.submit(
                _crawl_index_pages,
                company,
                profile.get("news_pages", []),
                "newsroom_post",
                "official_news",
                MAX_NEWS_DOCS,
                profile.get("allowed_domains", []),
            ))
            futures.append(executor.submit(
                _crawl_index_pages,
                company,
                profile.get("changelog_pages", []),
                "changelog",
                "product_updates",
                MAX_CHANGELOG_DOCS,
                profile.get("allowed_domains", []),
            ))

        futures.append(executor.submit(_fetch_github_documents, company, profile, MAX_GITHUB_DOCS))

        for future in as_completed(futures):
            try:
                raw_docs.extend(future.result() or [])
            except Exception as e:
                print(f"[company_documents] Source fetch failed: {e}")

    normalized = []
    seen = set()
    for doc in raw_docs:
        key = (doc.get("source_type", ""), doc.get("title", "").lower(), doc.get("source_url", ""))
        if key in seen:
            continue
        seen.add(key)
        normalized.append(doc)

    normalized.sort(key=_source_sort_key, reverse=True)
    normalized = normalized[:MAX_TOTAL_DOCS]
    enriched = []
    with ThreadPoolExecutor(max_workers=min(MAX_SUMMARY_WORKERS, max(1, len(normalized)))) as executor:
        futures = [executor.submit(_summarize_document, doc) for doc in normalized]
        for future in as_completed(futures):
            try:
                enriched.append(future.result())
            except Exception as e:
                print(f"[company_documents] Document summary failed: {e}")
    enriched.sort(key=_source_sort_key, reverse=True)
    print(f"[company_documents] Collected {len(enriched)} documents for '{company}'")
    return enriched
