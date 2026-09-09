import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database import get_db, init_db
from app.models import ScrapedItemModel, ScrapeRunModel
from app.schemas import Category, QueryResponse, ScrapeJob, ScrapeRequest, ScrapedItem, Source
from app.scrapers.cg_vyapam import CGVyapamScraper

settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Query-driven CG Vyapam/CGSSB scraping API",
)
scraper = CGVyapamScraper()


@app.on_event("startup")
def startup() -> None:
    init_db()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Protect scrape operations when API_KEY is configured; stay convenient locally when unset."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def to_schema(item: ScrapedItemModel) -> ScrapedItem:
    try:
        raw = json.loads(item.raw_json or "{}")
    except json.JSONDecodeError:
        raw = {}
    return ScrapedItem(
        id=item.id,
        source=item.source,
        category=item.category,
        title=item.title,
        published_date=item.published_date,
        source_url=item.source_url,
        notification_url=item.notification_url,
        application_url=item.application_url,
        content=item.content,
        raw=raw,
    )


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
            {
                "id": Source.cg_vyapam.value,
                "name": "CG Vyapam",
                "categories": [c.value for c in Category if c != Category.all],
            }
        ],
    }


@app.get(f"{settings.api_prefix}/query", response_model=QueryResponse, tags=["query"])
def query(
    category: Category = Category.all,
    keyword: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(ScrapedItemModel).order_by(ScrapedItemModel.last_seen_at.desc()).limit(limit)
    if category != Category.all:
        stmt = stmt.where(ScrapedItemModel.category == category.value)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(
            (ScrapedItemModel.title.ilike(pattern))
            | (ScrapedItemModel.content.ilike(pattern))
        )
    items = list(db.scalars(stmt))
    return QueryResponse(total=len(items), items=[to_schema(item) for item in items])


@app.post(
    f"{settings.api_prefix}/scrape",
    response_model=ScrapeJob,
    tags=["scrape"],
    dependencies=[Depends(require_api_key)],
)
def scrape(request: ScrapeRequest, db: Session = Depends(get_db)):
    job_id = f"scr_{uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)
    run = ScrapeRunModel(
        job_id=job_id,
        source=request.source.value,
        category=request.category.value,
        status="running",
        created_at=now,
    )
    db.add(run)
    db.commit()

    try:
        results = scraper.scrape(request.category, request.keyword, request.limit)
        run.discovered = len(results)

        for result in results:
            payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
            raw_json = json.dumps(payload.get("raw", {}), ensure_ascii=False, sort_keys=True)
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "category": payload.get("category"),
                        "title": payload.get("title"),
                        "published_date": payload.get("published_date"),
                        "notification_url": payload.get("notification_url"),
                        "application_url": payload.get("application_url"),
                        "content": payload.get("content"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()

            existing = db.get(ScrapedItemModel, payload["id"])
            if existing is None:
                db.add(
                    ScrapedItemModel(
                        id=payload["id"],
                        source=payload["source"],
                        category=payload["category"],
                        title=payload["title"],
                        published_date=payload.get("published_date"),
                        source_url=payload.get("source_url"),
                        notification_url=payload.get("notification_url"),
                        application_url=payload.get("application_url"),
                        content=payload.get("content"),
                        raw_json=raw_json,
                        content_hash=fingerprint,
                    )
                )
                run.new_items += 1
            elif existing.content_hash != fingerprint:
                existing.source = payload["source"]
                existing.category = payload["category"]
                existing.title = payload["title"]
                existing.published_date = payload.get("published_date")
                existing.source_url = payload.get("source_url")
                existing.notification_url = payload.get("notification_url")
                existing.application_url = payload.get("application_url")
                existing.content = payload.get("content")
                existing.raw_json = raw_json
                existing.content_hash = fingerprint
                existing.last_seen_at = now
                run.updated_items += 1
            else:
                existing.last_seen_at = now
                run.unchanged_items += 1

        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_run = db.get(ScrapeRunModel, job_id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.error = str(exc)[:4000]
            failed_run.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise HTTPException(status_code=502, detail="Scrape failed") from exc

    return ScrapeJob(
        job_id=job_id,
        status=run.status,
        created_at=run.created_at,
        source=Source(run.source),
        category=Category(run.category),
        discovered=run.discovered,
        new_items=run.new_items,
        updated_items=run.updated_items,
        unchanged_items=run.unchanged_items,
        failed=run.failed,
        finished_at=run.finished_at,
        error=run.error,
    )


@app.get(f"{settings.api_prefix}/scrape/{{job_id}}", response_model=ScrapeJob, tags=["scrape"])
def scrape_status(job_id: str, db: Session = Depends(get_db)):
    run = db.get(ScrapeRunModel, job_id)
    if not run:
        raise HTTPException(status_code=404, detail="Scrape job not found")
    return ScrapeJob(
        job_id=run.job_id,
        status=run.status,
        created_at=run.created_at,
        source=Source(run.source),
        category=Category(run.category),
        discovered=run.discovered,
        new_items=run.new_items,
        updated_items=run.updated_items,
        unchanged_items=run.unchanged_items,
        failed=run.failed,
        finished_at=run.finished_at,
        error=run.error,
    )
