import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
EXTRACTION_MODEL = os.getenv('JOB_EXTRACTION_MODEL', 'gpt-4o-mini')
MAX_JOBS_TO_ANALYZE = int(os.getenv('MAX_JOBS_TO_ANALYZE', '75'))

# How many jobs to extract simultaneously.
# 10 parallel threads = ~10x faster than sequential.
# Stays well within OpenAI's rate limits for gpt-4o-mini.
MAX_WORKERS = 10

DOMAIN_TAXONOMY = [
    "mobile_growth", "consumer_growth", "ai_agents", "developer_platform",
    "ai_infrastructure", "inference_optimization", "model_research",
    "evaluation_safety", "enterprise_sales", "enterprise_platform",
    "data_platform", "ml_ops"
]

EXTRACT_PROMPT = """You are a competitive intelligence analyst extracting signals from a job posting.

Job Title: {title}
Company: {company}
Job Description:
{description}

Extract the following and return as a single JSON object:

{{
  "company": "{company}",
  "title": "exact job title",
  "team": "team or department name if explicitly mentioned, else empty string",
  "seniority": "one of: intern, junior, mid, senior, staff, principal, manager, director, vp — infer from title keywords (e.g. 'Senior', 'Staff', 'Principal', 'Director', 'VP', 'Intern', 'Associate') OR from experience requirements (0-2 yrs → junior, 3-5 yrs → mid, 5+ yrs → senior). Use 'mid' as default if unclear but clearly not entry-level or leadership",
  "domain_tags": ["domains from taxonomy below — pick ALL that apply"],
  "skills": ["technical and soft skills required, max 12"],
  "responsibilities": ["key responsibilities, max 5, be specific not generic"],
  "experience": "experience requirement as a short string",
  "location": "location or Remote",

  "metrics": ["any specific metrics mentioned e.g. DAU, MAU, D7 retention, CTR, LTV, ARPU, NPS — only include if explicitly named"],
  "tools_platforms": ["any specific named tools or platforms e.g. Braze, Amplitude, Mixpanel, Segment, Snowflake, dbt, Kubernetes, CUDA — only include if explicitly named"],
  "team_names": ["any internal team or pod names mentioned e.g. 'Frontier Research', 'Growth Platform', 'ChatGPT team' — only if explicitly stated"],
  "business_goals": ["any explicit business objectives stated e.g. 'grow DAU by 2x', 'launch enterprise tier', 'improve onboarding completion' — only if explicitly stated"]
}}

Domain taxonomy (multi-label — pick ALL that apply):
{domains}

Rules:
- For metrics, tools_platforms, team_names, business_goals: only extract what is EXPLICITLY mentioned. Do not infer or guess. Empty list is fine.
- For responsibilities: be specific — include actual numbers or tools mentioned in the description, not generic phrases like "work cross-functionally".

Return only valid JSON. No text outside the JSON."""


def _extract_single(job, company):
    """Extract structured data from one job. Runs in a thread pool."""
    title = job.get('job_title', '') or ''
    description = (job.get('job_description', '') or '')[:3000]
    job_url = job.get('job_apply_link', '') or job.get('job_google_link', '') or ''

    if not description.strip():
        return None

    prompt = EXTRACT_PROMPT.format(
        title=title,
        company=company,
        description=description,
        domains=', '.join(DOMAIN_TAXONOMY)
    )

    try:
        response = client.chat.completions.create(
            model=EXTRACTION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0
        )
        extracted = json.loads(response.choices[0].message.content)
        extracted['raw_description'] = description
        extracted['job_url'] = job_url
        return extracted
    except Exception as e:
        print(f"[job_extractor] Extraction error for '{title}': {e}")
        return {
            'company': company, 'title': title,
            'team': '', 'seniority': '',
            'domain_tags': [], 'skills': [], 'responsibilities': [],
            'experience': '', 'location': '',
            'metrics': [], 'tools_platforms': [], 'team_names': [], 'business_goals': [],
            'raw_description': description, 'job_url': job_url
        }


def _normalize_text(text):
    text = re.sub(r"\s+", " ", (text or "").strip().lower())
    return text


def _dedupe_and_limit_jobs(raw_jobs):
    ranked = []
    for job in raw_jobs:
        description = job.get('job_description', '') or ''
        title = job.get('job_title', '') or ''
        url = job.get('job_apply_link', '') or job.get('job_google_link', '') or ''
        ranked.append((
            -len(description),
            title.lower(),
            {
                **job,
                'job_description': description,
                'job_title': title,
                'job_apply_link': url,
            }
        ))

    ranked.sort(key=lambda item: (item[0], item[1]))

    deduped = []
    seen = set()
    for _, _, job in ranked:
        description = _normalize_text(job.get('job_description', ''))
        signature = (
            _normalize_text(job.get('job_title', '')),
            _normalize_text(job.get('job_apply_link', '')),
            description[:600],
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(job)
        if len(deduped) >= MAX_JOBS_TO_ANALYZE:
            break

    return deduped


def extract_and_classify_jobs(raw_jobs, company):
    """
    Extract structured data from all jobs in parallel using a thread pool.
    10 simultaneous OpenAI calls → ~10x faster than sequential.
    """
    valid_jobs = [j for j in raw_jobs if (j.get('job_description', '') or '').strip()]
    valid_jobs = _dedupe_and_limit_jobs(valid_jobs)

    structured = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_extract_single, job, company): job for job in valid_jobs}
        for future in as_completed(futures):
            result = future.result()
            if result:
                structured.append(result)

    print(f"[job_extractor] Extracted {len(structured)} structured jobs for '{company}'")
    return structured
