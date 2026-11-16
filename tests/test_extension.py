"""
إضافة كروم والمساعد المحلي: الملء على نسخة فورم Ashby، والمساعد بيرفض
أي حد من غير التوكن. مفيش Supabase ولا تليجرام هنا.
"""
import base64
import http.client
import json
import threading
from pathlib import Path

import pytest

from src import helper

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "ashby_form.html"
FILL_JS = ROOT / "extension" / "fill.js"
URL = "https://jobs.ashbyhq.com/acme/56992f29-17a5-4150-b50b-7a72206c2af6"


def F(path, typ, title, required=True, options=None):
    return {"path": path, "type": typ, "title": title, "required": required,
            "options": options or [], "description": ""}


FIELDS = [F("_systemfield_name", "String", "Name"),
          F("_systemfield_resume", "File", "Resume"),
          F("_systemfield_location", "Location", "Your Location"),
          F("spons", "Boolean", "Do you require sponsorship?"),
          F("hear", "ValueSelect", "How did you hear about us?", options=["Friend", "LinkedIn"]),
          F("why", "LongText", "Why are you interested?")]


def _state(tmp_path):
    cv = tmp_path / "Elsayed-Mustafa-Acme.pdf"
    cv.write_bytes(b"%PDF-1.4 test")
    a = lambda v, s="profile": {"value": v, "source": s, "why": ""}
    return {"url": URL, "stage": "extension", "fields": FIELDS, "answers": {
        "_systemfield_name": a("Elsayed Mustafa"),
        "_systemfield_resume": a(str(cv)),
        "_systemfield_location": a("Cairo, Egypt"),
        "spons": a(False, "policy"),
        "hear": a("LinkedIn", "policy"),
        "why": a("I built X.", "claude")}}


def test_pack_carries_values_and_the_cv_itself(tmp_path):
    pack = helper.build_pack(7, _state(tmp_path), {"title": "AI Engineer", "company_name": "Acme"})
    assert pack["job"] == {"id": 7, "title": "AI Engineer", "company": "Acme"}
    assert pack["answers"]["spons"] is False and pack["answers"]["hear"] == "LinkedIn"
    f = pack["files"]["_systemfield_resume"]
    assert f["name"] == "Elsayed-Mustafa-Acme.pdf" and f["type"] == "application/pdf"
    assert base64.b64decode(f["b64"]) == b"%PDF-1.4 test"


def test_find_state_matches_the_same_posting_only(tmp_path):
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "form.json").write_text(json.dumps(_state(tmp_path)), encoding="utf-8")
    assert helper.find_state(URL + "/application?utm=x", tmp_path)[0] == 7
    assert helper.find_state(URL.replace("acme", "other"), tmp_path) is None
    assert helper.find_state("https://example.com", tmp_path) is None


def test_fill_js_fills_every_field_and_never_submits(tmp_path):
    from playwright.sync_api import sync_playwright
    pack = helper.build_pack(7, _state(tmp_path))
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.goto(FIXTURE.as_uri())
        page.add_script_tag(path=str(FILL_JS))
        r = page.evaluate("pack => window.ApplyAgentFill.fillForm(document, pack)", pack)
        assert r["problems"] == [], r
        assert page.input_value("#_systemfield_name") == "Elsayed Mustafa"
        assert page.input_value("#why") == "I built X."
        assert page.input_value("#loc") == "Cairo, Cairo, Egypt"
        assert page.get_attribute('button[data-option="no"]', "aria-pressed") == "true"
        assert page.is_checked("#hear-1")
        assert page.eval_on_selector("#_systemfield_resume", "e => e.files[0].name") \
            == "Elsayed-Mustafa-Acme.pdf"
        assert "Thank you" not in page.inner_text("body")       # مفيش Submit
        b.close()


def test_fill_js_reports_a_missing_required_answer(tmp_path):
    from playwright.sync_api import sync_playwright
    pack = helper.build_pack(7, _state(tmp_path))
    del pack["answers"]["spons"]
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.goto(FIXTURE.as_uri())
        page.add_script_tag(path=str(FILL_JS))
        r = page.evaluate("pack => window.ApplyAgentFill.fillForm(document, pack)", pack)
        b.close()
    assert len(r["problems"]) == 1 and "sponsorship" in r["problems"][0]


@pytest.fixture
def server(monkeypatch):
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), helper.Handler)
    port = srv.server_address[1]
    monkeypatch.setattr(helper, "HOSTS", {f"127.0.0.1:{port}"})
    monkeypatch.setattr(helper.Handler, "tok", "secret-token")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port
    srv.shutdown()


def _get(port, path, headers):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers=headers)
    r = c.getresponse()
    return r.status, r.getheader("Access-Control-Allow-Origin")


def test_helper_needs_the_token_and_the_right_host(server):
    host = f"127.0.0.1:{server}"
    assert _get(server, "/ping", {"Host": host, "X-Token": "secret-token"})[0] == 200
    assert _get(server, "/ping", {"Host": host})[0] == 401
    assert _get(server, "/ping", {"Host": host, "X-Token": "wrong"})[0] == 401
    # DNS rebinding: اسم تاني بيشاور على 127.0.0.1
    assert _get(server, "/ping", {"Host": "evil.example", "X-Token": "secret-token"})[0] == 403
    # مفيش CORS: صفحة ويب متقدرش تقرا الرد
    assert _get(server, "/ping", {"Host": host, "X-Token": "secret-token"})[1] is None
