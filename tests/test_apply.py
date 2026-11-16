"""
الدفعة 2ب: إجابات الفورم، ردودك، والملء والإرسال على نسخة محلية من فورم
Ashby. مفيش نداءات Claude ولا تليجرام ولا شركة حقيقية هنا.
"""
from pathlib import Path

import pytest

from src import apply, ashby, form_answers

POLICY = {
    "first_name": "Elsayed", "last_name": "Mustafa", "email": "e@x.com",
    "phone": "+20 1", "city": "Cairo", "country": "Egypt",
    "linkedin": "https://linkedin.com/in/x", "github": "https://github.com/x",
    "portfolio": "https://p.x", "years_of_experience": "2",
    "notice_period": "1 month", "earliest_start_date": "Within 30 days of offer",
    "relocation_note": "Open to relocating with sponsorship",
    "salary": {"current": 500, "current_only_if_required": True, "bands": {
        "egypt_local":      {"currency": "USD", "floor": 700,  "default": 800,  "ceiling": 1200},
        "remote":           {"currency": "USD", "floor": 1200, "default": 1800, "ceiling": 3000},
        "gulf_relocation":  {"currency": "SAR", "floor": 8000, "default": 9000, "ceiling": 17000},
        "other_relocation": {"currency": "USD", "floor": 4000, "default": 4000, "ceiling": 9000}},
        "per_usd": {"SAR": 3.75}},
}
RIYADH = {"title": "AI Engineer", "location": "Riyadh", "remote_type": "onsite"}
REMOTE = {"title": "AI Engineer", "location": "Remote - US", "remote_type": "remote"}
CAIRO = {"title": "AI Engineer", "location": "Cairo, Egypt", "remote_type": "onsite"}


def F(title, typ="Boolean", required=True, options=None, path="p"):
    return {"path": path, "type": typ, "title": title, "required": required,
            "options": options or [], "description": ""}


def R(field, job=RIYADH):
    return form_answers.rule(field, job, None, POLICY, {"cv": "cv.pdf", "letter": "L"})


def test_sponsorship_in_current_location_is_no_even_with_right_to_work_wording():
    f = F("Do you require sponsorship by an employer for your right to work in your current location?")
    assert R(f)["value"] is False


def test_sponsorship_for_an_onsite_gulf_job_is_yes():
    assert R(F("Will you now or in the future require visa sponsorship?"))["value"] is True
    assert R(F("Will you require visa sponsorship?"), CAIRO)["value"] is False


def test_authorization_follows_the_job_country():
    f = F("Are you legally authorized to work in the country in which the job is located?")
    assert R(f, CAIRO)["value"] is True
    assert R(f, RIYADH)["value"] is False
    assert R(f, REMOTE) is None                            # ريموت: بيتسألك


def test_yes_no_as_a_dropdown_picks_the_option_label():
    f = F("Are you authorized to work in the country you currently reside in?",
          "ValueSelect", options=["Yes ", "No "])
    assert R(f)["value"] == "Yes "


def test_consent_is_never_answered_by_a_rule():
    assert R(F("By selecting Yes, I am consenting to the use of AI for evaluating my candidacy.")) is None
    assert R(F("I acknowledge the privacy policy", "ValueSelect", options=["Yes"])) is None


def test_eeo_declines_when_it_can():
    f = F("What is your gender?", "ValueSelect",
          options=["Male", "Female", "I prefer not to say"])
    assert R(f)["value"] == "I prefer not to say"


def test_salary_number_field_is_digits_in_the_right_period():
    f = F("What are your salary expectations (annually)?", "Number")
    a = R(f, REMOTE)
    assert a["value"] == "21600"                            # 1,800 × 12


def test_salary_text_for_riyadh_is_in_riyals():
    assert R(F("Expected salary", "String"))["value"] == "SAR 9,000 / month"


def test_how_did_you_hear_prefers_linkedin():
    f = F("How did you hear about us?", "ValueSelect", options=["Friend", "LinkedIn", "Other"])
    assert R(f)["value"] == "LinkedIn"


def test_links_and_profile_fields():
    assert R(F("LinkedIn profile, personal website, or GitHub URL", "String"))["value"] \
        == POLICY["linkedin"]
    assert R(F("Link to your Github profile", "String"))["value"] == POLICY["github"]
    assert R(F("Phone", "Phone"))["source"] == "profile"


def test_answer_all_routes_open_questions_to_sonnet_and_unknowns_to_you(monkeypatch, tmp_path):
    monkeypatch.setattr(form_answers, "LEARNED", tmp_path / "l.json")
    monkeypatch.setattr(form_answers, "write_open",
                        lambda fs, job, cli=None: ({fs[0]["path"]: "I built X."}, 0.01))
    fields = [F("Why are you interested in this role?", "LongText", path="why"),
              F("Are you open to travel?", path="travel"),
              F("Anything else?", "String", required=False, path="else")]
    out, cost = form_answers.answer_all(fields, RIYADH, None, POLICY, {})
    assert out["why"] == {"value": "I built X.", "source": "claude", "why": ""}
    assert out["travel"]["source"] == "ask"
    assert out["else"]["source"] == "skip"


def test_your_answer_is_reused_for_the_same_question_and_situation(monkeypatch, tmp_path):
    monkeypatch.setattr(form_answers, "LEARNED", tmp_path / "l.json")
    form_answers.learn("Are you open to travel?", "gulf_relocation", True)
    out, _ = form_answers.answer_all([F("Are you open to travel?", path="t")],
                                     RIYADH, None, POLICY, {})
    assert out["t"]["source"] == "learned" and out["t"]["value"] is True
    out, _ = form_answers.answer_all([F("Are you open to travel?", path="t")],
                                     REMOTE, None, POLICY, {})
    assert out["t"]["source"] == "ask"                     # وضع تاني — يتسأل


@pytest.mark.parametrize("text,value", [("Yes", True), ("ايوه", True), ("لا", False),
                                        ("no thanks", False), ("maybe", None)])
def test_reply_to_a_yes_no_question(text, value):
    assert apply.parse_reply(F("q"), text) is value


def test_reply_by_option_number_or_name():
    f = F("q", "ValueSelect", options=["Remote", "Riyadh office", "Dubai office"])
    assert apply.parse_reply(f, "2") == "Riyadh office"
    assert apply.parse_reply(f, "dubai") == "Dubai office"
    assert apply.parse_reply(f, "9") is None
    m = F("q", "MultiValueSelect", options=["A", "B", "C"])
    assert apply.parse_reply(m, "1, 3") == ["A", "C"]


def test_ashby_url_and_unsupported_fields():
    assert ashby.parse_url("https://jobs.ashbyhq.com/clickhouse/56992f29-17a5-4150-b50b-7a72206c2af6") \
        == ("clickhouse", "56992f29-17a5-4150-b50b-7a72206c2af6")
    assert ashby.parse_url("https://lnkd.in/x") is None
    fields = [F("Resume", "File", path="_systemfield_resume"),
              F("Portfolio PDF", "File", path="pdf"),
              F("Optional sample", "File", required=False, path="s")]
    assert [f["path"] for f in ashby.unsupported(fields)] == ["pdf"]


# ── الملء والإرسال على نسخة محلية ───────────────────────────────────────

FIXTURE = Path(__file__).parent / "fixtures" / "ashby_form.html"
FIELDS = [F("Name", "String", path="_systemfield_name"),
          F("Email", "Email", path="_systemfield_email"),
          F("Resume", "File", path="_systemfield_resume"),
          F("Your Location", "Location", path="_systemfield_location"),
          F("Do you require sponsorship?", path="spons"),
          F("How did you hear about us?", "ValueSelect", options=["Friend", "LinkedIn"], path="hear"),
          F("Why are you interested?", "LongText", path="why")]


def _answers(tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 test")
    a = form_answers.ans
    return {"_systemfield_name": a("Elsayed Mustafa", "profile"),
            "_systemfield_email": a("e@x.com", "profile"),
            "_systemfield_resume": a(str(cv), "profile"),
            "_systemfield_location": a("Cairo, Egypt", "profile"),
            "spons": a(False, "policy"), "hear": a("LinkedIn", "policy"),
            "why": a("I built X.", "claude")}


def test_fill_puts_every_answer_in_its_field(tmp_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.goto(FIXTURE.as_uri())
        assert ashby.fill(page, FIELDS, _answers(tmp_path)) == []
        assert page.input_value("#_systemfield_name") == "Elsayed Mustafa"
        assert page.input_value("#why") == "I built X."
        assert page.input_value("#loc") == "Cairo, Cairo, Egypt"
        assert page.get_attribute('button[data-option="no"]', "aria-pressed") == "true"
        assert page.is_checked("#hear-1")
        assert page.eval_on_selector("#_systemfield_resume", "e => e.files.length") == 1
        b.close()


def test_missing_required_answer_is_reported_not_skipped(tmp_path):
    from playwright.sync_api import sync_playwright
    ans = _answers(tmp_path)
    ans["spons"] = form_answers.ans(None, "ask")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.goto(FIXTURE.as_uri())
        probs = ashby.fill(page, FIELDS, ans)
        b.close()
    assert probs and "sponsorship" in probs[0]


def test_submit_reports_success_with_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(ashby, "application_url", lambda u: FIXTURE.as_uri())
    monkeypatch.setattr(ashby, "PROFILE", tmp_path / "profile")
    shot = tmp_path / "s.png"
    ok, why = ashby.submit("x", FIELDS, _answers(tmp_path), shot, headless=True)
    assert ok, why
    assert shot.exists() and shot.stat().st_size > 1000


def test_copy_kit_gives_each_short_answer_a_copy_button():
    st = {"fields": FIELDS, "answers": {
        "_systemfield_name": form_answers.ans("Elsayed Mustafa", "profile"),
        "_systemfield_resume": form_answers.ans("applications/1/cv.pdf", "profile"),
        "spons": form_answers.ans(False, "policy"),
        "hear": form_answers.ans("LinkedIn", "policy"),
        "why": form_answers.ans("I built <X> & Y. " * 30, "claude")}}
    msgs = apply.copy_kit({"title": "AI Engineer", "company_name": "Acme",
                           "url": "https://jobs.ashbyhq.com/acme/56992f29-17a5-4150-b50b-7a72206c2af6"}, st)
    text = "\n".join(m for m, _ in msgs)
    rows = msgs[0][1]["inline_keyboard"]
    assert [r[0]["copy_text"]["text"] for r in rows] == ["Elsayed Mustafa"]   # القصير بس
    assert "<pre>I built &lt;X&gt; &amp; Y." in text                # الطويل: COPY CODE · HTML آمن
    assert "اختار: <b>No</b>" in text and "اختار: <b>LinkedIn</b>" in text
    assert "cv.pdf" in text and not any("cv.pdf" in r[0]["copy_text"]["text"] for r in rows)
    assert "/application" in text
    assert all(len(m) <= 4096 for m, _ in msgs)
