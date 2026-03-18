from openai import OpenAI
import os
from dotenv import load_dotenv
from core.embeddings import search_jobs

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

Structure your answers using these sections where relevant:

**Hiring Signals** — the overall pattern in their hiring
**Roles Being Hired** — specific titles and what they indicate
**Skill Patterns** — technical capabilities they are building
**Strategic Interpretation** — what this means for their product/business strategy
**Evidence** — job titles used as references (listed at the end)"""


def answer_question(question, company, history):
    """Retrieve relevant jobs via RAG and generate a structured answer."""
    relevant_jobs = search_jobs(question, company=company if company else None, n_results=8)

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
