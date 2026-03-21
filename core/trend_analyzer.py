from collections import Counter


def compute_trends(company, jobs):
    """Compute domain distribution, top skills, and seniority breakdown from structured jobs."""
    domain_counts = Counter()
    skill_counts = Counter()
    seniority_counts = Counter()

    for job in jobs:
        for tag in job.get('domain_tags', []):
            domain_counts[tag] += 1
        for skill in job.get('skills', []):
            skill_counts[skill] += 1
        seniority = job.get('seniority', '').strip()
        if seniority:
            seniority_counts[seniority] += 1

    return {
        'company': company,
        'total_jobs': len(jobs),
        'domain_distribution': [
            {'domain': k.replace('_', ' ').title(), 'count': v}
            for k, v in sorted(domain_counts.items(), key=lambda x: -x[1])
        ],
        'top_skills': [
            {'skill': k, 'count': v}
            for k, v in skill_counts.most_common(15)
        ],
        'seniority_distribution': [
            {'level': k.title(), 'count': v}
            for k, v in seniority_counts.most_common()
        ]
    }
