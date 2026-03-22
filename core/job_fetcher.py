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
    Fetch job postings for a company from Adzuna API.

    Strategy: try company= (employer name match) first — most precise.
    If that returns nothing, fall back to what_and= (keyword in title/description)
    for companies that don't post on Adzuna-aggregated boards directly.

    Each page = 1 quota unit. 3 pages × 50 results = up to 150 jobs for 3 calls.
    """
    # Try employer-name match first, then keyword fallback
    query_variants = [
        {"company": company},
        {"what_and": company},
    ]

    for query_params in query_variants:
        label = list(query_params.items())[0]
        all_jobs = _fetch_pages(company, query_params, num_pages)
        if all_jobs:
            print(f"[job_fetcher] {label[0]}='{label[1]}' → {len(all_jobs)} jobs")
            return _normalize(all_jobs)
        print(f"[job_fetcher] {label[0]}='{label[1]}' → 0 results, trying next variant…")

    print(f"[job_fetcher] No jobs found for '{company}'")
    return []


def _fetch_pages(company, extra_params, num_pages):
    """Fetch up to num_pages pages from Adzuna and return raw results."""
    base_url = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"
    all_jobs = []

    for page in range(1, num_pages + 1):
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_APP_KEY,
            "results_per_page": RESULTS_PER_PAGE,
            "content-type": "application/json",
            **extra_params
        }
        try:
            response = requests.get(base_url.format(page=page), params=params, timeout=60)
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
