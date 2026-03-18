"""
Evaluation script for the competitive intelligence RAG system.

Usage:
    python eval/evaluate.py

Requires at least one company to have been analyzed first (so ChromaDB has data).
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.embeddings import search_jobs
from core.rag_answerer import answer_question


def load_questions():
    path = os.path.join(os.path.dirname(__file__), 'test_questions.json')
    with open(path) as f:
        return json.load(f)


def retrieval_metrics(retrieved_jobs, expected_domains):
    """Compute precision and recall over domain tags."""
    retrieved_domains = set()
    for job in retrieved_jobs:
        retrieved_domains.update(job.get('domain_tags', []))

    expected = set(expected_domains)

    precision = len(retrieved_domains & expected) / len(retrieved_domains) if retrieved_domains else 0.0
    recall    = len(retrieved_domains & expected) / len(expected) if expected else 1.0

    return round(precision, 2), round(recall, 2)


def keyword_coverage(answer_text, expected_keywords):
    """Fraction of expected keywords that appear in the answer (case-insensitive)."""
    if not expected_keywords:
        return 1.0
    lower = answer_text.lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in lower)
    return round(found / len(expected_keywords), 2)


def hallucination_flag(answer_text, retrieved_jobs):
    """
    Simple heuristic: if the answer is substantial but none of the retrieved
    job titles appear in it, flag as a potential hallucination.
    """
    if len(answer_text) < 150:
        return False
    titles = [j['title'].lower() for j in retrieved_jobs]
    return not any(t in answer_text.lower() for t in titles)


def run():
    questions = load_questions()
    results = []

    print("=" * 60)
    print("CompeteIQ — Evaluation Run")
    print("=" * 60)

    for q in questions:
        print(f"\nQ{q['id']}: {q['question']}")

        retrieved = search_jobs(q['question'], n_results=8)
        result    = answer_question(q['question'], company=None, history=[])

        answer   = result.get('answer', '')
        evidence = result.get('evidence', [])

        prec, rec = retrieval_metrics(retrieved, q['expected_domains'])
        kw_cov    = keyword_coverage(answer, q['expected_keywords'])
        halluc    = hallucination_flag(answer, retrieved)

        print(f"  Retrieval precision : {prec:.2f}")
        print(f"  Retrieval recall    : {rec:.2f}")
        print(f"  Keyword coverage    : {kw_cov:.0%}")
        print(f"  Hallucination flag  : {'⚠️  YES' if halluc else 'OK'}")
        print(f"  Evidence count      : {len(evidence)}")

        results.append({
            'id'                  : q['id'],
            'question'            : q['question'],
            'retrieval_precision' : prec,
            'retrieval_recall'    : rec,
            'keyword_coverage'    : kw_cov,
            'hallucination_flag'  : halluc,
            'answer_length'       : len(answer),
            'evidence_count'      : len(evidence)
        })

    # Summary
    n = len(results)
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Avg retrieval precision : {sum(r['retrieval_precision'] for r in results)/n:.2f}")
    print(f"Avg retrieval recall    : {sum(r['retrieval_recall'] for r in results)/n:.2f}")
    print(f"Avg keyword coverage    : {sum(r['keyword_coverage'] for r in results)/n:.0%}")
    print(f"Hallucination flags     : {sum(1 for r in results if r['hallucination_flag'])}/{n}")

    out_path = os.path.join(os.path.dirname(__file__), 'eval_results.json')
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results saved to: {out_path}")


if __name__ == '__main__':
    run()
