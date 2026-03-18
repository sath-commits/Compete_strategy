import json
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Common variations handled without any LLM call — instant and free
KNOWN_ALIASES = {
    'openai':       'OpenAI',
    'open ai':      'OpenAI',
    'open-ai':      'OpenAI',
    'anthropic':    'Anthropic',
    'deepmind':     'Google DeepMind',
    'deep mind':    'Google DeepMind',
    'google':       'Google',
    'meta':         'Meta',
    'facebook':     'Meta',
    'msft':         'Microsoft',
    'microsoft':    'Microsoft',
    'amazon':       'Amazon',
    'aws':          'Amazon Web Services',
    'apple':        'Apple',
    'netflix':      'Netflix',
    'uber':         'Uber',
    'airbnb':       'Airbnb',
    'stripe':       'Stripe',
    'salesforce':   'Salesforce',
    'mistral':      'Mistral AI',
    'mistralai':    'Mistral AI',
    'cohere':       'Cohere',
    'huggingface':  'Hugging Face',
    'hugging face': 'Hugging Face',
}

RESOLVE_PROMPT = """You are a company name resolver. The user typed "{query}" into a competitive intelligence tool.

Your job:
1. Decide if this is a clear company name, an ambiguous abbreviation, or a typo/variation.
2. Return a JSON object with this structure:

{{
  "status": "clear" | "ambiguous" | "unknown",
  "canonical": "The most likely full official company name, or empty string if unknown",
  "alternatives": [
    {{"name": "Full official company name", "description": "one line description e.g. 'Singapore-based bank'"}},
    ...
  ]
}}

Rules:
- "clear": you are confident what company they mean. Set canonical to the official name. alternatives can be empty.
- "ambiguous": the query could mean 2 or more distinct well-known companies. Set canonical to empty string. List all plausible options in alternatives (max 4).
- "unknown": you have no idea what company this refers to. Set canonical to empty string, alternatives to empty list.

Examples:
- "dbs" → ambiguous (DBS Bank Singapore, DBS Technologies, etc.)
- "openai" → clear, canonical = "OpenAI"
- "open ai" → clear, canonical = "OpenAI"
- "goog" → clear, canonical = "Google"
- "ms" → ambiguous (Microsoft, Morgan Stanley)
- "xyz123corp" → unknown

Return only valid JSON."""


def get_search_suggestions(company: str) -> list:
    """
    When a search returns no results, return simpler name variants to try.
    No AI call needed — we just apply simple rules:
    1. Try each individual word (e.g. "DBS Bank" → ["DBS", "Bank"])
    2. Try without common suffixes (Inc, Ltd, Corp, Group, Bank, Technologies…)
    This covers 90% of cases instantly and for free.
    """
    words = company.strip().split()
    suggestions = []

    # Rule 1: if multi-word, suggest the first word alone (usually the brand name)
    if len(words) > 1:
        suggestions.append(words[0])

    # Rule 2: strip common corporate suffixes and suggest the remainder
    suffixes = {'inc', 'ltd', 'llc', 'corp', 'corporation', 'group',
                'bank', 'technologies', 'technology', 'solutions',
                'services', 'holdings', 'co', 'company', 'ai', 'labs'}
    filtered = [w for w in words if w.lower() not in suffixes]
    if filtered and ' '.join(filtered).lower() != company.lower() and filtered != [words[0]]:
        suggestions.append(' '.join(filtered))

    # Deduplicate while preserving order
    seen = set()
    result = []
    for s in suggestions:
        if s.lower() not in seen and s.lower() != company.lower():
            seen.add(s.lower())
            result.append(s)

    return result[:3]


def resolve_company(query: str) -> dict:
    """
    Given a raw user query, return either:
    - {status: 'clear', canonical: 'OpenAI'} — proceed with analysis
    - {status: 'ambiguous', alternatives: [...]} — ask user to pick
    - {status: 'unknown'} — show helpful error

    We first check a local alias table (free, instant).
    Only if not found do we call the LLM (small, cheap call).
    """
    normalized = query.strip().lower()

    # Fast path: check known aliases first
    if normalized in KNOWN_ALIASES:
        return {
            'status': 'clear',
            'canonical': KNOWN_ALIASES[normalized],
            'alternatives': []
        }

    # Slow path: ask GPT to resolve
    try:
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': RESOLVE_PROMPT.format(query=query)}],
            response_format={'type': 'json_object'},
            temperature=0
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"[company_resolver] Error: {e}")
        # Fallback: treat as clear with the raw query
        return {
            'status': 'clear',
            'canonical': query.strip().title(),
            'alternatives': []
        }
