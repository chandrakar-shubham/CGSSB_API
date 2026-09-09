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
    "profile_registration_instructions": ("profile registration form", "प्रोफाइल पंजीयन"),
    "application_instructions": ("application form", "आवेदन पत्र"),
    "sample_application": ("sample application form", "नमूना आवेदन"),
    "bank_instructions": ("bank instructions", "बैंक निर्देश"),
    "online_application": ("online application form", "ऑनलाइन आवेदन"),
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
                with httpx.Client(
                    timeout=self.settings.request_timeout_seconds,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
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
        """Discover only real CG Vyapam /Post?PostID=... entries.

        This intentionally ignores WordPress/theme navigation, images and unrelated
        links. The individual post is fetched separately for full extraction.
        """
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
            items.append(
                ScrapedItem(
                    id=f"cgv_{fingerprint}",
                    source="cg_vyapam",
                    category=config.category.value,
                    title=title,
                    source_url=url,
                    raw={"post_id": post_id, "discovered_from": config.url},
                )
            )

        return items

    @staticmethod
    def _resource_key(label: str) -> str | None:
        normalized = re.sub(r"\s+", " ", label.casefold()).strip()
        for key, aliases in RESOURCE_LABELS.items():
            if any(alias.casefold() in normalized for alias in aliases):
                return key
        return None

    def parse_detail(self, html: str, url: str, config: SourceConfig, fallback_title: str = "") -> ScrapedItem:
        """Extract the post content and the document/application resources."""
        soup = BeautifulSoup(html, "lxml")
        post_id = self._post_id(url) or ""

        # Prefer the content article. The current site is WordPress-based, but the
        # exact builder markup can vary, so fall back through stable semantic nodes.
        article = soup.select_one("main article") or soup.select_one("article") or soup.body or soup

        # Remove navigation/sidebar/footer noise before text extraction.
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

            if any(ext in link_lower for ext in (".pdf", ".jpeg", ".jpg", ".png")):
                if notification_url is None and key in {
                    "newspaper_advertisement",
                    "detailed_advertisement",
                    "exam_instructions",
                }:
                    notification_url = link

        # De-duplicate resource URLs while preserving order.
        for key, values in list(resources.items()):
            resources[key] = list(dict.fromkeys(values))

        # If no explicit heading exists, use the first meaningful content block.
        text = self._clean(article.get_text(" ", strip=True))
        if title and text.startswith(title):
            content = text
        else:
            content = text or None

        fingerprint = self._fingerprint(config.category, post_id or title, url)
        raw = {
            "post_id": post_id or None,
            "resources": resources,
            "resource_count": sum(len(v) for v in resources.values()),
        }

        return ScrapedItem(
            id=f"cgv_{fingerprint}",
            source="cg_vyapam",
            category=config.category.value,
            title=title,
            source_url=url,
            notification_url=notification_url,
            application_url=application_url,
            content=content,
            raw=raw,
        )

    def parse(self, html: str, config: SourceConfig) -> list[ScrapedItem]:
        """Backward-compatible listing parser used by tests and callers."""
        return self.parse_listing(html, config)

    def scrape(self, category: Category, keyword: str | None = None, limit: int = 100) -> list[ScrapedItem]:
        categories = list(SOURCES) if category == Category.all else [category]
        results: list[ScrapedItem] = []

        for selected in categories:
            config = SOURCES[selected]
            html = self.fetch(config.url)
            discovered = self.parse_listing(html, config)

            # RESULT is a special single PostID page rather than a tag listing.
            if selected == Category.result and not discovered:
                discovered = [
                    ScrapedItem(
                        id=f"cgv_{self._fingerprint(selected, 'RESULT', config.url)}",
                        source="cg_vyapam",
                        category=selected.value,
                        title="CG Vyapam Result",
                        source_url=config.url,
                        raw={"post_id": "RESULT"},
                    )
                ]

            for discovered_item in discovered:
                if not discovered_item.source_url:
                    continue

                try:
                    detail_html = self.fetch(discovered_item.source_url)
                    item = self.parse_detail(
                        detail_html,
                        discovered_item.source_url,
                        config,
                        fallback_title=discovered_item.title,
                    )
                except Exception:
                    # Preserve the discovered listing even if an individual post
                    # fails, so one bad upstream page does not discard the run.
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
