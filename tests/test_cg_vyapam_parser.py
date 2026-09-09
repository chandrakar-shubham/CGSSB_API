from app.scrapers.cg_vyapam import CGVyapamScraper, SOURCES
from app.schemas import Category


LISTING_HTML = """
<html><body>
  <a href="/Post?PostID=PSLA26ONLINE">ONLINE APPLICATION - नमूना सहायक / लैब असिस्टेंट भर्ती परीक्षा (FWLN26)</a>
  <a href="/Post?PostID=WRDT26ONLINE">ONLINE APPLICATION - सहायक शिक्षक पदों हेतु लिखित भर्ती परीक्षा (LSAT26)</a>
  <a href="/Post?PostID=RESULT">RESULT - Pre. B.Ed.26 प्रवेश परीक्षा - 2026</a>
  <a href="/Post?PostID=CONTACT">CONTACT US</a>
  <a href="/Post?PostID=PSC">DEPARTMENT LOGIN</a>
</body></html>
"""


DETAIL_HTML = """
<html>
  <head><title>CG Vyapam</title></head>
  <body>
    <header><a href="/">NOTICE</a></header>
    <main>
      <article>
        <h2>छत्तीसगढ़ पर्यावरण संरक्षण मंडल, रायपुर के अंतर्गत प्रयोगशाला परिचारक पदों की लिखित भर्ती परीक्षा (PSLA26)</h2>
        <ol>
          <li><a href="/uploads/pdfs/1.jpeg">News Paper Advertisement</a></li>
          <li><a href="/uploads/pdfs/2.pdf">Vibhagiya Vistrit Vigyapan</a></li>
          <li><a href="/uploads/pdfs/3.pdf">Vyapam Pariksha Nirdesh</a></li>
          <li><a href="/uploads/pdfs/4.pdf">Syllabus</a></li>
          <li><a href="/uploads/pdfs/5.pdf">Instructions to fill the Profile Registration form</a></li>
          <li><a href="/uploads/pdfs/6.pdf">Instructions to fill the Application form</a></li>
          <li><a href="/uploads/pdfs/7.pdf">Sample Application form</a></li>
          <li><a href="/uploads/pdfs/8.pdf">Bank Instructions</a></li>
          <li><a href="https://vyapamprofile.cgstate.gov.in/online/">Online Application Form</a></li>
        </ol>
      </article>
      <aside><a href="/Post?PostID=CONTACT">CONTACT US</a></aside>
      <footer>Copyright</footer>
    </main>
  </body>
</html>
"""


def test_listing_discovers_real_post_ids_and_ignores_navigation():
    scraper = CGVyapamScraper()
    items = scraper.parse_listing(LISTING_HTML, SOURCES[Category.online_application])

    assert [item.raw["post_id"] for item in items] == ["PSLA26ONLINE", "WRDT26ONLINE"]
    assert items[0].title.startswith("ONLINE APPLICATION")
    assert all(item.source_url.startswith("https://vyapamcg.cgstate.gov.in/Post?PostID=") for item in items)


def test_detail_extracts_resources_and_application_url():
    scraper = CGVyapamScraper()
    config = SOURCES[Category.online_application]
    item = scraper.parse_detail(
        DETAIL_HTML,
        "https://vyapamcg.cgstate.gov.in/Post?PostID=PSLA26ONLINE",
        config,
    )

    assert item.raw["post_id"] == "PSLA26ONLINE"
    assert "PSLA26" in item.title
    assert item.application_url == "https://vyapamprofile.cgstate.gov.in/online/"
    assert item.notification_url == "https://vyapamcg.cgstate.gov.in/uploads/pdfs/1.jpeg"

    resources = item.raw["resources"]
    assert resources["newspaper_advertisement"] == ["https://vyapamcg.cgstate.gov.in/uploads/pdfs/1.jpeg"]
    assert resources["detailed_advertisement"] == ["https://vyapamcg.cgstate.gov.in/uploads/pdfs/2.pdf"]
    assert resources["exam_instructions"] == ["https://vyapamcg.cgstate.gov.in/uploads/pdfs/3.pdf"]
    assert resources["syllabus"] == ["https://vyapamcg.cgstate.gov.in/uploads/pdfs/4.pdf"]
    assert resources["profile_registration_instructions"] == ["https://vyapamcg.cgstate.gov.in/uploads/pdfs/5.pdf"]
    assert resources["application_instructions"] == ["https://vyapamcg.cgstate.gov.in/uploads/pdfs/6.pdf"]
    assert resources["sample_application"] == ["https://vyapamcg.cgstate.gov.in/uploads/pdfs/7.pdf"]
    assert resources["bank_instructions"] == ["https://vyapamcg.cgstate.gov.in/uploads/pdfs/8.pdf"]
    assert resources["online_application"] == ["https://vyapamprofile.cgstate.gov.in/online/"]


def test_resource_matching_prefers_specific_labels():
    scraper = CGVyapamScraper()
    assert scraper._resource_key("Instructions to fill the Application form") == "application_instructions"
    assert scraper._resource_key("Instructions to fill the Profile Registration form") == "profile_registration_instructions"
    assert scraper._resource_key("Sample Application form") == "sample_application"
    assert scraper._resource_key("Online Application Form") == "online_application"
