from core.company_documents import fetch_company_documents


def fetch_quarterly_documents(public_company: dict) -> list:
    company = public_company.get("company", "")
    return [
        doc for doc in fetch_company_documents(company, public_company)
        if doc.get("source_group") == "investor_relations"
    ]
