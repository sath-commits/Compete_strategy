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

    doc_id = (
        f"{job.get('company', 'x')}_{job.get('title', 'x')}_{i}"
        .replace(' ', '_').replace('/', '_')[:128]
    )

    try:
        embedding = _embed(text)
        return doc_id, {
            'embedding': embedding,
            'metadata': {
                'company': job.get('company', ''),
                'title': job.get('title', ''),
                'domain_tags': json.dumps(job.get('domain_tags', [])),
                'skills': json.dumps(job.get('skills', [])),
                'responsibilities': json.dumps(job.get('responsibilities', [])),
                'job_url': job.get('job_url', ''),
                'seniority': job.get('seniority', ''),
                'location': job.get('location', '')
            }
        }
    except Exception as e:
        print(f"[embeddings] Embed error for '{job.get('title')}': {e}")
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


def search_jobs(query, company=None, n_results=8):
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

        doc_vec = np.array(entry['embedding'], dtype=np.float32)
        similarity = float(
            np.dot(query_vec, doc_vec) /
            (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec) + 1e-10)
        )
        results.append({
            'title': meta.get('title', ''),
            'company': meta.get('company', ''),
            'domain_tags': json.loads(meta.get('domain_tags', '[]')),
            'skills': json.loads(meta.get('skills', '[]')),
            'responsibilities': json.loads(meta.get('responsibilities', '[]')),
            'job_url': meta.get('job_url', ''),
            'seniority': meta.get('seniority', ''),
            'relevance': round(similarity, 3)
        })

    results.sort(key=lambda x: x['relevance'], reverse=True)
    return results[:n_results]
