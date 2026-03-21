import requests
import os
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.getenv('RAPIDAPI_KEY')
RAPIDAPI_HOST = os.getenv('RAPIDAPI_HOST', 'jsearch.p.rapidapi.com')


def fetch_jobs(company, num_pages=3):
    """
    Fetch job postings for a company from JSearch via RapidAPI.

    Why fallback queries?
    JSearch results depend heavily on query wording. "jobs at DBS Bank"
    might return nothing while "DBS Bank careers" returns 40 jobs.
    We try up to 3 query formats and return the first one that has results.
    All successful fetches cost exactly 1 API call.
    """
    url = f"https://{RAPIDAPI_HOST}/search"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": RAPIDAPI_HOST
    }

    # Try these query formats in order — stop at the first one that returns results
    query_variants = [
        f"jobs at {company}",
        f"{company} jobs",
        f"{company} hiring",
    ]

    for query in query_variants:
        params = {
            "query": query,
            "page": "1",
            "num_pages": str(num_pages),
            "date_posted": "month"
        }
        try:
            # 120s timeout — JSearch can be slow for large companies (Netflix, Google etc.)
            # This runs in a background thread so it never blocks the HTTP response.
            response = requests.get(url, headers=headers, params=params, timeout=120)
            response.raise_for_status()
            jobs = response.json().get('data', [])
            if jobs:
                print(f"[job_fetcher] '{query}' → {len(jobs)} jobs (1 API call)")
                return jobs
            else:
                print(f"[job_fetcher] '{query}' → 0 results, trying next variant…")
        except Exception as e:
            print(f"[job_fetcher] Error on query '{query}': {e}")

    print(f"[job_fetcher] All query variants returned 0 results for '{company}'")
    return []
