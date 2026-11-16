"""
Greenhouse و Lever: قراية الفورم، تمييز اللينكات، والملء على نسخ محلية
من الصفحات الحقيقية. مفيش شبكة ولا Supabase هنا.
"""
import json
from pathlib import Path

from src import ats, form_answers, greenhouse, helper, lever

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
FILL_JS = ROOT / "extension" / "fill.js"
POLICY = {"first_name": "Elsayed", "last_name": "Mustafa", "email": "e@x.com", "phone": "+20 1",
          "city": "Cairo", "country": "Egypt", "linkedin": "https://linkedin.com/in/x"}


# ── اللينكات ─────────────────────────────────────────────────────────────

def test_greenhouse_links_of_every_shape():
    p = greenhouse.parse_url
    assert p("https://job-boards.greenhouse.io/anthropic/jobs/5390966008") == ("anthropic", "5390966008")
    assert p("https://job-boards.eu.greenhouse.io/physicsx/jobs/4860241101") == ("physicsx", "4860241101")
    assert p("https://boards.greenhouse.io/geniussports/jobs/7795980003?gh_jid=7795980003") \
        == ("geniussports", "7795980003")
    assert p("https://job-boards.greenhouse.io/embed/job_app?for=fanduel&token=7981990") \
        == ("fanduel", "7981990")
    assert p("https://www.fanduel.careers/open-positions?gh_jid=7981990", "fanduel") \
        == ("fanduel", "7981990")
    assert p("https://www.fanduel.careers/open-positions?gh_jid=7981990") is None   # من غير بورد
    assert greenhouse.application_url("https://stripe.com/jobs/search?gh_jid=8267102", "stripe") \
        == "https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=8267102"


def test_lever_links_and_same_posting_from_any_link():
    u = "https://jobs.lever.co/laminarprojects/07cdbd87-556a-4f48-b937-5202a4cf0f70"
    assert lever.application_url(u) == u + "/apply"
    assert ats.posting_key(u + "/apply") == ats.posting_key(u) == \
        ("lever", "07cdbd87-556a-4f48-b937-5202a4cf0f70")
    # صفحة البورد والـembed وموقع الشركة = نفس الإعلان
    assert ats.posting_key("https://job-boards.greenhouse.io/embed/job_app?for=fanduel&token=7981990") \
        == ats.posting_key("https://www.fanduel.careers/open-positions?gh_jid=7981990", "fanduel")
    assert ats.site_of("https://jobs.ashbyhq.com/acme/56992f29-17a5-4150-b50b-7a72206c2af6") == "ashby"
    assert ats.site_of("https://careers.example.com/job/1") is None


# ── قراية الفورم ─────────────────────────────────────────────────────────

class FakeHTTP:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def get(self, url, params=None, timeout=None):
        outer = self

        class R:
            status_code = outer.status

            def json(self):
                return outer.body

            def raise_for_status(self):
                pass
        return R()


def test_greenhouse_form_from_the_api_shape():
    body = {"questions": [
        {"label": "First Name", "required": True, "fields": [{"name": "first_name", "type": "input_text", "values": []}]},
        {"label": "Email", "required": True, "fields": [{"name": "email", "type": "input_text", "values": []}]},
        {"label": "Resume/CV", "required": True, "fields": [
            {"name": "resume", "type": "input_file", "values": []},
            {"name": "resume_text", "type": "textarea", "values": []}]},
        {"label": "Do you require visa sponsorship? ", "required": True, "fields": [
            {"name": "question_1", "type": "multi_value_single_select",
             "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]}]}],
        "compliance": [{"type": "eeoc", "questions": [{"label": "Gender", "required": False, "fields": [
            {"name": "gender", "type": "multi_value_single_select",
             "values": [{"label": "Male", "value": 1}, {"label": "Decline To Self Identify", "value": 3}]}]}]}]}
    fields = greenhouse.form("https://job-boards.greenhouse.io/x/jobs/1", http=FakeHTTP(body))
    assert [(f["path"], f["type"]) for f in fields] == [
        ("first_name", "String"), ("email", "Email"), ("resume", "File"),
        ("question_1", "ValueSelect"), ("gender", "ValueSelect")]     # resume_text بديل، اتشال
    assert fields[3]["title"] == "Do you require visa sponsorship?" and fields[3]["options"] == ["Yes", "No"]
    assert greenhouse.form("https://job-boards.greenhouse.io/x/jobs/1", http=FakeHTTP({}, 404)) is None


def test_lever_form_from_the_apply_page():
    fields = lever.parse((FIX / "lever_form.html").read_text(encoding="utf-8"))
    got = {f["path"]: (f["type"], f["required"], f["title"], f["options"]) for f in fields}
    assert got["resume"][:2] == ("File", True)
    assert got["name"] == ("String", True, "Full name", [])
    assert got["email"][0] == "Email" and got["location"][0] == "Location"
    assert got["urls[LinkedIn]"][:3] == ("String", False, "LinkedIn URL")
    assert got["cards[abc][field0]"] == ("ValueSelect", True, "Do you have AI experience?", ["Yes", "No"])
    assert got["cards[abc][field1]"][0] == "ValueSelect" and got["cards[abc][field1]"][3] == ["Full-time", "Contract"]
    assert got["cards[abc][field2]"][:2] == ("LongText", True)
    assert got["consent[marketing]"][0] == "Boolean" and "future job" in got["consent[marketing]"][2]
    assert "selectedLocation" not in got and "h-captcha-response" not in got


def test_standard_fields_get_profile_answers():
    def r(path, typ, title):
        f = {"path": path, "type": typ, "title": title, "required": True, "options": []}
        return form_answers.rule(f, {"location": "Remote", "remote_type": "remote"}, None, POLICY,
                                 {"cv": "cv.pdf"})
    assert r("name", "String", "Full name")["value"] == "Elsayed Mustafa"
    assert r("resume", "File", "Resume/CV")["value"] == "cv.pdf"
    assert r("question_9", "File", "Upload your CV")["value"] == "cv.pdf"
    assert r("question_8", "File", "Cover letter") is None            # من غير PDF للخطاب


def test_a_required_file_we_cannot_make_is_left_to_you(monkeypatch, tmp_path):
    monkeypatch.setattr(form_answers, "LEARNED", tmp_path / "l.json")
    f = {"path": "cards[x][field0]", "type": "File", "title": "Portfolio PDF", "required": True, "options": []}
    out, _ = form_answers.answer_all([f], {"location": "Remote", "remote_type": "remote"}, None, POLICY, {})
    assert out[f["path"]]["source"] == "manual"
    assert form_answers.pending(out) == []                            # مش سؤال على تليجرام


# ── الملء على النسخ المحلية ──────────────────────────────────────────────

def _fill(fixture, pack):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch()
    page = b.new_page()
    page.goto((FIX / fixture).as_uri())
    page.add_script_tag(path=str(FILL_JS))
    r = page.evaluate("pack => window.ApplyAgentFill.fillForm(document, pack)", pack)
    return pw, b, page, r


def _pdf(tmp_path, name="cv.pdf"):
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4 test")
    return str(p)


def test_fill_greenhouse_copy(tmp_path):
    a = form_answers.ans
    fields = [{"path": "first_name", "type": "String", "title": "First Name", "required": True, "options": []},
              {"path": "email", "type": "Email", "title": "Email", "required": True, "options": []},
              {"path": "resume", "type": "File", "title": "Resume/CV", "required": True, "options": []},
              {"path": "question_1", "type": "ValueSelect", "title": "Visa?", "required": True, "options": ["Yes", "No"]},
              {"path": "question_2", "type": "ValueSelect", "title": "Arbitrate", "required": True,
               "options": ["I understand and agree to the terms of the Agreement to Arbitrate set forth above."]},
              {"path": "question_3", "type": "LongText", "title": "Why us?", "required": True, "options": []},
              {"path": "race", "type": "ValueSelect", "title": "Race", "required": False, "options": ["Decline"]}]
    st = {"site": "greenhouse", "fields": fields, "answers": {
        "first_name": a("Elsayed", "profile"), "email": a("e@x.com", "profile"),
        "resume": a(_pdf(tmp_path), "profile"), "question_1": a("No", "policy"),
        "question_2": a(fields[4]["options"][0], "you"), "question_3": a("I built X.", "claude"),
        "race": a("Decline", "policy")}}
    pw, b, page, r = _fill("greenhouse_form.html", helper.build_pack(1, st))
    try:
        assert r["problems"] == [], r                       # race مش ظاهرة واختيارية: مش مشكلة
        assert page.input_value("#first_name") == "Elsayed"
        assert page.inner_text("#val-question_1") == "No"
        assert page.inner_text("#val-question_2").startswith("I understand")   # readonly: اتفتحت بالضغط
        assert page.input_value("#question_3") == "I built X."
        assert page.eval_on_selector("#resume", "e => e.files[0].name") == "cv.pdf"
        assert "Thank you" not in page.inner_text("body")
    finally:
        b.close()
        pw.stop()


def test_fill_lever_copy(tmp_path):
    a = form_answers.ans
    fields = lever.parse((FIX / "lever_form.html").read_text(encoding="utf-8"))
    st = {"site": "lever", "fields": fields, "answers": {
        "resume": a(_pdf(tmp_path), "profile"), "name": a("Elsayed Mustafa", "profile"),
        "email": a("e@x.com", "profile"), "location": a("Cairo, Egypt", "profile"),
        "urls[LinkedIn]": a("https://linkedin.com/in/x", "profile"),
        "cards[abc][field0]": a("Yes", "you"), "cards[abc][field1]": a("Contract", "you"),
        "cards[abc][field2]": a("1 month", "policy"), "consent[marketing]": a(None, "skip")}}
    pw, b, page, r = _fill("lever_form.html", helper.build_pack(1, st))
    try:
        assert r["problems"] == [], r
        assert page.input_value('input[name="name"]') == "Elsayed Mustafa"
        assert page.input_value('input[name="location"]') == "Cairo, EGY"
        assert json.loads(page.input_value('input[name="selectedLocation"]'))["name"] == "Cairo, EGY"
        assert page.input_value('select[name="cards[abc][field0]"]') == "Yes"
        assert page.is_checked('input[value="Contract"]')
        assert page.input_value('textarea[name="cards[abc][field2]"]') == "1 month"
        assert not page.is_checked('input[name="consent[marketing]"]')     # الموافقات: إنت
        assert page.eval_on_selector('input[name="resume"]', "e => e.files[0].name") == "cv.pdf"
        assert "submitted" not in page.inner_text("body").lower()
    finally:
        b.close()
        pw.stop()


def test_helper_finds_greenhouse_and_lever_states(tmp_path):
    gh = {"url": "https://www.fanduel.careers/open-positions?gh_jid=7981990", "company": "fanduel",
          "site": "greenhouse", "fields": [], "answers": {}}
    lv = {"url": "https://jobs.lever.co/acme/07cdbd87-556a-4f48-b937-5202a4cf0f70", "site": "lever",
          "fields": [], "answers": {}}
    for jid, st in ((11, gh), (12, lv)):
        (tmp_path / str(jid)).mkdir()
        (tmp_path / str(jid) / "form.json").write_text(json.dumps(st), encoding="utf-8")
    assert helper.find_state("https://job-boards.greenhouse.io/embed/job_app?for=fanduel&token=7981990",
                             tmp_path)[0] == 11
    assert helper.find_state("https://jobs.lever.co/acme/07cdbd87-556a-4f48-b937-5202a4cf0f70/apply",
                             tmp_path)[0] == 12
    assert helper.build_pack(12, lv)["site"] == "lever"


def test_experience_questions_are_yes_for_what_your_cv_verifies():
    """Laminar، 17 نوفمبر: التجربة ملت No بقيمة اختبار. الصح Yes من سيرتك."""
    def r(title, typ="ValueSelect", opts=("Yes", "No")):
        f = {"path": "q", "type": typ, "title": title, "required": True, "options": list(opts)}
        return form_answers.rule(f, {"location": "Remote", "remote_type": "remote"}, None, POLICY, {})
    for q in ("Do you have Large Language Models (LLM) experience?", "Do you have AI experience?",
              "Do you have experience with machine learning?", "Have you worked with RAG pipelines?"):
        assert r(q)["value"] == "Yes", q
    assert r("Do you have experience with Python?", "Boolean", ())["value"] is True
    # مش verified أو محتاج رأيك: يتسأل — عمره ما يقول No لوحده
    for q in ("Do you have Machine Learning Operations experience?", "Do you have MLOps experience?",
              "Do you have experience with Kubernetes?", "Do you have experience training LLMs from scratch?"):
        assert r(q) is None, q
    # مش Yes/No: مش شغل القاعدة دي
    assert r("How many years of AI experience do you have?", opts=("0-1", "2-3", "4+")) is None
