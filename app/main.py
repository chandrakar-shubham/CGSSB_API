from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query

from app.core.config import get_settings
from app.schemas import Category, QueryResponse, ScrapeJob, ScrapeRequest, Source
from app.scrapers.cg_vyapam import CGVyapamScraper

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", description="Query-driven CG Vyapam/CGSSB scraping API")
scraper = CGVyapamScraper()

_jobs: dict[str, ScrapeJob] = {}
_cache: list = []


@app.get("/", tags=["system"])
def root():
    return {"name": settings.app_name, "version": app.version, "docs": "/docs"}


@app.get(f"{settings.api_prefix}/health", tags=["system"])
def health():
    return {"success": True, "status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get(f"{settings.api_prefix}/sources", tags=["system"])
def sources():
    return {
        "success": True,
        "sources": [
            {"id": Source.cg_vyapam.value, "name": "CG Vyapam", "categories": [c.value for c in Category if c != Category.all]}
        ],
    }


@app.get(f"{settings.api_prefix}/query", response_model=QueryResponse, tags=["query"])
def query(
    category: Category = Category.all,
    keyword: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=500),
):
    items = list(_cache)
    if category != Category.all:
        items = [x for x in items if x.category == category.value]
    if keyword:
        needle = keyword.casefold()
        items = [x for x in items if needle in x.title.casefold() or needle in (x.content or "").casefold()]
    return QueryResponse(total=len(items[:limit]), items=items[:limit])


@app.post(f"{settings.api_prefix}/scrape", response_model=ScrapeJob, tags=["scrape"])
def scrape(request: ScrapeRequest):
    job_id = f"scr_{uuid4().hex[:16]}"
    job = ScrapeJob(job_id=job_id, status="running", created_at=datetime.now(timezone.utc), source=request.source, category=request.category)
    _jobs[job_id] = job
    try:
        results = scraper.scrape(request.category, request.keyword, request.limit)
        _cache[:] = results
        job.status = "completed"
    except Exception as exc:
        job.status = f"failed: {type(exc).__name__}"
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return job


@app.get(f"{settings.api_prefix}/scrape/{{job_id}}", response_model=ScrapeJob, tags=["scrape"])
def scrape_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scrape job not found")
    return job
