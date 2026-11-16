"""
الدفعة 2أ: تجهيز ملف التقديم. مفيش نداءات Claude ولا تليجرام هنا.
"""
from src import cover, prepare, telegram

CV = ("AI & Automation Engineer with 2+ years. Rating model 80.7% exact. "
      "Tracks about 10,000 products. Delivered 6+ client platforms.")
LEVELS = {"verified": {"python", "fastapi"},
          "banned": ["Docker", "AWS", "Kubernetes", "LangGraph"]}


def test_letter_with_only_cv_numbers_passes():
    letter = ("Dear Hiring Team,\nI built a rating model at 80.7% exact match "
              "and delivered 6+ client platforms.\nBest regards,\nElsayed Mustafa")
    assert cover.check(letter, CV, LEVELS) == []


def test_invented_number_is_rejected():
    letter = "I cut costs by 40% and tracked 10,000 products."
    assert any("40%" in p for p in cover.check(letter, CV, LEVELS))


def test_developing_skill_presented_as_experience_is_rejected():
    letter = "I deploy LLM services on AWS with Docker every day."
    probs = cover.check(letter, CV, LEVELS)
    assert any("AWS" in p for p in probs) and any("Docker" in p for p in probs)


def test_real_cv_levels_ban_developing_and_future_skills():
    lv = cover._levels()
    banned = {b.lower() for b in lv["banned"]}
    assert {"langgraph", "docker", "kubernetes", "redis"} <= banned
    assert "pytest" not in banned and "python" not in banned


POLICY = {
    "first_name": "Elsayed", "last_name": "Mustafa", "email": "e@x.com",
    "notice_period": "1 month", "requires_sponsorship": "Yes",
    "relocation_note": "Open to relocating with sponsorship",
    "salary": {"current": 500, "bands": {
        "egypt_local":      {"currency": "USD", "floor": 700,  "default": 800,  "ceiling": 1200},
        "remote":           {"currency": "USD", "floor": 1200, "default": 1800, "ceiling": 3000},
        "gulf_relocation":  {"currency": "SAR", "floor": 8000, "default": 9000, "ceiling": 17000},
        "other_relocation": {"currency": "USD", "floor": 4000, "default": 4000, "ceiling": 9000}},
        "per_usd": {"SAR": 3.75}},
    "work_authorization": {"Saudi Arabia": "No - sponsorship", "remote": "Yes - remote",
                           "Egypt": "Yes", "other": "No - sponsorship"},
}


def test_answer_sheet_for_a_riyadh_job():
    job = {"title": "AI Engineer", "location": "Riyadh", "remote_type": "onsite"}
    s = prepare.answer_sheet(job, None, POLICY)
    assert s["Expected salary"].startswith("SAR 9,000 / month")
    assert "USD 2,400" in s["Expected salary"]            # المعادل بالدولار
    assert s["Minimum acceptable salary"] == "SAR 8,000 / month"
    assert s["Requires sponsorship"] == "Yes"
    assert s["Work authorization"] == "No - sponsorship"


def test_remote_job_needs_no_sponsorship_or_relocation_line():
    job = {"title": "AI Engineer", "location": "EMEA", "remote_type": "remote"}
    s = prepare.answer_sheet(job, None, POLICY)
    assert s["Requires sponsorship"] == "No"
    assert s["Expected salary"] == "USD 1,800 / month"
    assert prepare.relocation_line(job) == ""


def test_onsite_abroad_gets_the_relocation_line():
    job = {"title": "AI Engineer", "location": "Dubai, UAE", "remote_type": "onsite"}
    assert "relocat" in prepare.relocation_line(job)


def test_apply_buttons_only_behind_the_switch():
    old = telegram.keyboard(5, "https://x.co/j", apply_flow=False)
    assert old["inline_keyboard"][0][0]["callback_data"] == "a:5"
    new = telegram.keyboard(5, "https://x.co/j", apply_flow=True)
    datas = [b.get("callback_data") for b in new["inline_keyboard"][0]]
    assert datas == ["p:5", "s:5", "v:5"]
    assert new["inline_keyboard"][1][0]["url"] == "https://x.co/j"


def test_bad_url_never_becomes_a_button():
    kb = telegram.keyboard(5, "javascript:alert(1)", apply_flow=True)
    assert len(kb["inline_keyboard"]) == 1


def test_submit_buttons_carry_the_approval_id_not_the_job_id():
    kb = telegram.submit_keyboard(42)
    assert [b["callback_data"] for b in kb["inline_keyboard"][0]] == ["ys:42", "yn:42"]
    import re
    assert all(re.fullmatch(r"[a-z]{1,2}:\d{1,12}", b["callback_data"])
               for b in kb["inline_keyboard"][0])          # نفس فحص الـwebhook


def test_kuwait_job_answers_in_dinars():
    pol = {**POLICY, "salary": {**POLICY["salary"],
                                "per_usd": {"SAR": 3.75, "KWD": 0.307}}}
    job = {"title": "AI Engineer", "location": "Kuwait City", "remote_type": "onsite"}
    s = prepare.answer_sheet(job, None, pol)
    assert s["Expected salary"].startswith("KWD 740 / month")   # 9,000 ريال ≈ 737 دينار
    assert s["Minimum acceptable salary"].startswith("KWD 650")


def test_post_filename_skips_the_recruiters_name():
    from src import render
    post = {"ats": "linkedin_post", "company_name": "Tamer Omar, MBA, PMP",
            "title": "AI/ML Engineer"}
    assert render.filename(post) == "Elsayed-Mustafa-AIML-Engineer.pdf"
    job = {"ats": "ashby", "company_name": "Scale", "title": "AI Engineer"}
    assert render.filename(job) == "Elsayed-Mustafa-Scale-AI-Engineer.pdf"
