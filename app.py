from dotenv import load_dotenv
load_dotenv()  # Must run before any other import so API keys are available

import os
import threading
import time
import uuid
import functools
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template, request, jsonify, Response
from core.job_fetcher import fetch_jobs
from core.job_extractor import extract_and_classify_jobs
from core.embeddings import add_jobs_to_index, add_company_documents_to_index, get_index_count
from core.insight_engine import generate_insights
from core.trend_analyzer import compute_trends
from core.rag_answerer import answer_question
from core.public_company import resolve_public_company
from core.company_documents import fetch_company_documents
from db.db import (
    init_db, save_jobs, save_company_documents,
    get_cached_jobs, get_cache_info,
    log_api_call, get_api_usage,
    log_page_view, log_search, get_dashboard_data,
    get_all_jobs, get_all_company_documents, get_cached_company_documents,
    count_fresh_fetches_today, FRESH_FETCH_DAILY_LIMIT
)
from core.company_resolver import resolve_company, get_search_suggestions

app = Flask(__name__)

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'changeme')

# Hard cap on JSearch calls per month (200 free/month). Default 190 leaves a safety buffer.
# Each company search = 1 API call regardless of num_pages. Override with JSEARCH_LIMIT env var.
JSEARCH_MONTHLY_LIMIT = int(os.getenv('JSEARCH_LIMIT', '190'))

# ── Startup ────────────────────────────────────────────────────────────────────
# Runs when gunicorn imports this module (and when running locally).
# init_db() is safe to call multiple times — it only creates tables if missing.
# rebuild_chroma_if_needed() re-indexes jobs from SQLite if ChromaDB is empty
# (happens after every Render deploy since the filesystem resets).

def _rebuild_index_if_needed():
    try:
        count = get_index_count()
        if count == 0:
            all_jobs = get_all_jobs()
            company_docs = get_all_company_documents()
            if all_jobs or company_docs:
                print(
                    f"[startup] Embeddings index empty — rebuilding from "
                    f"{len(all_jobs)} jobs and {len(company_docs)} company docs in SQLite"
                )
                add_jobs_to_index(all_jobs)
                if company_docs:
                    add_company_documents_to_index(company_docs)
            else:
                print("[startup] Embeddings index empty, SQLite also empty — fresh start")
        else:
            print(f"[startup] Embeddings index has {count} documents — no rebuild needed")
    except Exception as e:
        print(f"[startup] Index rebuild skipped: {e}")


init_db()
_rebuild_index_if_needed()


# ── Admin auth ─────────────────────────────────────────────────────────────────

def _require_admin(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.password != ADMIN_PASSWORD:
            return Response(
                'Admin access required.',
                401,
                {'WWW-Authenticate': 'Basic realm="Admin"'}
            )
        return f(*args, **kwargs)
    return decorated


# ── Background job state ────────────────────────────────────────────────────────
_jobs = {}
_jobs_lock = threading.Lock()


def _make_source_status(company: str, public_company: dict, company_docs: list) -> dict:
    source_groups = sorted({doc.get('source_group', '') for doc in company_docs if doc.get('source_group')})
    source_counts = {}
    for doc in company_docs:
        source_type = doc.get('source_type', '')
        if source_type:
            source_counts[source_type] = source_counts.get(source_type, 0) + 1
    has_investor_docs = 'investor_relations' in source_groups

    if company_docs:
        source_parts = []
        if has_investor_docs:
            source_parts.append('investor materials')
        if 'official_news' in source_groups:
            source_parts.append('newsroom posts')
        if 'product_updates' in source_groups:
            source_parts.append('product updates')
        if 'github' in source_groups:
            source_parts.append('GitHub releases')

        return {
            'mode': 'mixed_sources',
            'is_public': bool(public_company.get('is_public')),
            'company': public_company.get('company', company) if public_company.get('is_public') else company,
            'ticker': public_company.get('ticker', ''),
            'doc_count': len(company_docs),
            'source_groups': source_groups,
            'source_counts': source_counts,
            'message': (
                "Insights combine hiring signals with official company materials"
                + (f" for {public_company.get('ticker', '')}" if public_company.get('ticker') else "")
                + (f", including {', '.join(source_parts)}." if source_parts else ".")
            )
        }

    if public_company.get('is_public'):
        return {
            'mode': 'public_jobs_only',
            'is_public': True,
            'company': public_company.get('company', company),
            'ticker': public_company.get('ticker', ''),
            'doc_count': 0,
            'source_groups': [],
            'source_counts': {},
            'message': (
                "This company appears to be public, but we could not retrieve official company materials right now. "
                "Showing hiring-based insights only."
            )
        }

    return {
        'mode': 'private_or_unknown_jobs_only',
        'is_public': False,
        'company': company,
        'ticker': '',
        'doc_count': 0,
        'source_groups': [],
        'source_counts': {},
        'message': (
            "No official public company materials were retrieved for this search. "
            "Showing hiring-based insights only."
        )
    }


def _load_or_fetch_company_docs(company: str, force_refresh: bool = False):
    public_company = resolve_public_company(company)
    if not force_refresh:
        cached_docs = get_cached_company_documents(company)
        if cached_docs:
            return public_company, cached_docs

    company_docs = fetch_company_documents(company, public_company)
    for doc in company_docs:
        doc['company'] = company
    if company_docs:
        save_company_documents(company_docs)
    return public_company, company_docs


def _run_analysis_job(job_id: str, company: str, ip: str):
    try:
        with ThreadPoolExecutor(max_workers=2) as prefetch_executor:
            jobs_future = prefetch_executor.submit(fetch_jobs, company)
            docs_future = prefetch_executor.submit(_load_or_fetch_company_docs, company, True)
            raw_jobs = jobs_future.result()

            if not raw_jobs:
                suggestions = get_search_suggestions(company)
                log_search(company, ip, from_cache=False, success=False, error_type='no_results')
                with _jobs_lock:
                    _jobs[job_id] = {
                        'status': 'error',
                        'error': f'No job postings found for "{company}".',
                        'suggestions': suggestions,
                        '_completed_at': time.time(),
                    }
                return

            log_api_call('jsearch', company=company, call_type='search')

            structured_jobs = extract_and_classify_jobs(raw_jobs, company)
            if not structured_jobs:
                log_search(company, ip, from_cache=False, success=False, error_type='extraction_failed')
                with _jobs_lock:
                    _jobs[job_id] = {
                        'status': 'error',
                        'error': 'Could not extract job data. Please try again.',
                        'suggestions': [],
                        '_completed_at': time.time(),
                    }
                return

            public_company, company_docs = docs_future.result()

        save_jobs(structured_jobs)
        source_status = _make_source_status(company, public_company, company_docs)

        # Embeddings are only needed for /chat — run them in the background
        # so they don't block insights/trends from completing.
        threading.Thread(
            target=add_jobs_to_index, args=(structured_jobs,), daemon=True
        ).start()
        if company_docs:
            threading.Thread(
                target=add_company_documents_to_index, args=(company_docs,), daemon=True
            ).start()

        # Insights and trends are independent — run them in parallel.
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_insights = ex.submit(generate_insights, company, structured_jobs, company_docs)
            f_trends = ex.submit(compute_trends, company, structured_jobs)
            insights = f_insights.result()
            trends = f_trends.result()

        log_search(company, ip, from_cache=False, success=True)

        with _jobs_lock:
            _jobs[job_id] = {
                'status': 'done',
                '_completed_at': time.time(),
                'result': {
                    'company': company,
                    'job_count': len(structured_jobs),
                    'from_cache': False,
                    'insights': insights,
                    'trends': trends,
                    'source_status': source_status,
                }
            }

    except Exception as e:
        print(f"[app] Background job {job_id} failed: {e}")
        log_search(company, ip, from_cache=False, success=False, error_type='exception')
        with _jobs_lock:
            _jobs[job_id] = {
                'status': 'error',
                'error': 'An unexpected error occurred. Please try again.',
                'suggestions': [],
                '_completed_at': time.time(),
            }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/ping')
def ping():
    return '', 204


@app.route('/')
def index():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    log_page_view(ip, request.referrer, request.headers.get('User-Agent', ''))
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json() or {}
    company = (data.get('company') or '').strip()
    force_refresh = data.get('force_refresh', False)
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)

    if not company:
        return jsonify({'error': 'Company name is required'}), 400

    if not force_refresh:
        structured_jobs = get_cached_jobs(company)
        if structured_jobs:
            print(f"[app] Cache hit for '{company}' — {len(structured_jobs)} jobs")
            log_search(company, ip, from_cache=True, success=True)
            public_company, company_docs = _load_or_fetch_company_docs(company, force_refresh=False)
            source_status = _make_source_status(company, public_company, company_docs)
            threading.Thread(
                target=add_jobs_to_index, args=(structured_jobs,), daemon=True
            ).start()
            if company_docs:
                threading.Thread(
                    target=add_company_documents_to_index, args=(company_docs,), daemon=True
                ).start()
            with ThreadPoolExecutor(max_workers=2) as ex:
                f_insights = ex.submit(generate_insights, company, structured_jobs, company_docs)
                f_trends = ex.submit(compute_trends, company, structured_jobs)
                insights = f_insights.result()
                trends = f_trends.result()
            return jsonify({
                'company': company,
                'job_count': len(structured_jobs),
                'from_cache': True,
                'insights': insights,
                'trends': trends,
                'source_status': source_status,
            })

    # ── Per-IP rate limit: 5 fresh fetches per 24 hours ───────────────────
    fresh_today = count_fresh_fetches_today(ip)
    if fresh_today >= FRESH_FETCH_DAILY_LIMIT:
        remaining_hint = 'Come back tomorrow, or search a company already analysed — those are always instant and free.'
        return jsonify({
            'error': f"You've used all {FRESH_FETCH_DAILY_LIMIT} free analyses for today. {remaining_hint}"
        }), 429

    # ── Circuit breaker ────────────────────────────────────────────────────
    usage = get_api_usage('jsearch')
    if usage['this_month'] >= JSEARCH_MONTHLY_LIMIT:
        return jsonify({
            'error': f'Monthly search limit reached. Fresh searches are paused until '
                     f'the 1st of next month. You can still search companies already analysed.'
        }), 429

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {'status': 'running'}

    thread = threading.Thread(target=_run_analysis_job, args=(job_id, company, ip), daemon=True)
    thread.start()

    return jsonify({'status': 'running', 'job_id': job_id})


@app.route('/status/<job_id>')
def job_status(job_id):
    with _jobs_lock:
        raw = _jobs.get(job_id)
        # Snapshot inside the lock so reads outside are thread-safe
        job = dict(raw) if raw is not None else None
        # Lazy cleanup: evict completed entries after 5-minute window
        if job and job.get('status') in ('done', 'error'):
            if time.time() - job.get('_completed_at', time.time()) > 300:
                _jobs.pop(job_id, None)

    if not job:
        return jsonify({'status': 'not_found'}), 404

    if job['status'] == 'done':
        return jsonify({'status': 'done', **job['result']})

    if job['status'] == 'error':
        return jsonify({
            'status': 'error',
            'error': job.get('error', 'Unknown error'),
            'suggestions': job.get('suggestions', [])
        })

    return jsonify({'status': 'running'})


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    question = (data.get('question') or '').strip()
    company = (data.get('company') or '').strip() or None
    history = data.get('history') or []

    if not question:
        return jsonify({'error': 'Question is required'}), 400

    try:
        result = answer_question(question, company, history)
    except Exception as e:
        print(f"[chat] Unhandled error: {e}")
        result = {'answer': 'Something went wrong. Please try again.', 'evidence': []}
    return jsonify(result)


@app.route('/resolve', methods=['POST'])
def resolve():
    data = request.get_json() or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({'status': 'unknown'}), 400
    result = resolve_company(query)
    return jsonify(result)


@app.route('/admin')
@_require_admin
def admin():
    return render_template('dashboard.html')


@app.route('/admin/data')
@_require_admin
def admin_data():
    return jsonify(get_dashboard_data())


if __name__ == '__main__':
    print("Starting server at http://127.0.0.1:5000")
    print("Admin dashboard at http://127.0.0.1:5000/admin")
    app.run(debug=True, port=5000)
