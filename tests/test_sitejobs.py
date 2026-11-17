"""
مواقع التوظيف من كروم: القارئ (extension/sitejobs.js) على نسخ مصغرة من
الصفحات، وتحويل الكروت لوظايف وفلترتها. مفيش شبكة ولا Supabase هنا.
"""
from pathlib import Path

from src import sitejobs

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "extension" / "sitejobs.js"

WUZZUF = """<div class="list">
 <div class="c"><h2><a href="/jobs/p/9rz8-senior-ai-engineer-techsa-cairo-egypt?o=1">Senior AI Engineer</a></h2>
   <div>Confidential - Cairo, Egypt</div><div>6 days ago</div><div>Full Time</div><div>Remote</div>
   <div>Python · LLMs · RAG</div></div>
 <div class="c"><h2><a href="/jobs/p/afoj-ai-ml-engineer-gb-corp-giza-egypt">AI / ML Engineer</a></h2>
   <div>GB Corp - Giza, Egypt</div><div>8 days ago</div><div>On-site</div></div>
 <div class="c"><h2><a href="/jobs/p/xx-civil-engineer">Civil Engineer</a></h2>
   <div>Build Co - Cairo, Egypt</div></div>
 <a href="/jobs/p/9rz8-senior-ai-engineer-techsa-cairo-egypt">Senior AI Engineer</a>
</div>"""

INDEED = """<ul>
 <li><a data-jk="aa11"><h2><span title="AI Engineer">AI Engineer</span></h2></a>
   <span data-testid="company-name">Acme AI</span><div data-testid="text-location">Dubai</div></li>
 <li><a data-jk="bb22"><h2><span title="Senior Analytics Engineer">Senior Analytics Engineer</span></h2></a>
   <span data-testid="company-name">B2Broker</span><div data-testid="text-location">Dubai</div></li>
</ul>"""


def _extract(html, host, path="/search/jobs/"):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(f"<html><head><title>jobs</title></head><body>{html}</body></html>")
        page.add_script_tag(path=str(JS))
        r = page.evaluate("""([host, path]) => window.ApplyAgentSiteJobs.extract(document,
            {hostname: host, origin: 'https://' + host, pathname: path})""", [host, path])
        b.close()
    return r


def test_reader_takes_each_card_once_with_its_own_text():
    r = _extract(WUZZUF, "wuzzuf.net")
    assert r["site"] == "wuzzuf" and not r["blocked"]
    urls = [j["url"] for j in r["jobs"]]
    assert urls == ["https://wuzzuf.net/jobs/p/9rz8-senior-ai-engineer-techsa-cairo-egypt",
                    "https://wuzzuf.net/jobs/p/afoj-ai-ml-engineer-gb-corp-giza-egypt",
                    "https://wuzzuf.net/jobs/p/xx-civil-engineer"]       # من غير ?o=1 ومن غير تكرار
    assert "Confidential - Cairo, Egypt" in r["jobs"][0]["card"]
    assert "GB Corp" not in r["jobs"][0]["card"]                         # كارت كل وظيفة لوحده


def test_indeed_cards_use_the_job_key():
    r = _extract(INDEED, "ae.indeed.com", "/jobs")
    assert [j["url"] for j in r["jobs"]] == ["https://ae.indeed.com/viewjob?jk=aa11",
                                             "https://ae.indeed.com/viewjob?jk=bb22"]
    assert r["jobs"][0]["company"] == "Acme AI" and r["jobs"][0]["location"] == "Dubai"


def test_unknown_site_and_check_page():
    assert _extract(WUZZUF, "example.com") is None
    r = _extract("<h1>Just a moment...</h1>", "www.bayt.com", "/en/uae/jobs/ai-engineer-jobs/")
    assert r["blocked"] is True and r["jobs"] == []


def test_card_text_becomes_a_job():
    j = sitejobs.to_job({"site": "wuzzuf", "url": "https://wuzzuf.net/jobs/p/9rz8",
                         "title": "Senior AI Engineer",
                         "card": "Senior AI Engineer\nConfidential - Cairo, Egypt\n6 days ago\nFull Time\nRemote"})
    assert (j.company_name, j.location, j.remote_type, j.ats) == \
        ("Confidential", "Cairo, Egypt", "remote", "wuzzuf")
    j = sitejobs.to_job({"site": "naukrigulf", "url": "https://www.naukrigulf.com/x-jid-1",
                         "title": "AI Engineer",
                         "card": "AI Engineer\nConfidential Company\n6-12 Yrs\nAl Khobar - Saudi Arabia"})
    assert j.company_name == "Confidential Company" and j.location == "Al Khobar - Saudi Arabia"
    j = sitejobs.to_job({"site": "wellfound", "url": "https://wellfound.com/jobs/1-ml",
                         "title": "Machine Learning Engineer",
                         "card": "Noesia\nAI agents act.\n11-50 Employees\nMachine Learning Engineer\nFull-time\nRemote"})
    assert j.company_name == "Noesia" and j.remote_type == "remote"
    assert sitejobs.to_job({"site": "bayt", "url": "/relative", "title": "x"}) is None


def test_country_comes_from_the_link_when_the_card_skips_it():
    # Bayt: "Title | Company | Summary" ولينك فيه /en/uae/
    j = sitejobs.to_job({"site": "bayt", "url": "https://www.bayt.com/en/uae/jobs/ai-engineer-5312345/",
                         "title": "AI Engineer",
                         "card": "AI Engineer | Acme Tech | Build LLM agents for clients"})
    assert j.company_name == "Acme Tech" and j.location == "UAE"
    # GulfTalent: مفصول بـTab
    j = sitejobs.to_job({"site": "gulftalent", "url": "https://www.gulftalent.com/qatar/jobs/ml-engineer-501234",
                         "title": "ML Engineer", "card": "3 | ML Engineer | Delta Co\tQatar\t17 Nov"})
    assert j.company_name == "Delta Co" and j.location == "Qatar"
    # Indeed: "Dubai" لوحدها بتتكمّل بالبلد من ae.indeed.com
    j = sitejobs.to_job({"site": "indeed", "url": "https://ae.indeed.com/viewjob?jk=aa11",
                         "title": "AI Engineer", "company": "Acme AI", "location": "Hybrid work"})
    assert j.location.endswith("UAE")
    j = sitejobs.to_job({"site": "wuzzuf", "url": "https://wuzzuf.net/jobs/p/1", "title": "AI Engineer",
                         "card": "AI Engineer\nAcme - Nasr City\nFull Time"})
    assert j.location == "Nasr City, Egypt"


def test_ingest_keeps_only_jobs_that_pass_targeting(tmp_path, monkeypatch):
    monkeypatch.setattr(sitejobs, "LOG", tmp_path / "log.jsonl")
    page = {"site": "wuzzuf", "page": "https://wuzzuf.net/search/jobs/", "blocked": False, "jobs": [
        {"url": "https://wuzzuf.net/jobs/p/1", "title": "AI Engineer",
         "card": "AI Engineer\nAcme - Cairo, Egypt\nFull Time"},
        {"url": "https://wuzzuf.net/jobs/p/2", "title": "Civil Engineer",
         "card": "Civil Engineer\nBuild Co - Cairo, Egypt"},
        {"url": "https://wuzzuf.net/jobs/p/1", "title": "AI Engineer", "card": "dup"}]}
    r = sitejobs.ingest_pages(page, dry=True, quiet=True)
    assert r["sites"]["wuzzuf"]["read"] == 2 and r["kept"] == 1 and r["saved"] == 0


def test_status_counts_what_the_extension_sent(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "saved": 2,
                               "sites": {"bayt": {"read": 20, "kept": 3, "blocked": 0}}}) + "\n"
                   + json.dumps({"at": "2000-01-01T00:00:00+00:00", "saved": 9,
                                 "sites": {"indeed": {"read": 5, "kept": 1, "blocked": 0}}}) + "\n",
                   encoding="utf-8")
    monkeypatch.setattr(sitejobs, "LOG", log)
    s = sitejobs.status()
    assert s["bayt"] == {"pages": 1, "read": 20, "kept": 3, "blocked": 0}
    assert "indeed" not in s and s["_saved"]["n"] == 2
