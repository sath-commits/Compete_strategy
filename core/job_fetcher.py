import requests
import os
import re
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY')
RAPIDAPI_HOST = os.getenv('RAPIDAPI_HOST', 'jsearch.p.rapidapi.com')
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY')

NUM_PAGES = 10


def fetch_jobs(company, num_pages=NUM_PAGES):
    results = _fetch_from_jsearch(company, num_pages)
    if not results:
        print(f"[job_fetcher] JSearch empty for '{company}', trying Adzuna")
        results = _fetch_from_adzuna(company)
    return results


def _fetch_from_jsearch(company: str, num_pages: int) -> list:
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
        print(f"[job_fetcher] JSearch error for '{company}': {e}")
        return []

    validated = _filter_by_company(raw_jobs, company)
    print(f"[job_fetcher] JSearch company='{company}' → {len(raw_jobs)} raw, {len(validated)} after filter")
    return _normalize(validated)


def _fetch_from_adzuna(company: str) -> list:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("[job_fetcher] Adzuna credentials not configured")
        return []

    url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": company,
        "results_per_page": 50,
        "content-type": "application/json",
    }
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        raw = response.json().get("results", [])
    except Exception as e:
        print(f"[job_fetcher] Adzuna error for '{company}': {e}")
        return []

    # Map Adzuna fields to match the format _filter_by_company and _normalize expect
    mapped = [{
        'employer_name': job.get('company', {}).get('display_name', ''),
        'job_title': job.get('title', ''),
        'job_description': job.get('description', ''),
        'job_apply_link': job.get('redirect_url', ''),
        'job_location': job.get('location', {}).get('display_name', ''),
    } for job in raw]

    validated = _filter_by_company(mapped, company)
    print(f"[job_fetcher] Adzuna company='{company}' → {len(raw)} raw, {len(validated)} after filter")
    return _normalize(validated)


def _normalize_company_name(name: str) -> str:
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
