import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
EMBEDDINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'embeddings.json')


def _embed(text):
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000]
    )
    return response.data[0].embedding


def _load_index():
    if os.path.exists(EMBEDDINGS_PATH):
        with open(EMBEDDINGS_PATH) as f:
            return json.load(f)
    return {}


def _save_index(index):
    os.makedirs(os.path.dirname(EMBEDDINGS_PATH), exist_ok=True)
    with open(EMBEDDINGS_PATH, 'w') as f:
        json.dump(index, f)


def get_index_count():
    return len(_load_index())


def _make_doc_id(prefix, company, title, i):
    return (
        f"{prefix}_{company or 'x'}_{title or 'x'}_{i}"
        .replace(' ', '_').replace('/', '_')[:160]
    )


def _embed_job(args):
    """Embed a single job. Runs in a thread pool."""
    i, job = args
    text = (
        f"Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Team: {job.get('team', '')}\n"
        f"Domains: {', '.join(job.get('domain_tags', []))}\n"
        f"Skills: {', '.join(job.get('skills', []))}\n"
        f"Responsibilities: {'. '.join(job.get('responsibilities', []))}\n"
        f"Experience: {job.get('experience', '')}"
    ).strip()

    doc_id = _make_doc_id('job', job.get('company', ''), job.get('title', ''), i)

    try:
        embedding = _embed(text)
        return doc_id, {
            'embedding': embedding,
            'metadata': {
                'source_type': 'job',
                'company': job.get('company', ''),
                'title': job.get('title', ''),
                'domain_tags': json.dumps(job.get('domain_tags', [])),
                'skills': json.dumps(job.get('skills', [])),
                'responsibilities': json.dumps(job.get('responsibilities', [])),
                'job_url': job.get('job_url', ''),
                'seniority': job.get('seniority', ''),
                'location': job.get('location', ''),
                'period': '',
                'text_snippet': ''
            }
        }
    except Exception as e:
        print(f"[embeddings] Embed error for '{job.get('title')}': {e}")
        return None, None


def _embed_company_document(args):
    i, doc = args
    text = (
        f"Source type: {doc.get('source_type', '')}\n"
        f"Title: {doc.get('title', '')}\n"
        f"Company: {doc.get('company', '')}\n"
        f"Fiscal period: {doc.get('fiscal_period', '')}\n"
        f"Summary: {doc.get('summary_text', '')}\n"
        f"Signals: {json.dumps(doc.get('structured_signals', {}))}\n"
        f"Raw text: {doc.get('raw_text', '')[:4000]}"
    ).strip()

    doc_id = _make_doc_id(
        doc.get('source_type', 'quarterly'),
        doc.get('company', ''),
        doc.get('title', ''),
        i
    )

    try:
        embedding = _embed(text)
        return doc_id, {
            'embedding': embedding,
            'metadata': {
                'source_type': doc.get('source_type', 'company_document'),
                'company': doc.get('company', ''),
                'title': doc.get('title', ''),
                'domain_tags': json.dumps([]),
                'skills': json.dumps([]),
                'responsibilities': json.dumps([]),
                'job_url': doc.get('source_url', ''),
                'seniority': '',
                'location': '',
                'period': doc.get('fiscal_period', ''),
                'text_snippet': doc.get('summary_text', '')[:1000]
            }
        }
    except Exception as e:
        print(f"[embeddings] Embed error for company doc '{doc.get('title')}': {e}")
        return None, None


def add_jobs_to_index(jobs):
    index = _load_index()

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_embed_job, (i, job)) for i, job in enumerate(jobs)]
        for future in as_completed(futures):
            doc_id, entry = future.result()
            if doc_id:
                index[doc_id] = entry

    _save_index(index)
    print(f"[embeddings] Indexed {len(jobs)} jobs (total in index: {len(index)})")


def add_company_documents_to_index(documents):
    index = _load_index()

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(_embed_company_document, (i, doc)) for i, doc in enumerate(documents)]
        for future in as_completed(futures):
            doc_id, entry = future.result()
            if doc_id:
                index[doc_id] = entry

    _save_index(index)
    print(f"[embeddings] Indexed {len(documents)} company documents (total in index: {len(index)})")


def add_quarterly_documents_to_index(documents):
    return add_company_documents_to_index(documents)


def search_documents(query, company=None, n_results=8, source_types=None):
    index = _load_index()
    if not index:
        return []

    try:
        query_vec = np.array(_embed(query), dtype=np.float32)
    except Exception as e:
        print(f"[embeddings] Query embed error: {e}")
        return []

    results = []
    for doc_id, entry in index.items():
        meta = entry['metadata']
        if company and meta.get('company', '').lower() != company.lower():
            continue
        source_type = meta.get('source_type', 'job')
        if source_types and source_type not in source_types:
            continue

        doc_vec = np.array(entry['embedding'], dtype=np.float32)
        similarity = float(
            np.dot(query_vec, doc_vec) /
            (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec) + 1e-10)
        )
        results.append({
            'source_type': source_type,
            'title': meta.get('title', ''),
            'company': meta.get('company', ''),
            'domain_tags': json.loads(meta.get('domain_tags', '[]')),
            'skills': json.loads(meta.get('skills', '[]')),
            'responsibilities': json.loads(meta.get('responsibilities', '[]')),
            'job_url': meta.get('job_url', ''),
            'seniority': meta.get('seniority', ''),
            'period': meta.get('period', ''),
            'text_snippet': meta.get('text_snippet', ''),
            'relevance': round(similarity, 3)
        })

    results.sort(key=lambda x: x['relevance'], reverse=True)
    return results[:n_results]


def search_jobs(query, company=None, n_results=8):
    return search_documents(query, company=company, n_results=n_results, source_types={'job'})
