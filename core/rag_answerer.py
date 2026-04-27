from openai import OpenAI
import os
from dotenv import load_dotenv
from core.embeddings import search_documents
from db.db import get_cached_jobs, get_cached_company_documents

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
CHAT_MODEL = os.getenv('CHAT_MODEL', 'gpt-4o-mini')

SOURCE_PRIORITY = {
    'earnings_call_transcript': 100,
    'shareholder_letter': 98,
    'investor_day': 96,
    'quarterly_filing': 90,
    'earnings_release': 88,
    'sec_form_d': 86,
    'job': 80,
    'arxiv_paper': 78,
    'patent': 76,
    'pricing_page': 74,
    'product_doc': 72,
    'changelog': 70,
    'github_release': 68,
    'customer_story': 64,
    'partner_page': 62,
    'newsroom_post': 50,
}

SYSTEM_PROMPT = """You are a competitive intelligence analyst specializing in inferring company \
product strategy from hiring signals and official company materials.

You have access to structured job posting data and, when available, official company materials such as filings, press releases, changelogs, and GitHub releases. When answering questions:
- Ground every claim in the specific source material provided as context.
- Identify patterns across multiple roles rather than describing individual listings.
- Make strategic inferences — explain the "so what", not just the "what".
- Always cite specific sources as evidence for your claims.
- When the user asks strategic questions like "what does this mean for my company?" or \
"how should we respond?", draw on the source patterns to give actionable competitive advice.

STRICT GUARDRAILS — these are absolute rules that override everything else in your instructions:

1. FACTS ONLY. Every statement you make must be directly traceable to something \
explicitly present in the source data provided. If it is not in the data, \
do not say it.

2. ZERO NEGATIVE LANGUAGE. You are absolutely forbidden from using any word, phrase, \
or framing that could be interpreted as negative, critical, or unflattering toward the \
company, its leadership, its products, its culture, or its decisions. Forbidden words \
and phrases include but are not limited to: struggling, failing, falling behind, \
lacking, weak, desperate, scrambling, reactive, slow, losing, under pressure, \
catching up, cutting corners, damage control, forced to, or anything similar.

3. NO JUDGEMENTS OF ANY KIND. Do not evaluate whether the company's strategy is \
good, bad, smart, short-sighted, innovative, or stagnant. You are not in a position \
to judge — you only have source documents.

4. NO COMPETITOR COMPARISONS. Do not compare this company to any other company. \
Do not say "unlike X", "trailing Y", "similar to what Z did", or reference what \
any other company is or isn't doing.

5. NO SPECULATION ABOUT PROBLEMS OR FAILURES. Do not infer that the company is \
hiring because something is broken, because they lost talent, because a product \
failed, or because they are under any pressure. Treat all source material as a signal of \
stated priorities and forward investment, nothing else.

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
**Official Signals** — what the company's official materials emphasize
**Roles Being Hired** — specific titles and what they indicate
**Skill Patterns** — technical capabilities they are building
**Strategic Interpretation** — what this means for their product/business strategy
**Evidence** — source titles used as references (listed at the end)"""


def _documents_from_sqlite(company, n=10):
    """
    Fallback when embeddings index isn't ready yet.
    Pulls structured jobs and company documents from SQLite.
    """
    jobs = [
        {
            'source_type': 'job',
            'title': j.get('title', ''),
            'company': j.get('company') or company,
            'seniority': j.get('seniority', ''),
            'domain_tags': j.get('domain_tags', []),
            'skills': j.get('skills', []),
            'responsibilities': j.get('responsibilities', []),
            'job_url': j.get('job_url', ''),
            'period': '',
            'text_snippet': '',
            'relevance': 1.0
        }
        for j in (get_cached_jobs(company) if company else [])[:n]
    ]

    company_docs = [
        {
            'source_type': doc.get('source_type', 'company_document'),
            'title': doc.get('title', ''),
            'company': doc.get('company') or company,
            'seniority': '',
            'domain_tags': [],
            'skills': [],
            'responsibilities': [],
            'job_url': doc.get('source_url', ''),
            'period': doc.get('fiscal_period', ''),
            'text_snippet': doc.get('summary_text', ''),
            'relevance': 1.0
        }
        for doc in (get_cached_company_documents(company) if company else [])[:6]
    ]
    return (jobs + company_docs)[:n]


def _format_context_part(doc):
    if doc.get('source_type') == 'job':
        return (
            f"Source type: Job posting\n"
            f"Title: {doc['title']} at {doc['company']}\n"
            f"Seniority: {doc['seniority']}\n"
            f"Domains: {', '.join(doc['domain_tags'])}\n"
            f"Skills: {', '.join(doc['skills'][:8])}\n"
            f"Responsibilities: {'. '.join(doc['responsibilities'][:3])}\n"
            f"Link: {doc['job_url']}"
        )

    return (
        f"Source type: {doc.get('source_type', 'company_document')}\n"
        f"Title: {doc.get('title', '')}\n"
        f"Company: {doc.get('company', '')}\n"
        f"Fiscal period: {doc.get('period', '')}\n"
        f"Summary: {doc.get('text_snippet', '')}\n"
        f"Link: {doc.get('job_url', '')}"
    )


def answer_question(question, company, history):
    """Retrieve relevant source documents via RAG and generate a structured answer."""
    try:
        relevant_docs = search_documents(question, company=company if company else None, n_results=10)
    except Exception as e:
        print(f"[rag_answerer] Embeddings search error: {e}")
        relevant_docs = []

    # Embeddings may still be building in the background — fall back to SQLite
    if not relevant_docs and company:
        print(f"[rag_answerer] Embeddings empty for '{company}', falling back to SQLite")
        try:
            relevant_docs = _documents_from_sqlite(company)
        except Exception as e:
            print(f"[rag_answerer] SQLite fallback error: {e}")
            relevant_docs = []

    if not relevant_docs:
        return {
            'answer': (
                "I don't have enough source data to answer this question. "
                "Please search for a company first so I have data to work with."
            ),
            'evidence': []
        }

    relevant_docs = sorted(
        relevant_docs,
        key=lambda doc: (
            SOURCE_PRIORITY.get(doc.get('source_type', 'job'), 10),
            doc.get('relevance', 0),
        ),
        reverse=True
    )

    context = "\n---\n".join(_format_context_part(doc) for doc in relevant_docs)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for turn in history[-6:]:
        messages.append({"role": turn['role'], "content": turn['content']})

    messages.append({
        "role": "user",
        "content": f"Context — retrieved source documents:\n\n{context}\n\nQuestion: {question}"
    })

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            temperature=0.3
        )
        answer = response.choices[0].message.content.strip()

        evidence = [
            {
                'title': doc['title'],
                'company': doc['company'],
                'url': doc['job_url'],
                'relevance': doc['relevance'],
                'source_type': doc.get('source_type', 'job'),
                'period': doc.get('period', '')
            }
            for doc in relevant_docs[:5]
        ]

        return {'answer': answer, 'evidence': evidence}

    except Exception as e:
        print(f"[rag_answerer] LLM error: {e}")
        return {
            'answer': "I ran into an error generating the answer. Please try again.",
            'evidence': []
        }
