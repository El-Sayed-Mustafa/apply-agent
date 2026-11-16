"""
سياسة المرتب (16 نوفمبر). answers.yaml ملف خاص، فالاختبارات بتدّي
السياسة نفسها.
"""
import pytest

from src import answers

POLICY = {"salary": {
    "current": 500, "current_only_if_required": True,
    "bands": {
        "egypt_local":      {"currency": "USD", "floor": 700,  "default": 800,  "ceiling": 1200},
        "remote":           {"currency": "USD", "floor": 1200, "default": 1800, "ceiling": 3000},
        "gulf_relocation":  {"currency": "SAR", "floor": 8000, "default": 9000, "ceiling": 17000},
        "other_relocation": {"currency": "USD", "floor": 4000, "default": 4000, "ceiling": 9000},
    },
    "per_usd": {"SAR": 3.75, "AED": 3.6725, "EGP": 50},
}, "work_authorization": {
    "Saudi Arabia": "No - needs sponsorship", "Egypt": "Yes",
    "other": "No - needs sponsorship", "remote": "Yes - remote from Egypt"}}


def job(title="AI Engineer", remote="onsite"):
    return {"title": title, "remote_type": remote}


def text(j, country, facts=None, **kw):
    return answers.expected_text(j, facts, country, POLICY, **kw)


def test_defaults_by_situation():
    assert text(job(), "Egypt") == "USD 800 / month"
    assert text(job(remote="remote"), None) == "USD 1,800 / month"
    assert text(job(), "Saudi Arabia") == "SAR 9,000 / month"
    assert text(job(), "United States") == "USD 4,000 / month"


def test_gulf_band_is_kept_in_riyals():
    """8,000 ريال لازم تطلع 8,000 ريال، مش 8,050 بعد تقريب الدولار."""
    floor = answers.minimum_acceptable(job(), "Saudi Arabia", POLICY)
    assert answers.in_currency(floor, "SAR", POLICY) == "SAR 8,000 / month"


def test_other_gulf_countries_convert_from_riyals():
    assert text(job(), "United Arab Emirates", currency="AED") == "AED 8,800 / month"


def test_posted_range_is_respected_inside_the_band():
    facts = {"salary": "SAR 12,000 - 15,000 per month"}
    assert text(job(), "Saudi Arabia", facts) == "SAR 13,500 / month"


def test_never_below_the_floor_and_rich_posts_get_their_own_floor():
    rich = {"salary": "SAR 30,000 - 40,000 per month"}
    poor = {"salary": "SAR 5,000 per month"}
    # الإعلان كله فوق السقف → أقل رقم في الإعلان (قرار 16 نوفمبر)
    assert text(job(), "Saudi Arabia", rich) == "SAR 30,000 / month"
    assert text(job(), "Saudi Arabia", poor) == "SAR 8,000 / month"
    assert text(job(), "Egypt", {"salary": "EGP 10,000 per month"}) == "USD 700 / month"


def test_junior_roles_ask_less_but_not_below_the_floor():
    assert text(job("Junior AI Engineer", "remote"), None) == "USD 1,550 / month"
    assert text(job("Junior AI Engineer"), "Egypt") == "USD 700 / month"


def test_minimum_acceptable_depends_on_the_situation():
    assert answers.minimum_acceptable(job(), "Egypt", POLICY) == 700
    assert answers.minimum_acceptable(job(remote="remote"), None, POLICY) == 1200


def test_current_salary_only_when_the_question_is_required():
    assert answers.current_salary(False, POLICY) == ""
    assert answers.current_salary(True, POLICY) == "USD 500 / month"


def test_unclear_salary_text_is_ignored_not_guessed():
    assert answers.parse_salary("competitive package", {}) is None
    assert answers.parse_salary("", {}) is None


def test_annual_forms():
    assert text(job(remote="remote"), None, annual=True) == "USD 21,600 / year"


def test_work_authorization_follows_the_relocation_rule():
    assert answers.work_authorization("Egypt", False, POLICY) == "Yes"
    assert "sponsorship" in answers.work_authorization("United States", False, POLICY)
    assert answers.work_authorization(None, True, POLICY).startswith("Yes")


def test_real_answers_file_matches_the_agreed_bands():
    """لو answers.yaml موجود (جهازك)، لازم يطابق اللي اتفقنا عليه."""
    real = answers.load()
    if not real:
        pytest.skip("answers.yaml مش موجود (GitHub مثلاً)")
    assert real["salary"]["bands"]["gulf_relocation"]["floor"] == 8000
    assert real["salary"]["bands"]["gulf_relocation"]["currency"] == "SAR"


def test_posted_range_above_the_ceiling_asks_for_their_floor():
    from src import answers
    pol = {"salary": {"bands": {"remote": {"currency": "USD", "floor": 1200,
                                           "default": 1800, "ceiling": 3000}},
                      "per_usd": {}}}
    job = {"title": "AI Engineer", "remote_type": "remote"}
    usd = answers.expected_salary(job, {"salary": "$130,000-$160,000/year"}, None, pol)
    assert round(usd) == 10833                        # 130,000 / 12
    # مدى بيعدّي السقف بس أوله تحته — السقف زي ما هو
    assert answers.expected_salary(job, {"salary": "$2,500-$5,000/month"}, None, pol) == 3000
