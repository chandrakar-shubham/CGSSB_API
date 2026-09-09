from app.schemas import Category
from app.scrapers.cg_vyapam import CGVyapamScraper, SOURCES


LISTING_HTML = """
<html><body>
  <nav>
    <a href="/">NOTICE</a>
    <a href="/Posts?tag=ONLINEAPPLICATION">ONLINE APPLICATION</a>
  </nav>
  <div class="marquee">
    <a href="/Post?PostID=PSLA26ONLINE">ONLINE APPLICATION - Laboratory Attendant (PSLA26)</a>
    <a href="/Post?PostID=WRDT26ONLINE">ONLINE APPLICATION - Assistant Teacher (LSAT26)</a>
    <a href="/Post?PostID=CONTACT">CONTACT</a>
  </div>
</body></html>
"""


DETAIL_HTML = """
<html><body>
  <header><a href="/">NOTICE</a></header>
  <main>
    <article>
      <h2>Chhattisgarh Environment Conservation Board Laboratory Attendant (PSLA26)</h2>
      <ol>
        <li><a href="/uploads/pdfs/ad.jpeg">News Paper Advertisement</a></li>
        <li><a href="/uploads/pdfs/notice.pdf">Vibhagiya Vistari Vigyapan</a></li>
        <li><a href="/uploads/pdfs/syllabus.pdf">Syllabus</a></li>
        <li><a href="https://vyapamprofile.cgstate.gov.in/online/">Online Application Form</a></li>
      </ol>
    </article>
    <aside><a href="/Post?PostID=CONTACT">CONTACT US</a></aside>
  </main>
  <footer>Footer</footer>
</body></html>
"""


def test_listing_discovers_only_real_post_ids():
    scraper = CGVyapamScraper()
    items = scraper.parse_listing(LISTING_HTML, SOURCES[Category.online_application])

    assert [item.raw["post_id"] for item in items] == ["PSLA26ONLINE", "WRDT26ONLINE"]
    assert items[0].source_url.endswith("/Post?PostID=PSLA26ONLINE")


def test_detail_extracts_resources_and_application_url():
    scraper = CGVyapamScraper()
    config = SOURCES[Category.online_application]
    item = scraper.parse_detail(
        DETAIL_HTML,
        "https://vyapamcg.cgstate.gov.in/Post?PostID=PSLA26ONLINE",
        config,
        fallback_title="Fallback",
    )

    assert item.title.startswith("Chhattisgarh Environment")
    assert item.application_url == "https://vyapamprofile.cgstate.gov.in/online/"
    assert item.raw["resources"]["newspaper_advertisement"][0].endswith("ad.jpeg")
    assert item.raw["resources"]["detailed_advertisement"][0].endswith("notice.pdf")
    assert item.raw["resources"]["syllabus"][0].endswith("syllabus.pdf")
    assert item.raw["resource_count"] == 4
