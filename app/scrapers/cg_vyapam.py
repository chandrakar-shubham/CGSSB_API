from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urljoin, urlparse

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

RESOURCE_LABELS = {
    "newspaper_advertisement": ("news paper advertisement", "newspaper advertisement"),
    "detailed_advertisement": ("vibhagiya vistari vigyapan", "विभागीय विस्तृत विज्ञापन"),
    "exam_instructions": ("vyapam pariksha nirdesh", "व्यापम परीक्षा निर्देश"),
    "syllabus": ("syllabus", "पाठ्यक्रम"),
    "profile_registration_instructions": (
        "instructions to fill the profile registration form",
        "profile registration form",
        "प्रोफाइल पंजीयन",
    ),
    "application_instructions": (
        "instructions to fill the application form",
        "application instructions",
        "आवेदन पत्र भरने के निर्देश",
    ),
    "sample_application": ("sample application form", "sample application", "नमूना आवेदन"),
    "bank_instructions": ("bank instructions", "बैंक निर्देश"),
    "online_application": ("online application form", "online application", "ऑनलाइन आवेदन"),
}


class CGVyapamScraper:
    def __init__(self) -> None:
        self.settings = get_settings()

    def fetch(self, url: str) -> str:
        last_error: Exception | None = None
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        }
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

    @staticmethod
    def _post_id(url: str) -> str | None:
        parsed = urlparse(url)
        if parsed.path.rstrip("/").lower() != "/post":
            return None
        value = parse_qs(parsed.query).get("PostID", [None])[0]
        return unquote(value) if value else None

    @staticmethod
    def _fingerprint(category: Category, post_id: str, url: str) -> str:
        value = f"{category.value}|{post_id}|{url}".encode("utf-8")
        return hashlib.sha256(value).hexdigest()[:24]

    def parse_listing(self, html: str, config: SourceConfig) -> list[ScrapedItem]:
        soup = BeautifulSoup(html, "lxml")
        items: list[ScrapedItem] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            href = self._clean(anchor.get("href"))
            url = urljoin(BASE, href)
            post_id = self._post_id(url)
            if not post_id or post_id.upper() in {"RESULT", "CONTACT", "PSC", "DAVA"}:
                continue
            title = self._clean(anchor.get_text(" ", strip=True))
            if not title:
                continue
            key = f"{config.category.value}|{post_id.upper()}"
            if key in seen:
                continue
            seen.add(key)
            fingerprint = self._fingerprint(config.category, post_id, url)
            items.append(ScrapedItem(
                id=f"cgv_{fingerprint}", source="cg_vyapam", category=config.category.value,
                title=title, source_url=url,
                raw={"post_id": post_id, "discovered_from": config.url},
            ))
        return items

    @staticmethod
    def _resource_key(label: str) -> str | None:
        normalized = re.sub(r"\s+", " ", label.casefold()).strip()
        aliases: list[tuple[str, str]] = []
        for key, values in RESOURCE_LABELS.items():
            aliases.extend((alias.casefold(), key) for alias in values)
        aliases.sort(key=lambda pair: len(pair[0]), reverse=True)
        for alias, key in aliases:
            if alias in normalized:
                return key
        return None

    def parse_detail(self, html: str, url: str, config: SourceConfig, fallback_title: str = "") -> ScrapedItem:
        soup = BeautifulSoup(html, "lxml")
        post_id = self._post_id(url) or ""
        article = soup.select_one("main article") or soup.select_one("article") or soup.body or soup
        for noisy in article.select("nav, header, footer, aside, script, style, noscript"):
            noisy.decompose()

        heading = ""
        for selector in ("h1", "h2", "h3", ".entry-title"):
            node = article.select_one(selector)
            if node:
                heading = self._clean(node.get_text(" ", strip=True))
                if heading:
                    break
        title = heading or fallback_title
        if not title:
            page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
            title = self._clean(page_title)

        resources: dict[str, list[str]] = {}
        notification_url: str | None = None
        application_url: str | None = None
        for anchor in article.select("a[href]"):
            label = self._clean(anchor.get_text(" ", strip=True))
            href = self._clean(anchor.get("href"))
            if not href:
                continue
            link = urljoin(url, href)
            link_lower = link.casefold()
            key = self._resource_key(label)
            if key:
                resources.setdefault(key, []).append(link)
            if "vyapamprofile.cgstate.gov.in" in link_lower:
                application_url = link
                resources.setdefault("online_application", []).append(link)
            if any(ext in link_lower for ext in (".pdf", ".jpeg", ".jpg", ".png")) and notification_url is None:
                if key in {"newspaper_advertisement", "detailed_advertisement", "exam_instructions"}:
                    notification_url = link

        for key, values in list(resources.items()):
            resources[key] = list(dict.fromkeys(values))
        text = self._clean(article.get_text(" ", strip=True))
        fingerprint = self._fingerprint(config.category, post_id or title, url)
        raw = {
            "post_id": post_id or None,
            "resources": resources,
            "resource_count": sum(len(v) for v in resources.values()),
        }
        return ScrapedItem(
            id=f"cgv_{fingerprint}", source="cg_vyapam", category=config.category.value,
            title=title, source_url=url, notification_url=notification_url,
            application_url=application_url, content=text or None, raw=raw,
        )

    def parse(self, html: str, config: SourceConfig) -> list[ScrapedItem]:
        return self.parse_listing(html, config)

    def scrape(self, category: Category, keyword: str | None = None, limit: int = 100) -> list[ScrapedItem]:
        categories = list(SOURCES) if category == Category.all else [category]
        results: list[ScrapedItem] = []
        for selected in categories:
            config = SOURCES[selected]
            html = self.fetch(config.url)
            discovered = self.parse_listing(html, config)
            if selected == Category.result and not discovered:
                discovered = [ScrapedItem(
                    id=f"cgv_{self._fingerprint(selected, 'RESULT', config.url)}",
                    source="cg_vyapam", category=selected.value, title="CG Vyapam Result",
                    source_url=config.url, raw={"post_id": "RESULT"},
                )]
            for discovered_item in discovered:
                if not discovered_item.source_url:
                    continue
                try:
                    detail_html = self.fetch(discovered_item.source_url)
                    item = self.parse_detail(detail_html, discovered_item.source_url, config, fallback_title=discovered_item.title)
                except Exception:
                    item = discovered_item
                if keyword:
                    needle = keyword.casefold()
                    haystack = f"{item.title} {item.content or ''}".casefold()
                    if needle not in haystack:
                        continue
                results.append(item)
                if len(results) >= limit:
                    return results[:limit]
        return results[:limit]
