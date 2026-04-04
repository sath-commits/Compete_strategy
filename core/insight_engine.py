from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
import os
from dotenv import load_dotenv
from db.db import save_insights

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

MIN_JOBS_FOR_INSIGHT = 2

CONSULTANT_SYSTEM_PROMPT = """You are a senior strategy consultant who specialises in \
competitive intelligence. Your job is to read source evidence and infer what a company \
is actually building or prioritising — not to simply summarise raw documents.

Your reasoning method:
1. Look for PATTERNS across multiple roles, not individual job summaries.
2. When the same tool, metric, team name, or business goal appears in multiple roles, \
that repetition is a strong signal of a strategic initiative.
3. Name the initiative specifically. Bad: "they are investing in mobile". \
Good: "they appear to be building a mobile re-engagement system using Braze push \
notifications, targeting D7 retention improvement."
4. Build an evidence chain: list exactly which roles and which specific detail \
(a tool, a metric, a responsibility) supports your inference.
5. State your confidence: HIGH (3+ corroborating signals), MEDIUM (2 signals), \
LOW (1 signal but strong).

Reasoning examples:
- 3 roles mention Braze + push notifications → infer a retention/re-engagement initiative
- Growth PM role mentions D7 retention + onboarding experiments → mobile growth is a \
current OKR
- Multiple roles name the same internal team (e.g. "Frontier Research") → that team \
is expanding, likely a new product surface
- Roles requiring both Kubernetes and CUDA → building in-house GPU inference \
infrastructure, not outsourcing to cloud
- Enterprise AE + Solutions Engineer + Customer Success hired together → preparing \
for an enterprise GTM motion, not just self-serve

STRICT GUARDRAILS — these override everything else. Violating any of these is not allowed:

1. FACTS ONLY. Every single statement must be directly traceable to something explicitly \
present in the source data. If the source data does not say it, you cannot say it.

2. ZERO NEGATIVE LANGUAGE. You are absolutely forbidden from using any word or phrase \
that could be interpreted as negative, critical, or unflattering about the company. \
This includes but is not limited to: struggling, failing, behind, lacking, weak, \
scrambling, catching up, desperate, reactive, slow, losing, shrinking, cutting corners, \
damage control, forced to, under pressure, or any similar framing.

3. NO JUDGEMENTS. Do not evaluate whether the company's strategy is good or bad, \
smart or misguided, ahead or behind. You have no basis to judge — you only have source data.

4. NO COMPETITOR COMPARISONS. Do not compare the company to any other company, \
positively or negatively. Do not say "unlike X" or "similar to what Y did" or \
"trailing Z in this area".

5. NO SPECULATION ABOUT PROBLEMS. Do not infer that the company is hiring because \
something is broken, because they lost someone, because they failed at something, \
or because they are under any kind of pressure. Hiring is a signal of investment, \
not dysfunction.

6. NEUTRAL FRAMING ONLY. All inferences must be framed as observations about where \
the company is directing investment. Use only language like: "is building", \
"is expanding", "is investing in", "appears to be developing", "is focusing on". \
Never use framing that implies urgency, failure, or necessity.

7. NO PRECISE FORECASTING. Do not invent revenue numbers, growth rates, or precise financial projections. \
If discussing future implications, keep them directional and limited to the next 2-4 quarters unless the source data explicitly provides guidance.

Output format (use exactly this structure):
**Strategic Initiative:** [one sharp sentence naming the initiative]

**Evidence Chain:**
- [Role title]: [specific signal — tool / metric / responsibility / team name]
- [Role title]: [specific signal]
- ...

**Confidence:** HIGH / MEDIUM / LOW

**So What:** [1-2 sentences on what this means competitively — what are they likely \
to launch or announce in the next 6-12 months?]"""


def _serialize_jobs_for_prompt(domain_jobs):
    """
    Format all jobs in a domain into a rich block for the LLM.
    The richer the input, the more specific the inference.
    We now include metrics, tools, team names, and business goals
    because these are the strongest strategy signals.
    """
    lines = []
    for i, job in enumerate(domain_jobs, 1):
        lines.append(f"--- Role {i}: {job.get('title', 'Unknown')} ---")
        if job.get('team'):
            lines.append(f"Team/Pod: {job['team']}")
        if job.get('seniority'):
            lines.append(f"Seniority: {job['seniority']}")
        if job.get('skills'):
            lines.append(f"Skills: {', '.join(job['skills'][:12])}")
        if job.get('tools_platforms'):
            lines.append(f"Named tools/platforms: {', '.join(job['tools_platforms'])}")
        if job.get('metrics'):
            lines.append(f"Metrics mentioned: {', '.join(job['metrics'])}")
        if job.get('team_names'):
            lines.append(f"Internal team names: {', '.join(job['team_names'])}")
        if job.get('business_goals'):
            lines.append(f"Explicit business goals: {'; '.join(job['business_goals'])}")
        if job.get('responsibilities'):
            lines.append(f"Responsibilities: {'; '.join(job['responsibilities'][:5])}")
        lines.append("")
    return "\n".join(lines)


def _generate_single_insight(company, domain, domain_jobs):
    """Generate one domain insight. Runs in a thread pool."""
    job_block = _serialize_jobs_for_prompt(domain_jobs)

    user_prompt = (
        f"Company: {company}\n"
        f"Strategic domain: {domain.replace('_', ' ').title()}\n"
        f"Number of roles in this domain: {len(domain_jobs)}\n\n"
        f"Raw hiring data:\n{job_block}\n"
        f"Using the reasoning method above, what strategic initiative is {company} "
        f"most likely pursuing in the '{domain.replace('_', ' ')}' domain? "
        f"Be specific. Name tools, metrics, and team names you see repeated. "
        f"Do not summarise — infer."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": CONSULTANT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        return {
            'company': company,
            'domain': domain,
            'insight_text': response.choices[0].message.content.strip(),
            'evidence': [
                {
                    'title': job.get('title', ''),
                    'url': job.get('job_url', ''),
                    'source_type': 'job',
                    'label': job.get('title', '')
                }
                for job in domain_jobs[:6]
            ]
        }
    except Exception as e:
        print(f"[insight_engine] Error for domain '{domain}': {e}")
        return None


def _serialize_company_docs_for_prompt(company_docs):
    lines = []
    for i, doc in enumerate(company_docs, 1):
        lines.append(f"--- Official Source {i}: {doc.get('title', 'Unknown')} ---")
        if doc.get('source_type'):
            lines.append(f"Source type: {doc['source_type']}")
        if doc.get('source_group'):
            lines.append(f"Source group: {doc['source_group']}")
        if doc.get('fiscal_period'):
            lines.append(f"Fiscal period: {doc['fiscal_period']}")
        if doc.get('published_at'):
            lines.append(f"Published at: {doc['published_at']}")
        if doc.get('summary_text'):
            lines.append(f"Summary: {doc['summary_text']}")
        signals = doc.get('structured_signals') or {}
        if signals.get('focus_areas'):
            lines.append(f"Focus areas: {', '.join(signals['focus_areas'])}")
        if signals.get('products_or_initiatives'):
            lines.append(f"Products or initiatives: {', '.join(signals['products_or_initiatives'])}")
        if signals.get('metrics'):
            lines.append(f"Metrics/guidance: {', '.join(signals['metrics'])}")
        if signals.get('management_priorities'):
            lines.append(f"Management priorities: {', '.join(signals['management_priorities'])}")
        if signals.get('qa_topics'):
            lines.append(f"Q&A topics: {', '.join(signals['qa_topics'])}")
        lines.append("")
    return "\n".join(lines)


def _generate_official_materials_insight(company, jobs, company_docs):
    if not company_docs:
        return None

    docs_block = _serialize_company_docs_for_prompt(company_docs)
    hiring_domains = sorted({tag for job in jobs for tag in job.get('domain_tags', [])})

    user_prompt = (
        f"Company: {company}\n"
        f"Hiring domains observed: {', '.join(hiring_domains) if hiring_domains else 'None'}\n\n"
        f"Official company materials:\n{docs_block}\n"
        f"Using the same output format, write one mixed-source insight that explains the clearest "
        f"official-company signal visible in these materials. You may mention alignment "
        f"with hiring patterns only if it is directly supported by the data.\n"
        f"In the Evidence Chain, cite the official source titles directly."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": CONSULTANT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2
        )
        evidence = [
            {
                'title': doc.get('title', ''),
                'url': doc.get('source_url', ''),
                'source_type': doc.get('source_type', ''),
                'period': doc.get('fiscal_period', '') or doc.get('published_at', '')
            }
            for doc in company_docs[:6]
        ]
        return {
            'company': company,
            'domain': 'official_signals',
            'insight_text': response.choices[0].message.content.strip(),
            'evidence': evidence
        }
    except Exception as e:
        print(f"[insight_engine] Error generating official materials insight: {e}")
        return None


def generate_insights(company, jobs, company_docs=None):
    """
    Group jobs by domain and generate consultant-style insights in parallel.
    All domain insights are generated simultaneously instead of sequentially.
    """
    domain_groups = defaultdict(list)
    for job in jobs:
        for tag in job.get('domain_tags', []):
            domain_groups[tag].append(job)

    eligible = {
        domain: domain_jobs
        for domain, domain_jobs in domain_groups.items()
        if len(domain_jobs) >= MIN_JOBS_FOR_INSIGHT
    }

    all_insights = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_generate_single_insight, company, domain, domain_jobs): domain
            for domain, domain_jobs in eligible.items()
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                all_insights.append(result)

    official_insight = _generate_official_materials_insight(company, jobs, company_docs or [])
    if official_insight:
        all_insights.insert(0, official_insight)

    if all_insights:
        save_insights(all_insights)

    print(f"[insight_engine] Generated {len(all_insights)} insights for '{company}'")
    return all_insights
