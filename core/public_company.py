import os
import re
from functools import lru_cache

import requests


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "compete-strategy/1.0 support@example.com"
)


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
    words = [word for word in normalized.split() if word not in suffixes]
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


def resolve_public_company(company: str) -> dict:
    query = (company or "").strip()
    if not query:
        return {
            "is_public": False,
            "company": "",
            "ticker": "",
            "cik": "",
            "match_type": "empty",
        }

    query_normalized = _normalize_company_name(query)
    query_upper = query.upper()

    try:
        companies = _load_sec_company_tickers()
    except Exception as e:
        print(f"[public_company] SEC lookup failed: {e}")
        return {
            "is_public": False,
            "company": query,
            "ticker": "",
            "cik": "",
            "match_type": "lookup_failed",
        }

    best = None
    best_score = 0
    query_words = set(query_normalized.split())

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

    if not best or best_score < 74:
        return {
            "is_public": False,
            "company": query,
            "ticker": "",
            "cik": "",
            "match_type": "not_found",
        }

    return {
        "is_public": True,
        "company": best["company"],
        "ticker": best["ticker"],
        "cik": best["cik"],
        "match_type": "sec_tickers",
    }
