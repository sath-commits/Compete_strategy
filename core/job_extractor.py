import json
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

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
  "seniority": "one of: intern, junior, mid, senior, staff, principal, manager, director, vp — or empty string",
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


def extract_and_classify_jobs(raw_jobs, company):
    """
    Call GPT-4o-mini once per job to extract the full structured schema.
    The richer fields (metrics, tools_platforms, team_names, business_goals)
    are what make the insight engine actually useful — they let us find
    patterns like '4 roles mention Braze' rather than just listing titles.
    """
    structured = []

    for job in raw_jobs:
        title = job.get('job_title', '') or ''
        description = (job.get('job_description', '') or '')[:3000]
        job_url = job.get('job_apply_link', '') or job.get('job_google_link', '') or ''

        if not description.strip():
            continue

        prompt = EXTRACT_PROMPT.format(
            title=title,
            company=company,
            description=description,
            domains=', '.join(DOMAIN_TAXONOMY)
        )

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0
            )
            extracted = json.loads(response.choices[0].message.content)
            extracted['raw_description'] = description
            extracted['job_url'] = job_url
            structured.append(extracted)
        except Exception as e:
            print(f"[job_extractor] Extraction error for '{title}': {e}")
            structured.append({
                'company': company, 'title': title,
                'team': '', 'seniority': '',
                'domain_tags': [], 'skills': [], 'responsibilities': [],
                'experience': '', 'location': '',
                'metrics': [], 'tools_platforms': [], 'team_names': [], 'business_goals': [],
                'raw_description': description, 'job_url': job_url
            })

    print(f"[job_extractor] Extracted {len(structured)} structured jobs for '{company}'")
    return structured
