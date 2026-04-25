from collections import Counter


def compute_trends(company, jobs):
    """Compute domain distribution, top skills, and seniority breakdown from structured jobs."""
    domain_counts = Counter()
    skill_counts = Counter()
    seniority_counts = Counter()
    tagged_jobs = 0
    untagged_jobs = 0

    for job in jobs:
        domain_tags = job.get('domain_tags', [])
        if domain_tags:
            tagged_jobs += 1
        else:
            untagged_jobs += 1

        for tag in domain_tags:
            domain_counts[tag] += 1
        for skill in job.get('skills', []):
            skill_counts[skill] += 1
        seniority = job.get('seniority', '').strip()
        if seniority:
            seniority_counts[seniority] += 1

    return {
        'company': company,
        'total_jobs': len(jobs),
        'tagged_jobs': tagged_jobs,
        'untagged_jobs': untagged_jobs,
        'domain_coverage_pct': round((tagged_jobs / len(jobs)) * 100) if jobs else 0,
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
