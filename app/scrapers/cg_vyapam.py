from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.schemas import Category, ScrapedItem


@dataclass(frozen=True)
class SourceConfig:
    category: Category
    url: str


BASE = "https://vyapamcg.cgstate.gov.in"
SOURCES = {
    Category.online_application: SourceConfig(Category.online_application, f"{BASE}/Posts?tag=ONLINEAPPLICATION"),
    Category.admit_card: SourceConfig(Category.admit_card, f"{BASE}/Posts?tag=ADMIT%20CARD"),
    Category.result: SourceConfig(Category.result, f"{BASE}/Post?PostID=RESULT"),
    Category.model_answer: SourceConfig(Category.model_answer, f"{BASE}/Posts?tag=MODEL%20ANSWERS"),
}


class CGVyapamScraper:
    def __init__(self) -> None:
        self.settings = get_settings()

    def fetch(self, url: str) -> str:
        last_error: Exception | None = None
        headers = {"User-Agent": self.settings.user_agent, "Accept": "text/html,application/xhtml+xml"}
        for attempt in range(self.settings.max_retries):
            try:
                with httpx.Client(timeout=self.settings.request_timeout_seconds, follow_redirects=True, headers=headers) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    return response.text
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                if attempt + 1 == self.settings.max_retries:
                    break
        raise RuntimeError(f"Unable to fetch CG Vyapam source: {last_error}")

    @staticmethod
    def _clean(value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    def parse(self, html: str, config: SourceConfig) -> list[ScrapedItem]:
        soup = BeautifulSoup(html, "lxml")
        items: list[ScrapedItem] = []

        # The upstream site can change its markup. We deliberately use several
        # generic discovery strategies and keep selectors isolated here.
        candidates = soup.select("a[href]")
        seen: set[str] = set()
        for anchor in candidates:
            title = self._clean(anchor.get_text(" ", strip=True))
            href = anchor.get("href")
            if not title or not href or len(title) < 8:
                continue
            url = urljoin(BASE, href)
            key = hashlib.sha256(f"{config.category.value}|{url}|{title}".encode("utf-8")).hexdigest()[:24]
            if key in seen:
                continue
            seen.add(key)
            items.append(ScrapedItem(
                id=f"cgv_{key}",
                source="cg_vyapam",
                category=config.category.value,
                title=title,
                source_url=url,
                raw={"href": href},
            ))
        return items

    def scrape(self, category: Category, keyword: str | None = None, limit: int = 100) -> list[ScrapedItem]:
        categories = list(SOURCES) if category == Category.all else [category]
        results: list[ScrapedItem] = []
        for selected in categories:
            config = SOURCES[selected]
            html = self.fetch(config.url)
            parsed = self.parse(html, config)
            if keyword:
                needle = keyword.casefold()
                parsed = [item for item in parsed if needle in item.title.casefold() or needle in (item.content or "").casefold()]
            results.extend(parsed)
            if len(results) >= limit:
                return results[:limit]
        return results[:limit]
