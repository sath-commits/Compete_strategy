from dotenv import load_dotenv
load_dotenv()  # Must run before any other import so API keys are available

import os
import threading
import uuid
import functools

from flask import Flask, render_template, request, jsonify, Response
from core.job_fetcher import fetch_jobs
from core.job_extractor import extract_and_classify_jobs
from core.embeddings import add_jobs_to_index, get_index_count
from core.insight_engine import generate_insights
from core.trend_analyzer import compute_trends
from core.rag_answerer import answer_question
from db.db import (
    init_db, save_jobs,
    get_cached_jobs, get_cache_info,
    log_api_call, get_api_usage,
    log_page_view, log_search, get_dashboard_data,
    get_all_jobs
)
from core.company_resolver import resolve_company, get_search_suggestions

app = Flask(__name__)

ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'changeme')

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
            if all_jobs:
                print(f"[startup] Embeddings index empty — rebuilding from {len(all_jobs)} jobs in SQLite")
                add_jobs_to_index(all_jobs)
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


def _run_analysis_job(job_id: str, company: str, ip: str):
    try:
        raw_jobs = fetch_jobs(company)

        if not raw_jobs:
            suggestions = get_search_suggestions(company)
            log_search(company, ip, from_cache=False, success=False, error_type='no_results')
            with _jobs_lock:
                _jobs[job_id] = {
                    'status': 'error',
                    'error': f'No job postings found for "{company}".',
                    'suggestions': suggestions
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
                    'suggestions': []
                }
            return

        save_jobs(structured_jobs)
        add_jobs_to_index(structured_jobs)

        insights = generate_insights(company, structured_jobs)
        trends = compute_trends(company, structured_jobs)

        log_search(company, ip, from_cache=False, success=True)

        with _jobs_lock:
            _jobs[job_id] = {
                'status': 'done',
                'result': {
                    'company': company,
                    'job_count': len(structured_jobs),
                    'from_cache': False,
                    'insights': insights,
                    'trends': trends,
                }
            }

    except Exception as e:
        print(f"[app] Background job {job_id} failed: {e}")
        log_search(company, ip, from_cache=False, success=False, error_type='exception')
        with _jobs_lock:
            _jobs[job_id] = {
                'status': 'error',
                'error': 'An unexpected error occurred. Please try again.',
                'suggestions': []
            }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    log_page_view(ip, request.referrer, request.headers.get('User-Agent', ''))
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
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
            insights = generate_insights(company, structured_jobs)
            trends = compute_trends(company, structured_jobs)
            return jsonify({
                'company': company,
                'job_count': len(structured_jobs),
                'from_cache': True,
                'insights': insights,
                'trends': trends,
            })

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {'status': 'running'}

    thread = threading.Thread(target=_run_analysis_job, args=(job_id, company, ip), daemon=True)
    thread.start()

    return jsonify({'status': 'running', 'job_id': job_id})


@app.route('/status/<job_id>')
def job_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)

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
    data = request.get_json()
    question = (data.get('question') or '').strip()
    company = (data.get('company') or '').strip() or None
    history = data.get('history') or []

    if not question:
        return jsonify({'error': 'Question is required'}), 400

    result = answer_question(question, company, history)
    return jsonify(result)


@app.route('/resolve', methods=['POST'])
def resolve():
    data = request.get_json()
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
