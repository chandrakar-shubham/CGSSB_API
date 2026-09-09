# CGSSB API

Production-oriented Python API and scraper for Chhattisgarh Vyapam/CGSSB public notices.

## Goals

- Query-driven scraping
- Normalized JSON suitable for downstream JOBS systems
- CGSSB categories: online applications, admit cards, results, model answers
- Duplicate/change detection hooks
- Hostinger-compatible deployment
- FastAPI/OpenAPI
- SQLite for local development; MySQL-compatible SQLAlchemy configuration for Hostinger

## Current source endpoints

- `https://vyapamcg.cgstate.gov.in/Posts?tag=ONLINEAPPLICATION`
- `https://vyapamcg.cgstate.gov.in/Posts?tag=ADMIT%20CARD`
- `https://vyapamcg.cgstate.gov.in/Post?PostID=RESULT`
- `https://vyapamcg.cgstate.gov.in/Posts?tag=MODEL%20ANSWERS`

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `/docs` for Swagger UI.

## API examples

```text
GET /api/v1/health
GET /api/v1/sources
GET /api/v1/query?category=online_application&keyword=teacher
POST /api/v1/scrape
GET /api/v1/scrape/{job_id}
```

## Important

The upstream site can be intermittently slow or unavailable. The connector uses explicit timeouts/retries and does not assume that an HTML response is always available. Parser selectors are isolated so they can be adjusted without changing the API contract.
