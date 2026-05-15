import requests
import os
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY')
RAPIDAPI_HOST = os.getenv('RAPIDAPI_HOST', 'jsearch.p.rapidapi.com')

NUM_PAGES = 10


def fetch_jobs(company, num_pages=NUM_PAGES):
    """
    Fetch job postings for a company from JSearch (RapidAPI).
    num_pages=10 returns ~100 jobs in a single API call.
    """
    url = f"https://{RAPIDAPI_HOST}/search"
    headers = {
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": RAPIDAPI_KEY,
    }
    params = {
        "query": f"{company} jobs",
        "page": "1",
        "num_pages": str(num_pages),
        "date_posted": "all",
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        raw_jobs = response.json().get("data", [])
    except Exception as e:
        print(f"[job_fetcher] Error fetching jobs for '{company}': {e}")
        return []

    validated = _filter_by_company(raw_jobs, company)
    print(f"[job_fetcher] company='{company}' → {len(raw_jobs)} raw, {len(validated)} after company filter")
    return _normalize(validated)


def _normalize_company_name(name: str) -> str:
    import re
    name = name.lower().strip()
    name = re.sub(r'[^a-z0-9 ]', '', name)
    for suffix in (' inc', ' ltd', ' llc', ' corp', ' corporation', ' group',
                   ' co', ' company', ' technologies', ' technology'):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()


def _filter_by_company(raw_jobs: list, searched_company: str) -> list:
    target = _normalize_company_name(searched_company)
    target_tokens = set(target.split())
    stop_tokens = {'the', 'and', 'of', 'for', 'a', 'an', 'in', 'at', 'on'}
    target_tokens -= stop_tokens

    filtered = []
    for job in raw_jobs:
        employer = job.get('employer_name', '') or ''
        if not employer.strip():
            filtered.append(job)
            continue
        norm_employer = _normalize_company_name(employer)
        employer_tokens = set(norm_employer.split()) - stop_tokens
        if (target in norm_employer or norm_employer in target
                or bool(target_tokens & employer_tokens)):
            filtered.append(job)
    return filtered


def _normalize(raw_jobs):
    """Map JSearch fields to the schema expected by job_extractor.py."""
    normalized = []
    for job in raw_jobs:
        title = (job.get('job_title') or '').strip()
        description = (job.get('job_description') or '').strip()
        apply_link = job.get('job_apply_link', '')
        company_name = job.get('employer_name', '')
        location = job.get('job_location', '')

        if not description:
            continue

        normalized.append({
            'job_title': title,
            'job_description': description,
            'job_apply_link': apply_link,
            'job_company': company_name,
            'job_location': location,
        })

    return normalized
