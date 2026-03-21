import chromadb
import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
CHROMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'chroma')


def _get_collection():
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    return chroma_client.get_or_create_collection(
        name="jobs",
        metadata={"hnsw:space": "cosine"}
    )


def _embed(text):
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text[:8000]
    )
    return response.data[0].embedding


def add_jobs_to_index(jobs):
    """Embed structured jobs and store in ChromaDB."""
    collection = _get_collection()

    for i, job in enumerate(jobs):
        text = (
            f"Title: {job.get('title', '')}\n"
            f"Company: {job.get('company', '')}\n"
            f"Team: {job.get('team', '')}\n"
            f"Domains: {', '.join(job.get('domain_tags', []))}\n"
            f"Skills: {', '.join(job.get('skills', []))}\n"
            f"Responsibilities: {'. '.join(job.get('responsibilities', []))}\n"
            f"Experience: {job.get('experience', '')}"
        ).strip()

        try:
            embedding = _embed(text)
        except Exception as e:
            print(f"[embeddings] Embed error for '{job.get('title')}': {e}")
            continue

        doc_id = (
            f"{job.get('company', 'x')}_{job.get('title', 'x')}_{i}"
            .replace(' ', '_')
            .replace('/', '_')[:128]
        )

        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                'company': job.get('company', ''),
                'title': job.get('title', ''),
                'domain_tags': json.dumps(job.get('domain_tags', [])),
                'skills': json.dumps(job.get('skills', [])),
                'responsibilities': json.dumps(job.get('responsibilities', [])),
                'job_url': job.get('job_url', ''),
                'seniority': job.get('seniority', ''),
                'location': job.get('location', '')
            }]
        )

    print(f"[embeddings] Indexed {len(jobs)} jobs into ChromaDB")


def search_jobs(query, company=None, n_results=8):
    """Search ChromaDB for jobs relevant to a query, optionally filtered by company."""
    collection = _get_collection()

    try:
        query_embedding = _embed(query)
    except Exception as e:
        print(f"[embeddings] Query embed error: {e}")
        return []

    where = {"company": {"$eq": company}} if company else None

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"]
        )
    except Exception as e:
        print(f"[embeddings] ChromaDB query error: {e}")
        return []

    jobs = []
    for idx in range(len(results['ids'][0])):
        meta = results['metadatas'][0][idx]
        jobs.append({
            'title': meta.get('title', ''),
            'company': meta.get('company', ''),
            'domain_tags': json.loads(meta.get('domain_tags', '[]')),
            'skills': json.loads(meta.get('skills', '[]')),
            'responsibilities': json.loads(meta.get('responsibilities', '[]')),
            'job_url': meta.get('job_url', ''),
            'seniority': meta.get('seniority', ''),
            'relevance': round(1 - results['distances'][0][idx], 3)
        })

    return jobs
