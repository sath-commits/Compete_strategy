from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
import os
import re
from dotenv import load_dotenv
from db.db import save_insights

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
DOMAIN_INSIGHT_MODEL = os.getenv('DOMAIN_INSIGHT_MODEL', 'gpt-4o-mini')
FINAL_SYNTHESIS_MODEL = os.getenv('FINAL_SYNTHESIS_MODEL', 'gpt-5-mini')

MIN_JOBS_FOR_INSIGHT = 2
MAX_DOMAIN_INSIGHTS = int(os.getenv('MAX_DOMAIN_INSIGHTS', '5'))

SOURCE_PRIORITY = {
    'earnings_call_transcript': 100,
    'shareholder_letter': 98,
    'investor_day': 96,
    'quarterly_filing': 90,
    'earnings_release': 88,
    'job': 80,
    'pricing_page': 74,
    'product_doc': 72,
    'changelog': 70,
    'github_release': 68,
    'customer_story': 64,
    'partner_page': 62,
    'newsroom_post': 50,
}

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
            model=DOMAIN_INSIGHT_MODEL,
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

    top_docs = _pick_top_documents(company_docs, limit=6)
    docs_block = _serialize_company_docs_for_prompt(top_docs)
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
            model=DOMAIN_INSIGHT_MODEL,
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
            for doc in top_docs
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


def _clean_text(value):
    return re.sub(r'\s+', ' ', str(value or '').strip())


def _pick_top_documents(company_docs, limit=6):
    ranked = sorted(
        company_docs,
        key=lambda doc: (
            SOURCE_PRIORITY.get(doc.get('source_type', ''), 10),
            _clean_text(doc.get('published_at') or doc.get('fiscal_period') or ''),
        ),
        reverse=True
    )
    return ranked[:limit]


def _summarize_job_patterns(jobs):
    domain_counts = defaultdict(int)
    tool_counts = defaultdict(int)
    metric_counts = defaultdict(int)
    team_counts = defaultdict(int)

    for job in jobs:
        for domain in job.get('domain_tags', []):
            domain_counts[domain] += 1
        for tool in job.get('tools_platforms', []):
            tool_counts[tool] += 1
        for metric in job.get('metrics', []):
            metric_counts[metric] += 1
        for team_name in job.get('team_names', []):
            team_counts[team_name] += 1

    lines = []
    top_domains = sorted(domain_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
    if top_domains:
        lines.append("Hiring domain concentration:")
        for domain, count in top_domains:
            lines.append(f"- {domain.replace('_', ' ')}: {count} roles")

    for heading, counter in (
        ("Repeated tools/platforms", tool_counts),
        ("Repeated metrics", metric_counts),
        ("Repeated internal team names", team_counts),
    ):
        items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:6]
        if items:
            lines.append(f"{heading}:")
            for label, count in items:
                lines.append(f"- {label}: {count} mentions")

    lines.append("Representative roles:")
    for job in jobs[:6]:
        signals = []
        if job.get('team'):
            signals.append(f"team={job['team']}")
        if job.get('tools_platforms'):
            signals.append(f"tools={', '.join(job['tools_platforms'][:3])}")
        if job.get('metrics'):
            signals.append(f"metrics={', '.join(job['metrics'][:2])}")
        if job.get('business_goals'):
            signals.append(f"goals={'; '.join(job['business_goals'][:2])}")
        signal_text = f" ({'; '.join(signals)})" if signals else ""
        lines.append(f"- {job.get('title', 'Unknown role')}{signal_text}")
    return "\n".join(lines)


def _summarize_official_patterns(company_docs):
    docs = _pick_top_documents(company_docs, limit=6)
    lines = []
    for doc in docs:
        label = doc.get('fiscal_period') or doc.get('published_at') or ''
        lines.append(
            f"- {doc.get('title', 'Unknown source')} [{doc.get('source_type', 'official')}]{f' ({label})' if label else ''}"
        )
        signals = doc.get('structured_signals') or {}
        for field in ('management_priorities', 'products_or_initiatives', 'focus_areas', 'metrics', 'qa_topics'):
            values = signals.get(field) or []
            if values:
                lines.append(f"  {field}: {', '.join(values[:4])}")
        if doc.get('summary_text'):
            lines.append(f"  summary: {_clean_text(doc.get('summary_text'))[:280]}")
    return "\n".join(lines)


def _generate_final_strategy_readout(company, jobs, company_docs):
    docs = _pick_top_documents(company_docs, limit=6)
    source_hierarchy = (
        "earnings call / shareholder letter / investor day > "
        "10-Q / 10-K / 8-K > jobs > product docs / changelog / pricing > "
        "customer stories / partner pages > newsroom posts"
    )
    user_prompt = (
        f"Company: {company}\n"
        f"Source hierarchy to respect: {source_hierarchy}\n\n"
        f"Structured hiring patterns:\n{_summarize_job_patterns(jobs)}\n\n"
        f"Official company patterns:\n{_summarize_official_patterns(docs)}\n\n"
        "Write one top-level strategic readout that synthesizes the strongest signals across all sources.\n"
        "Rules:\n"
        "- Respect the source hierarchy above when signals conflict.\n"
        "- Jobs are more important than product docs, changelogs, pricing pages, customer stories, partner pages, and newsroom posts.\n"
        "- Prefer repeated management commentary from earnings calls and filings over lighter-weight sources.\n"
        "- If the only official materials are lightweight sources such as GitHub releases, changelogs, or newsroom posts, do not let them override stronger repeated hiring patterns.\n"
        "- If official sources are limited or narrow, the readout should lead with the clearest hiring pattern instead of over-centering those sources.\n"
        "- If hiring confirms a management signal, say so explicitly.\n"
        "- If official sources are sparse, still use the hierarchy rather than treating all sources equally.\n"
        "- Use the exact output format from the system prompt.\n"
        "- In the evidence chain, cite both official sources and representative roles where relevant."
    )

    try:
        response = client.chat.completions.create(
            model=FINAL_SYNTHESIS_MODEL,
            messages=[
                {"role": "system", "content": CONSULTANT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.15
        )
        evidence = [
            {
                'title': doc.get('title', ''),
                'url': doc.get('source_url', ''),
                'source_type': doc.get('source_type', ''),
                'period': doc.get('fiscal_period', '') or doc.get('published_at', '')
            }
            for doc in docs[:4]
        ] + [
            {
                'title': job.get('title', ''),
                'url': job.get('job_url', ''),
                'source_type': 'job',
                'label': job.get('title', '')
            }
            for job in jobs[:4]
        ]
        return {
            'company': company,
            'domain': 'strategic_readout',
            'insight_text': response.choices[0].message.content.strip(),
            'evidence': evidence
        }
    except Exception as e:
        print(f"[insight_engine] Error generating final strategy readout: {e}")
        return None


def _is_lightweight_official_source(source_type: str) -> bool:
    return source_type in {'github_release', 'changelog', 'newsroom_post'}


def _choose_primary_insight(insights):
    if not insights:
        return None, []

    strategic = next((ins for ins in insights if ins.get('domain') == 'strategic_readout'), None)
    if strategic:
        evidence_types = {e.get('source_type', 'job') for e in (strategic.get('evidence') or [])}
        has_jobs = 'job' in evidence_types
        has_strong_official = any(
            source_type != 'job'
            and SOURCE_PRIORITY.get(source_type, 0) >= SOURCE_PRIORITY['job']
            and not _is_lightweight_official_source(source_type)
            for source_type in evidence_types
        )
        if has_jobs or has_strong_official:
            return strategic, [ins for ins in insights if ins is not strategic]

    strongest_hiring = next(
        (ins for ins in insights if ins.get('domain') not in {'official_signals', 'strategic_readout'}),
        None
    )
    if strongest_hiring:
        return strongest_hiring, [ins for ins in insights if ins is not strongest_hiring]

    primary = insights[0]
    return primary, insights[1:]


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
    ranked_domains = sorted(
        eligible.items(),
        key=lambda item: (-len(item[1]), item[0])
    )[:MAX_DOMAIN_INSIGHTS]

    all_insights = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_generate_single_insight, company, domain, domain_jobs): domain
            for domain, domain_jobs in ranked_domains
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                all_insights.append(result)
    domain_rank = {domain: idx for idx, (domain, _) in enumerate(ranked_domains)}
    all_insights.sort(key=lambda item: domain_rank.get(item.get('domain', ''), 999))

    final_readout = _generate_final_strategy_readout(company, jobs, company_docs or [])
    if final_readout:
        all_insights.insert(0, final_readout)

    official_insight = _generate_official_materials_insight(company, jobs, company_docs or [])
    if official_insight:
        insert_at = 1 if final_readout else 0
        all_insights.insert(insert_at, official_insight)

    primary_insight, remaining_insights = _choose_primary_insight(all_insights)
    ordered_insights = ([primary_insight] if primary_insight else []) + remaining_insights

    if ordered_insights:
        save_insights(ordered_insights)

    print(f"[insight_engine] Generated {len(ordered_insights)} insights for '{company}'")
    return ordered_insights
