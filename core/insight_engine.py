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
competitive intelligence. Your job is to read hiring signals and infer what a company \
is actually building or prioritising — not to summarise job descriptions.

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
present in the job posting data. If a job posting does not say it, you cannot say it.

2. ZERO NEGATIVE LANGUAGE. You are absolutely forbidden from using any word or phrase \
that could be interpreted as negative, critical, or unflattering about the company. \
This includes but is not limited to: struggling, failing, behind, lacking, weak, \
scrambling, catching up, desperate, reactive, slow, losing, shrinking, cutting corners, \
damage control, forced to, under pressure, or any similar framing.

3. NO JUDGEMENTS. Do not evaluate whether the company's strategy is good or bad, \
smart or misguided, ahead or behind. You have no basis to judge — you only have job postings.

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
    titles = [j.get('title', '') for j in domain_jobs]
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
            'evidence': titles
        }
    except Exception as e:
        print(f"[insight_engine] Error for domain '{domain}': {e}")
        return None


def generate_insights(company, jobs):
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

    if all_insights:
        save_insights(all_insights)

    print(f"[insight_engine] Generated {len(all_insights)} insights for '{company}'")
    return all_insights
