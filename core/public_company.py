import os
import re
from functools import lru_cache

import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "compete-strategy/1.0 support@example.com"
)

# Only true rebrands where the brand name is completely absent from the SEC filing name.
# "Google" will never match "Alphabet Inc." — no fuzzy logic can fix that.
# Everything else falls through to name matching, then GPT fallback.
REBRAND_ALIASES = {
    "google":          "GOOGL",
    "alphabet":        "GOOGL",
    "google deepmind": "GOOGL",
    "deepmind":        "GOOGL",
    "facebook":        "META",
    "instagram":       "META",
    "whatsapp":        "META",
    # Known private companies — skip SEC lookup entirely
    "twitter":         None,
    "x (twitter)":    None,
    "x":               None,
    "openai":          None,
    "anthropic":       None,
    "mistral ai":      None,
    "mistral":         None,
    "cohere":          None,
    "databricks":      None,
    "stripe":          None,
    "klarna":          None,
    "chime":           None,
    "plaid":           None,
    "brex":            None,
    "rippling":        None,
    "notion":          None,
    "figma":           None,
    "canva":           None,
    "vercel":          None,
    "supabase":        None,
}


def _sec_headers():
    return {
        "User-Agent": SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }


def _normalize_company_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    suffixes = {
        "inc", "incorporated", "corp", "corporation", "co", "company", "group",
        "holdings", "holding", "ltd", "limited", "plc", "sa", "nv", "ag"
    }
    words = [w for w in normalized.split() if w not in suffixes]
    return " ".join(words).strip()


@lru_cache(maxsize=1)
def _load_sec_company_tickers():
    response = requests.get(SEC_TICKERS_URL, headers=_sec_headers(), timeout=20)
    response.raise_for_status()
    payload = response.json()
    companies = []
    for entry in payload.values():
        companies.append({
            "company": entry.get("title", ""),
            "company_normalized": _normalize_company_name(entry.get("title", "")),
            "ticker": (entry.get("ticker") or "").upper(),
            "cik": str(entry.get("cik_str") or "").zfill(10),
        })
    return companies


def _lookup_by_ticker(ticker: str, companies: list) -> dict | None:
    for entry in companies:
        if entry["ticker"] == ticker.upper():
            return entry
    return None


def _name_match(query: str, companies: list) -> dict | None:
    """Fuzzy name match against SEC company list. Returns best entry or None."""
    query_normalized = _normalize_company_name(query)
    query_upper = query.upper()
    query_words = set(query_normalized.split())

    best = None
    best_score = 0

    for entry in companies:
        score = 0
        candidate_name = entry["company_normalized"]
        candidate_words = set(candidate_name.split())

        if query_upper == entry["ticker"]:
            score = 100
        elif query_normalized and query_normalized == candidate_name:
            score = 96
        elif query_normalized and candidate_name.startswith(query_normalized):
            score = 90
        elif query_normalized and query_normalized in candidate_name:
            score = 82
        elif query_words and query_words.issubset(candidate_words):
            score = 74

        if score > best_score:
            best = entry
            best_score = score

    return best if best_score >= 74 else None


def _gpt_ticker_lookup(company: str) -> str | None:
    """
    Ask GPT for the primary stock ticker of a company.
    Returns ticker string, "PRIVATE" if not listed, or None on error.
    Only called when name matching fails — roughly once per unknown company.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a financial data assistant. Given a company name, "
                        "return ONLY its primary US stock exchange ticker symbol (e.g. MSFT, AAPL). "
                        "If the company is privately held and not listed on a US exchange, return PRIVATE. "
                        "If you are unsure, return UNKNOWN. "
                        "Return nothing else — just the ticker, PRIVATE, or UNKNOWN."
                    ),
                },
                {"role": "user", "content": company},
            ],
            temperature=0,
            max_tokens=10,
        )
        result = response.choices[0].message.content.strip().upper()
        print(f"[public_company] GPT ticker for '{company}': {result}")
        return result if result else None
    except Exception as e:
        print(f"[public_company] GPT ticker lookup failed: {e}")
        return None


def resolve_public_company(company: str) -> dict:
    query = (company or "").strip()
    if not query:
        return {"is_public": False, "company": "", "ticker": "", "cik": "", "match_type": "empty"}

    try:
        companies = _load_sec_company_tickers()
    except Exception as e:
        print(f"[public_company] SEC tickers load failed: {e}")
        return {"is_public": False, "company": query, "ticker": "", "cik": "", "match_type": "lookup_failed"}

    # 1. Rebrand aliases — brand name absent from SEC filing name (e.g. Google → Alphabet)
    query_lower = query.lower().strip()
    if query_lower in REBRAND_ALIASES:
        alias_ticker = REBRAND_ALIASES[query_lower]
        if alias_ticker is None:
            return {"is_public": False, "company": query, "ticker": "", "cik": "", "match_type": "known_private"}
        entry = _lookup_by_ticker(alias_ticker, companies)
        if entry:
            print(f"[public_company] Rebrand alias: '{query}' → {alias_ticker}")
            return {"is_public": True, "company": entry["company"], "ticker": entry["ticker"], "cik": entry["cik"], "match_type": "alias"}

    # 2. Direct ticker match or fuzzy name match against SEC list
    entry = _name_match(query, companies)
    if entry:
        return {"is_public": True, "company": entry["company"], "ticker": entry["ticker"], "cik": entry["cik"], "match_type": "sec_tickers"}

    # 3. GPT fallback — handles any company not caught above
    ticker = _gpt_ticker_lookup(query)
    if ticker and ticker not in ("PRIVATE", "UNKNOWN", ""):
        entry = _lookup_by_ticker(ticker, companies)
        if entry:
            return {"is_public": True, "company": entry["company"], "ticker": entry["ticker"], "cik": entry["cik"], "match_type": "gpt_ticker"}

    if ticker == "PRIVATE":
        return {"is_public": False, "company": query, "ticker": "", "cik": "", "match_type": "gpt_private"}

    return {"is_public": False, "company": query, "ticker": "", "cik": "", "match_type": "not_found"}
