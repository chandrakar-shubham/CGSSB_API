from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, HttpUrl


class Category(str, Enum):
    online_application = "online_application"
    admit_card = "admit_card"
    result = "result"
    model_answer = "model_answer"
    all = "all"


class Source(str, Enum):
    cg_vyapam = "cg_vyapam"


class ScrapeRequest(BaseModel):
    source: Source = Source.cg_vyapam
    category: Category = Category.all
    keyword: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=100, ge=1, le=500)


class ScrapeJob(BaseModel):
    job_id: str
    status: str
    created_at: datetime
    source: Source
    category: Category


class ScrapedItem(BaseModel):
    id: str
    source: str
    category: str
    title: str
    published_date: str | None = None
    source_url: str | None = None
    notification_url: str | None = None
    application_url: str | None = None
    content: str | None = None
    raw: dict = Field(default_factory=dict)


class QueryResponse(BaseModel):
    success: bool = True
    total: int
    items: list[ScrapedItem]
