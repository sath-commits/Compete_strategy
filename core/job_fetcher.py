import requests
import os
from dotenv import load_dotenv

load_dotenv()

ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID')
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY')

# Adzuna: 50 results/page × 3 pages = up to 150 jobs for 3 quota units.
# Each page request = 1 API call regardless of results_per_page.
PAGES_TO_FETCH = 3
RESULTS_PER_PAGE = 50


def fetch_jobs(company, num_pages=PAGES_TO_FETCH):
    """
    Fetch job postings for a company from Adzuna using employer-name filter only.

    We intentionally do NOT fall back to keyword search (what_and/what_phrase)
    because keyword matching against a company name returns jobs from unrelated
    employers whose descriptions happen to contain the same words.
    """
    all_jobs = _fetch_pages(company, {"company": company}, num_pages)
    if all_jobs:
        validated = _filter_by_company(all_jobs, company)
        print(f"[job_fetcher] company='{company}' → {len(all_jobs)} raw, {len(validated)} after company filter")
        return _normalize(validated)

    print(f"[job_fetcher] No jobs found for '{company}'")
    return []


def _normalize_company_name(name: str) -> str:
    """Lowercase, strip punctuation and common suffixes for fuzzy company matching."""
    import re
    name = name.lower().strip()
    name = re.sub(r'[^a-z0-9 ]', '', name)
    for suffix in (' inc', ' ltd', ' llc', ' corp', ' corporation', ' group',
                   ' co', ' company', ' technologies', ' technology'):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return name.strip()


def _filter_by_company(raw_jobs: list, searched_company: str) -> list:
    """
    Drop jobs whose employer name clearly doesn't match what we searched for.
    Adzuna's company= filter is fuzzy and occasionally returns noise.
    We accept a job if:
      - the Adzuna company field is empty (some listings omit it), OR
      - either name is a substring of the other after normalization, OR
      - the two share at least one significant token (ignoring stop words).
    """
    import re
    target = _normalize_company_name(searched_company)
    target_tokens = set(target.split())
    stop_tokens = {'the', 'and', 'of', 'for', 'a', 'an', 'in', 'at', 'on'}
    target_tokens -= stop_tokens

    filtered = []
    for job in raw_jobs:
        employer = (job.get('company') or {}).get('display_name', '') or ''
        if not employer.strip():
            filtered.append(job)
            continue
        norm_employer = _normalize_company_name(employer)
        employer_tokens = set(norm_employer.split()) - stop_tokens
        # Accept if substring match or at least one significant token overlaps
        if (target in norm_employer or norm_employer in target
                or bool(target_tokens & employer_tokens)):
            filtered.append(job)
    return filtered


def _fetch_pages(company, extra_params, num_pages):
    """Fetch up to num_pages pages from Adzuna and return raw results."""
    base_url = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"
    all_jobs = []

    for page in range(1, num_pages + 1):
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_APP_KEY,
            "results_per_page": RESULTS_PER_PAGE,
            **extra_params
        }
        try:
            response = requests.get(base_url.format(page=page), params=params,
                                    headers={"Content-Type": "application/json"}, timeout=60)
            response.raise_for_status()
            results = response.json().get('results', [])
            all_jobs.extend(results)
            if len(results) < RESULTS_PER_PAGE:
                break
        except Exception as e:
            print(f"[job_fetcher] Error on page {page} for '{company}': {e}")
            break

    return all_jobs


def _normalize(raw_jobs):
    """
    Map Adzuna response fields to the schema expected by job_extractor.py:
      job_title, job_description, job_apply_link
    """
    normalized = []
    for job in raw_jobs:
        title = job.get('title', '').strip()
        description = job.get('description', '').strip()
        job_url = job.get('redirect_url', '')
        company_name = (job.get('company') or {}).get('display_name', '')
        location = (job.get('location') or {}).get('display_name', '')

        if not description:
            continue

        normalized.append({
            'job_title': title,
            'job_description': description,
            'job_apply_link': job_url,
            'job_company': company_name,
            'job_location': location,
        })

    return normalized
