import re
from urllib.parse import urlparse
from typing import Optional


PROFILE_OVERRIDES = {
    "openai": {
        "canonical": "OpenAI",
        "website": "https://openai.com",
        "allowed_domains": [
            "openai.com",
            "help.openai.com",
            "github.com",
            "api.github.com",
        ],
        "news_pages": [
            "https://openai.com/news/product-releases/",
            "https://openai.com/news/company-announcements/",
        ],
        "changelog_pages": [
            "https://help.openai.com/en/articles/6825453-chatgpt-release-notes",
            "https://help.openai.com/en/articles/10128477-chatgpt-enterprise-edu-release-notes",
        ],
        "github_orgs": ["openai"],
        "github_enabled": True,
    },
    "anthropic": {
        "canonical": "Anthropic",
        "website": "https://www.anthropic.com",
        "allowed_domains": [
            "www.anthropic.com",
            "support.anthropic.com",
            "github.com",
            "api.github.com",
        ],
        "news_pages": [
            "https://www.anthropic.com/news",
        ],
        "changelog_pages": [
            "https://support.anthropic.com/en/articles/12138966-release-notes",
        ],
        "github_orgs": ["anthropics"],
        "github_enabled": True,
    },
    "google": {
        "canonical": "Alphabet",
        "website": "https://blog.google",
        "allowed_domains": [
            "blog.google",
            "github.com",
            "api.github.com",
        ],
        "news_pages": [
            "https://blog.google/",
        ],
        "changelog_pages": [],
        "github_orgs": ["google"],
        "github_enabled": True,
    },
    "alphabet": {
        "canonical": "Alphabet",
        "website": "https://blog.google",
        "allowed_domains": [
            "blog.google",
            "github.com",
            "api.github.com",
        ],
        "news_pages": [
            "https://blog.google/",
        ],
        "changelog_pages": [],
        "github_orgs": ["google"],
        "github_enabled": True,
    },
    "meta": {
        "canonical": "Meta",
        "website": "https://about.fb.com",
        "allowed_domains": [
            "about.fb.com",
        ],
        "news_pages": [
            "https://about.fb.com/news/",
        ],
        "changelog_pages": [],
        "github_orgs": ["facebook"],
        "github_enabled": False,
    },
    "nvidia": {
        "canonical": "NVIDIA",
        "website": "https://nvidianews.nvidia.com",
        "allowed_domains": [
            "nvidianews.nvidia.com",
            "github.com",
            "api.github.com",
        ],
        "news_pages": [
            "https://nvidianews.nvidia.com/news",
        ],
        "changelog_pages": [],
        "github_orgs": ["NVIDIA"],
        "github_enabled": True,
    },
    "microsoft": {
        "canonical": "Microsoft",
        "website": "https://news.microsoft.com",
        "allowed_domains": [
            "news.microsoft.com",
            "blogs.microsoft.com",
            "github.com",
            "api.github.com",
        ],
        "news_pages": [
            "https://news.microsoft.com/",
            "https://blogs.microsoft.com/",
        ],
        "changelog_pages": [],
        "github_orgs": ["microsoft"],
        "github_enabled": True,
    },
}


def _normalize_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def get_company_profile(company: str, public_company: Optional[dict] = None) -> dict:
    normalized = _normalize_name(company)
    matched_key = None

    for key in PROFILE_OVERRIDES:
        if key == normalized or key in normalized or normalized in key:
            matched_key = key
            break

    profile = dict(PROFILE_OVERRIDES.get(matched_key, {}))
    profile.setdefault("canonical", public_company.get("company") if public_company else company)
    profile.setdefault("news_pages", [])
    profile.setdefault("changelog_pages", [])
    profile.setdefault("github_orgs", [])
    profile.setdefault("github_enabled", False)
    profile.setdefault("website", "")
    profile.setdefault("allowed_domains", [])

    if public_company and public_company.get("is_public"):
        profile["ticker"] = public_company.get("ticker", "")
        profile["cik"] = public_company.get("cik", "")

    if profile.get("website") and not profile.get("source_domain"):
        profile["source_domain"] = _domain_from_url(profile["website"])

    return profile
