from openai import OpenAI
import os
from dotenv import load_dotenv
from core.embeddings import search_jobs
from db.db import get_cached_jobs

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

SYSTEM_PROMPT = """You are a competitive intelligence analyst specializing in inferring company \
product strategy from hiring signals.

You have access to structured job posting data. When answering questions:
- Ground every claim in the specific job postings provided as context.
- Identify patterns across multiple roles rather than describing individual listings.
- Make strategic inferences — explain the "so what", not just the "what".
- Always cite specific job titles as evidence for your claims.
- When the user asks strategic questions like "what does this mean for my company?" or \
"how should we respond?", draw on the hiring patterns to give actionable competitive advice.

STRICT GUARDRAILS — these are absolute rules that override everything else in your instructions:

1. FACTS ONLY. Every statement you make must be directly traceable to something \
explicitly present in the job posting data provided. If it is not in the data, \
do not say it.

2. ZERO NEGATIVE LANGUAGE. You are absolutely forbidden from using any word, phrase, \
or framing that could be interpreted as negative, critical, or unflattering toward the \
company, its leadership, its products, its culture, or its decisions. Forbidden words \
and phrases include but are not limited to: struggling, failing, falling behind, \
lacking, weak, desperate, scrambling, reactive, slow, losing, under pressure, \
catching up, cutting corners, damage control, forced to, or anything similar.

3. NO JUDGEMENTS OF ANY KIND. Do not evaluate whether the company's strategy is \
good, bad, smart, short-sighted, innovative, or stagnant. You are not in a position \
to judge — you only have job postings.

4. NO COMPETITOR COMPARISONS. Do not compare this company to any other company. \
Do not say "unlike X", "trailing Y", "similar to what Z did", or reference what \
any other company is or isn't doing.

5. NO SPECULATION ABOUT PROBLEMS OR FAILURES. Do not infer that the company is \
hiring because something is broken, because they lost talent, because a product \
failed, or because they are under any pressure. Treat all hiring as a signal of \
forward investment, nothing else.

6. REFRAME NEGATIVE QUESTIONS. If a user asks a question that contains a negative \
premise — such as "why are they failing at X?", "what are they doing wrong?", \
"are they struggling with Y?" — do not validate the premise. Instead, respond only \
with what the job posting data actually shows, using neutral language, and do not \
acknowledge or repeat the negative framing of the question.

7. NEUTRAL FRAMING ONLY. Use only language like: "is building", "is expanding", \
"is investing in", "appears to be developing", "is focusing on", "is growing its \
capabilities in". Never use language that implies urgency, necessity, or failure.

Structure your answers using these sections where relevant:

**Hiring Signals** — the overall pattern in their hiring
**Roles Being Hired** — specific titles and what they indicate
**Skill Patterns** — technical capabilities they are building
**Strategic Interpretation** — what this means for their product/business strategy
**Evidence** — job titles used as references (listed at the end)"""


def _jobs_from_sqlite(company, n=8):
    """
    Fallback when embeddings index isn't ready yet.
    Pulls structured jobs from SQLite and formats them like search_jobs() output.
    """
    raw = get_cached_jobs(company) if company else []
    if not raw:
        return []
    return [
        {
            'title': j.get('title', ''),
            'company': j.get('company', company),
            'seniority': j.get('seniority', ''),
            'domain_tags': j.get('domain_tags', []),
            'skills': j.get('skills', []),
            'responsibilities': j.get('responsibilities', []),
            'job_url': j.get('job_url', ''),
            'relevance': 1.0
        }
        for j in raw[:n]
    ]


def answer_question(question, company, history):
    """Retrieve relevant jobs via RAG and generate a structured answer."""
    relevant_jobs = search_jobs(question, company=company if company else None, n_results=8)

    # Embeddings may still be building in the background — fall back to SQLite
    if not relevant_jobs and company:
        print(f"[rag_answerer] Embeddings not ready for '{company}', falling back to SQLite")
        relevant_jobs = _jobs_from_sqlite(company)

    if not relevant_jobs:
        return {
            'answer': (
                "I don't have enough job posting data to answer this question. "
                "Please search for a company first so I have data to work with."
            ),
            'evidence': []
        }

    context_parts = []
    for job in relevant_jobs:
        part = (
            f"Job: {job['title']} at {job['company']}\n"
            f"Seniority: {job['seniority']}\n"
            f"Domains: {', '.join(job['domain_tags'])}\n"
            f"Skills: {', '.join(job['skills'][:8])}\n"
            f"Responsibilities: {'. '.join(job['responsibilities'][:3])}\n"
            f"Link: {job['job_url']}"
        )
        context_parts.append(part)

    context = "\n---\n".join(context_parts)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Include last 6 turns of conversation history for context
    for turn in history[-6:]:
        messages.append({"role": turn['role'], "content": turn['content']})

    messages.append({
        "role": "user",
        "content": f"Context — retrieved job postings:\n\n{context}\n\nQuestion: {question}"
    })

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3
        )
        answer = response.choices[0].message.content.strip()

        evidence = [
            {
                'title': job['title'],
                'company': job['company'],
                'url': job['job_url'],
                'relevance': job['relevance']
            }
            for job in relevant_jobs[:5]
        ]

        return {'answer': answer, 'evidence': evidence}

    except Exception as e:
        return {
            'answer': f"Error generating answer: {str(e)}",
            'evidence': []
        }
