import sqlite3
import json
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'intelligence.db')

CACHE_TTL_DAYS = 7  # cached jobs are considered fresh for 7 days


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()

    conn.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            title TEXT,
            team TEXT,
            seniority TEXT,
            domain_tags TEXT,
            skills TEXT,
            responsibilities TEXT,
            experience TEXT,
            location TEXT,
            raw_description TEXT,
            job_url TEXT,
            date_fetched TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            domain TEXT,
            insight_text TEXT,
            evidence TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service TEXT NOT NULL,
            company TEXT,
            call_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS page_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT,
            referrer TEXT,
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            ip TEXT,
            from_cache INTEGER DEFAULT 0,
            success INTEGER DEFAULT 1,
            error_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    # Migrate: add richer signal columns to jobs if they don't exist yet
    new_columns = ['metrics', 'tools_platforms', 'team_names', 'business_goals']
    for col in new_columns:
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT DEFAULT '[]'")
        except Exception:
            pass  # column already exists — safe to ignore

    conn.commit()
    conn.close()


# ── Analytics tracking ─────────────────────────────────────────────────────────

def log_page_view(ip, referrer='', user_agent=''):
    conn = get_conn()
    conn.execute(
        'INSERT INTO page_views (ip, referrer, user_agent) VALUES (?, ?, ?)',
        (ip or '', referrer or '', user_agent or '')
    )
    conn.commit()
    conn.close()


def log_search(company, ip='', from_cache=False, success=True, error_type=None):
    conn = get_conn()
    conn.execute(
        'INSERT INTO searches (company, ip, from_cache, success, error_type) VALUES (?, ?, ?, ?, ?)',
        (company, ip or '', int(from_cache), int(success), error_type)
    )
    conn.commit()
    conn.close()


def get_dashboard_data():
    """Return all analytics data for the admin dashboard."""
    conn = get_conn()

    today = datetime.now().strftime('%Y-%m-%d')
    this_month = datetime.now().strftime('%Y-%m')

    # ── Page views ──────────────────────────────────────────────────────────
    total_views = conn.execute('SELECT COUNT(*) as n FROM page_views').fetchone()['n']
    views_today = conn.execute(
        "SELECT COUNT(*) as n FROM page_views WHERE date(created_at) = ?", (today,)
    ).fetchone()['n']
    unique_visitors = conn.execute(
        'SELECT COUNT(DISTINCT ip) as n FROM page_views'
    ).fetchone()['n']
    unique_today = conn.execute(
        "SELECT COUNT(DISTINCT ip) as n FROM page_views WHERE date(created_at) = ?", (today,)
    ).fetchone()['n']

    # ── Searches ────────────────────────────────────────────────────────────
    total_searches = conn.execute('SELECT COUNT(*) as n FROM searches').fetchone()['n']
    searches_today = conn.execute(
        "SELECT COUNT(*) as n FROM searches WHERE date(created_at) = ?", (today,)
    ).fetchone()['n']
    cache_hits = conn.execute(
        'SELECT COUNT(*) as n FROM searches WHERE from_cache = 1'
    ).fetchone()['n']
    fresh_fetches = conn.execute(
        'SELECT COUNT(*) as n FROM searches WHERE from_cache = 0 AND success = 1'
    ).fetchone()['n']
    failed_searches = conn.execute(
        'SELECT COUNT(*) as n FROM searches WHERE success = 0'
    ).fetchone()['n']

    # ── Top companies ───────────────────────────────────────────────────────
    top_companies = conn.execute('''
        SELECT company, COUNT(*) as count
        FROM searches WHERE success = 1
        GROUP BY LOWER(company)
        ORDER BY count DESC LIMIT 10
    ''').fetchall()

    # ── Activity over last 14 days ──────────────────────────────────────────
    cutoff = (datetime.now() - timedelta(days=13)).strftime('%Y-%m-%d')
    daily_views = conn.execute('''
        SELECT date(created_at) as day, COUNT(*) as count
        FROM page_views WHERE date(created_at) >= ?
        GROUP BY day ORDER BY day
    ''', (cutoff,)).fetchall()
    daily_searches = conn.execute('''
        SELECT date(created_at) as day, COUNT(*) as count
        FROM searches WHERE date(created_at) >= ?
        GROUP BY day ORDER BY day
    ''', (cutoff,)).fetchall()

    # ── Recent searches ─────────────────────────────────────────────────────
    recent = conn.execute('''
        SELECT company, ip, from_cache, success, error_type, created_at
        FROM searches ORDER BY created_at DESC LIMIT 25
    ''').fetchall()

    # ── API usage ───────────────────────────────────────────────────────────
    api_total = conn.execute(
        "SELECT COUNT(*) as n FROM api_usage WHERE service = 'jsearch'"
    ).fetchone()['n']
    api_this_month = conn.execute(
        "SELECT COUNT(*) as n FROM api_usage WHERE service = 'jsearch' "
        "AND strftime('%Y-%m', created_at) = ?", (this_month,)
    ).fetchone()['n']

    # ── Referrers ───────────────────────────────────────────────────────────
    top_referrers = conn.execute('''
        SELECT referrer, COUNT(*) as count
        FROM page_views WHERE referrer != '' AND referrer IS NOT NULL
        GROUP BY referrer ORDER BY count DESC LIMIT 8
    ''').fetchall()

    conn.close()

    return {
        'page_views': {
            'total': total_views,
            'today': views_today,
            'unique_visitors': unique_visitors,
            'unique_today': unique_today,
        },
        'searches': {
            'total': total_searches,
            'today': searches_today,
            'cache_hits': cache_hits,
            'fresh_fetches': fresh_fetches,
            'failed': failed_searches,
        },
        'api': {
            'total': api_total,
            'this_month': api_this_month,
            'remaining': max(0, 200 - api_this_month),
        },
        'top_companies': [{'company': r['company'], 'count': r['count']} for r in top_companies],
        'top_referrers': [{'referrer': r['referrer'], 'count': r['count']} for r in top_referrers],
        'daily_views': [{'day': r['day'], 'count': r['count']} for r in daily_views],
        'daily_searches': [{'day': r['day'], 'count': r['count']} for r in daily_searches],
        'recent_searches': [
            {
                'company': r['company'],
                'ip': r['ip'],
                'from_cache': bool(r['from_cache']),
                'success': bool(r['success']),
                'error_type': r['error_type'],
                'created_at': r['created_at'],
            } for r in recent
        ],
    }


# ── API usage tracking ─────────────────────────────────────────────────────────

def log_api_call(service, company='', call_type='search'):
    conn = get_conn()
    conn.execute(
        'INSERT INTO api_usage (service, company, call_type) VALUES (?, ?, ?)',
        (service, company, call_type)
    )
    conn.commit()
    conn.close()


def get_api_usage(service='jsearch'):
    conn = get_conn()
    total = conn.execute(
        'SELECT COUNT(*) as n FROM api_usage WHERE service = ?', (service,)
    ).fetchone()['n']
    this_month = conn.execute(
        "SELECT COUNT(*) as n FROM api_usage WHERE service = ? "
        "AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')",
        (service,)
    ).fetchone()['n']
    conn.close()
    return {'total': total, 'this_month': this_month}


# ── Caching ────────────────────────────────────────────────────────────────────

def get_cached_jobs(company):
    cutoff = (datetime.now() - timedelta(days=CACHE_TTL_DAYS)).strftime('%Y-%m-%d')
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM jobs WHERE LOWER(company) = LOWER(?) AND date_fetched >= ?',
        (company, cutoff)
    ).fetchall()
    conn.close()
    return [_parse_job_row(dict(row)) for row in rows]


def get_cache_info(company):
    conn = get_conn()
    row = conn.execute(
        'SELECT date_fetched, COUNT(*) as count FROM jobs '
        'WHERE LOWER(company) = LOWER(?) GROUP BY date_fetched ORDER BY date_fetched DESC LIMIT 1',
        (company,)
    ).fetchone()
    conn.close()
    if row:
        return {'date_fetched': row['date_fetched'], 'count': row['count']}
    return None


# ── Jobs ───────────────────────────────────────────────────────────────────────

def save_jobs(jobs):
    conn = get_conn()
    today = datetime.now().strftime('%Y-%m-%d')
    for job in jobs:
        conn.execute('''
            INSERT INTO jobs (company, title, team, seniority, domain_tags, skills,
                             responsibilities, experience, location, raw_description,
                             job_url, date_fetched, metrics, tools_platforms,
                             team_names, business_goals)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            job.get('company', ''),
            job.get('title', ''),
            job.get('team', ''),
            job.get('seniority', ''),
            json.dumps(job.get('domain_tags', [])),
            json.dumps(job.get('skills', [])),
            json.dumps(job.get('responsibilities', [])),
            job.get('experience', ''),
            job.get('location', ''),
            job.get('raw_description', ''),
            job.get('job_url', ''),
            today,
            json.dumps(job.get('metrics', [])),
            json.dumps(job.get('tools_platforms', [])),
            json.dumps(job.get('team_names', [])),
            json.dumps(job.get('business_goals', [])),
        ))
    conn.commit()
    conn.close()


def get_all_jobs():
    """Return every job in the DB — used to rebuild ChromaDB index after a cold start."""
    conn = get_conn()
    rows = conn.execute('SELECT * FROM jobs').fetchall()
    conn.close()
    return [_parse_job_row(dict(row)) for row in rows]


def get_jobs_by_company(company):
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM jobs WHERE LOWER(company) = LOWER(?)', (company,)
    ).fetchall()
    conn.close()
    return [_parse_job_row(dict(row)) for row in rows]


def _parse_job_row(row):
    for col in ['domain_tags', 'skills', 'responsibilities',
                'metrics', 'tools_platforms', 'team_names', 'business_goals']:
        row[col] = json.loads(row.get(col) or '[]')
    return row


# ── Insights ───────────────────────────────────────────────────────────────────

def save_insights(insights):
    conn = get_conn()
    if insights:
        company = insights[0].get('company', '')
        conn.execute('DELETE FROM insights WHERE LOWER(company) = LOWER(?)', (company,))
    for ins in insights:
        conn.execute(
            'INSERT INTO insights (company, domain, insight_text, evidence) VALUES (?, ?, ?, ?)',
            (ins.get('company', ''), ins.get('domain', ''),
             ins.get('insight_text', ''), json.dumps(ins.get('evidence', [])))
        )
    conn.commit()
    conn.close()


def get_insights(company):
    conn = get_conn()
    rows = conn.execute(
        'SELECT * FROM insights WHERE LOWER(company) = LOWER(?) ORDER BY created_at DESC',
        (company,)
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        i = dict(row)
        i['evidence'] = json.loads(i['evidence'] or '[]')
        results.append(i)
    return results
