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

    Adzuna pagination: each page is a separate GET request (1 quota unit each).
    We fetch pages 1–num_pages and combine all results.

    The response 'description' field is truncated to ~500 chars by Adzuna —
    this is a platform limitation that affects extraction quality vs full JDs.
    """
    base_url = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"
    all_jobs = []

    for page in range(1, num_pages + 1):
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_APP_KEY,
            "results_per_page": RESULTS_PER_PAGE,
            "what_and": company,
            "content-type": "application/json"
        }
        try:
            url = base_url.format(page=page)
            response = requests.get(url, params=params, timeout=60)
            response.raise_for_status()
            results = response.json().get('results', [])
            print(f"[job_fetcher] Page {page} → {len(results)} jobs")
            all_jobs.extend(results)

            # Stop early if last page returned fewer results than requested
            if len(results) < RESULTS_PER_PAGE:
                break

        except Exception as e:
            print(f"[job_fetcher] Error on page {page} for '{company}': {e}")
            break

    if not all_jobs:
        print(f"[job_fetcher] No jobs found for '{company}'")
        return []

    print(f"[job_fetcher] Total: {len(all_jobs)} jobs for '{company}' ({min(num_pages, page)} API calls)")
    return _normalize(all_jobs)


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
