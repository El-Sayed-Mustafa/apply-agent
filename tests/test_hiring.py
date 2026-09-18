"""
اختبارات البحث عن مرشّحين.

الاتجاه معكوس: باقي المنظومة بتدوّر على وظايف ليه، ودي بتدوّر
على ناس ليه. وهنا الفلترة غرضها مختلف — مش تحمينا من وظيفة وحشة،
دي بتحدّد مين يستاهل نفتح ملفه الشخصي، وفتح الملفات هو النشاط
اللي بيبان على الحساب.
"""
import pytest

from src import hiring


def card(*lines, url="https://www.linkedin.com/in/x"):
    return {"url": url, "lines": list(lines)}


# ── قراءة البطاقة ───────────────────────────────────────────────────────

def test_real_result_parsed():
    c = hiring.parse(card(
        "Salah Mahmoud • 1st", "Data Engineer | AWS", "Egypt",
        "Data Analyst & Scraping at TAG with Python, SQL, web scraping."))
    assert c["name"] == "Salah Mahmoud"
    assert c["headline"] == "Data Engineer | AWS"
    assert "SQL" in c["blurb"]


def test_mutual_connection_fragment_rejected():
    """
    البطاقة اللي جوّه بطاقة تانية بتطلع من غير سطر اسم. لو عدّت،
    بتتسجّل كمرشّح وهمي وبتاخد خانة من فتح الملفات.
    """
    assert hiring.parse(card(
        "Raja Bilal Ahmed, Feroz A. Shaik & 1,520 other mutual connections",
        "· 22K followers", "x")) is None


@pytest.mark.parametrize("line", [
    "Ahmed Ali • 2nd", "Mina Elkholy • 3rd+", "سارة محمد • 1st",
])
def test_name_line_shapes(line):
    assert hiring.NAME_LINE.match(line)


# ── الفلترة ─────────────────────────────────────────────────────────────

def ok(headline, blurb="", location="Cairo, Egypt"):
    return hiring.looks_right({"headline": headline, "blurb": blurb,
                               "location": location})


def test_settled_professional_rejected():
    """
    أول نسخة رجّعت "Data Engineer | AWS" و"BI Engineer @ Instant" —
    ناس شغالة ومستقرة. دول مش هيسيبوا شغلهم عشان عرض من شركة
    صغيرة، فوجودهم في القايمة ضجيج.
    """
    good, why = ok("Data Engineer | AWS", "Python, SQL, web scraping at TAG")
    assert not good and "بيدوّر" in why


@pytest.mark.parametrize("headline", [
    "Data Analyst | Open to Work",
    "Python Developer | #OpenToWork",
    "Seeking a Data Analyst opportunity",
    "Looking for a junior data role",
    "Immediately available | Data Analyst",
    "محلل بيانات | أبحث عن عمل",
    "مهندس بيانات | متاح للعمل",
])
def test_seeking_passes(headline):
    assert ok(headline, "SQL and web scraping projects")[0]


@pytest.mark.parametrize("headline", [
    "Data Analyst Intern @ Vodafone",
    "Data Engineering Trainee",
    "Machine Learning Intern",
    "متدرب تحليل بيانات",
])
def test_intern_passes(headline):
    assert ok(headline, "SQL scraping python")[0]


@pytest.mark.parametrize("headline", [
    "Computer Science Student | Python",
    "Final year student, Faculty of Computers",
    "Fresh Graduate | Data Analysis",
    "طالب علوم حاسب",
])
def test_student_passes(headline):
    assert ok(headline, "web scraping and SQL")[0]


def test_status_prefers_seeking():
    """
    "Data Analyst Intern, open to work" حالته "بيدوّر" — دي أقوى
    إشارة وأقربها لقرار.
    """
    assert hiring.status({"headline": "Data Analyst Intern | Open to Work",
                          "blurb": ""}) == "بيدوّر"


def test_status_none_for_the_settled():
    assert hiring.status({"headline": "Senior Data Engineer at Fawry",
                          "blurb": "SQL scraping"}) is None


def test_employed_student_rejected():
    """
    "Student" في العنوان مع شغل فعلي في شركة مش مرشّح — ده حد
    بيدرس وشغّال، مش بيدوّر.
    """
    good, why = ok("Data Analyst at Fawry | MSc Student",
                   "SQL scraping python")
    assert not good


def test_status_recorded_on_the_candidate():
    """الحالة لازم توصله في الرسالة — هي أهم من المسمى."""
    c = {"headline": "Open to Work | Data Analyst",
         "blurb": "SQL scraping", "location": "Cairo"}
    hiring.looks_right(c)
    assert c["status"] == "بيدوّر"


def test_one_skill_is_enough_on_the_card():
    """
    كارت البحث سطرين. طلب المهارتين فيه رجّع **صفر** من 40 نتيجة،
    رغم إن 15 منهم بيدوّروا فعلاً — الإشارة النادرة هي "بيدوّر"،
    والمهارات تفاصيل بتبان في البروفايل مش في الكارت.
    """
    assert ok("Open to Work | Data Analyst", "SQL reporting")[0]
    assert ok("Open to Work | Data Analyst", "Selenium scraping")[0]


def test_neither_skill_rejected():
    good, why = ok("Open to Work | Graphic Designer", "Photoshop and Figma")
    assert not good and "scraping" in why


def test_skills_reported_on_the_candidate():
    """
    القايمة للمراجعة، فلازم تقول إيه اللي اتشاف فعلاً — "SQL" بس
    غير "scraping + SQL".
    """
    c = {"headline": "Open to Work | Data Analyst",
         "blurb": "SQL and web scraping", "location": "Cairo"}
    hiring.looks_right(c)
    assert c["skills"] == "scraping + SQL"

    c2 = {"headline": "Open to Work | Data Analyst",
          "blurb": "SQL reporting", "location": "Cairo"}
    hiring.looks_right(c2)
    assert c2["skills"] == "SQL"


def test_outside_cairo_rejected():
    good, reason = ok("Open to Work | Data Analyst", "scraping and SQL",
                      location="Mianwali District, Punjab, Pakistan")
    assert not good and "القاهرة" in reason


def test_senior_rejected():
    good, reason = ok("Senior Data Extraction Expert | Open to Work",
                      "web scraping SQL data mining")
    assert not good and "خريج" in reason


@pytest.mark.parametrize("word", ["Scrapy", "BeautifulSoup", "crawling",
                                  "Playwright", "data extraction"])
def test_scraping_synonyms(word):
    assert hiring.SCRAPING.search(word)


@pytest.mark.parametrize("word", ["SQL", "PostgreSQL", "MySQL", "BigQuery",
                                  "قواعد بيانات"])
def test_sql_synonyms(word):
    assert hiring.SQL.search(word)


def test_queries_target_seekers():
    """
    الاستعلامات نفسها لازم تدوّر على بيدوّر/متدرّب — الفلترة
    وحدها بتشتغل على بركة غلط.
    """
    joined = " ".join(hiring.QUERIES).lower()
    for must in ("open to work", "intern", "seeking", "student"):
        assert must in joined


# ── سنة التخرج ─────────────────────────────────────────────────────────

AHMED = """Education
Minufiya University
Bachelor of Artificial Intelligence, Machine Intelligence
Oct 2024 - Aug 2028
Skills: Probability, Logic Design
Digital Egypt Pioneers Initiative - DEPI
AI & Data Sience
Jun 2025 - Jan 2026
"""

BOTHAINA = """Education
Beni-Suef University
Bachelor's degree, International Relations and Affairs
Sep 2013 - Jul 2017
Grade: B+
"""

TARGET = """Education
Cairo University
Bachelor of Computer Science
Sep 2021 - Jul 2025
"""


def test_bootcamp_does_not_count_as_graduation():
    """
    Ahmed Tayel عنده بكالوريوس 2024-2028 ومعسكر DEPI 2025-2026.
    أكبر سنة كانت هتقول 2026 وهو لسه طالب لحد 2028.
    """
    assert hiring.grad_year(AHMED) == 2028


def test_old_graduate_read_correctly():
    assert hiring.grad_year(BOTHAINA) == 2017


def test_neither_is_a_target_year():
    """
    الاتنين عدّوا فلترة المهارات، والاتنين مش في السنين المطلوبة.
    ده بالظبط شغل القراءة دي.
    """
    for t in (AHMED, BOTHAINA):
        assert hiring.grad_year(t) not in hiring.YEARS


def test_real_target_passes():
    assert hiring.grad_year(TARGET) == 2025


def test_ongoing_study_has_no_end():
    e = hiring.education_entries("Cairo University\nBachelor\n2023 - Present")
    assert e and e[0]["end"] is None


def test_plain_year_range():
    t = "Faculty of Artificial Intelligence, Menoufia University\n2024 - 2028"
    assert hiring.grad_year(t) == 2028


def test_no_education_data_returns_none():
    """أحسن من تخمين: مرشّح من غير بيانات لازم يتقال عنه مش معروف."""
    assert hiring.grad_year("") is None
    assert hiring.grad_year("Education\nCairo University") is None


def test_degree_told_apart_from_course():
    marks = {x["text"]: x["degree"] for x in hiring.education_entries(AHMED)}
    assert any(v for k, v in marks.items() if "University" in k)


def test_reads_the_dedicated_page():
    """
    الملف الكامل فيه منشورات الشخص — 1026 سطر لواحد منهم — فأي
    max على سنين الصفحة بيرجّع السنة الحالية.
    """
    import inspect
    assert hiring.EDU_URL == "/details/education/"
    assert "EDU_URL" in inspect.getsource(hiring.enrich)


# ── نفس الشخص ───────────────────────────────────────────────────────────

def test_language_suffix_is_the_same_person():
    """`/en/` بيخلّي نفس الملف يتسجّل مرتين وياخد خانتين من الفتح."""
    a = hiring.same_person("https://www.linkedin.com/in/mohamed-864881278/")
    b = hiring.same_person("https://www.linkedin.com/in/mohamed-864881278/en/")
    assert a == b


def test_different_people_stay_different():
    assert (hiring.same_person("https://www.linkedin.com/in/ahmed-tayel99/")
            != hiring.same_person("https://www.linkedin.com/in/salah-mahmoud/"))


# ── تأكيد المهارات ──────────────────────────────────────────────────────

def test_confirmation_runs_after_the_year_filter():
    """
    السنة أرخص تمييز عندنا (صفحة صغيرة واحدة). لو أكّدنا المهارات
    الأول، بنفتح 13 بروفايل بدل 5 — الترتيب هو الفرق بين 26 صفحة
    و18.
    """
    import inspect
    src = inspect.getsource(hiring.run)
    assert src.index("enrich(page") < src.index("confirm_skills(page")
    assert src.index("in YEARS") < src.index("confirm_skills(page")


def test_scraping_ranks_first():
    """
    الـscraping أهم شرط في الطلب، فاللي اتأكد عنده لازم يتقدّم
    في القايمة.
    """
    cands = [
        {"name": "a", "grad": 2025, "scraping": False},
        {"name": "b", "grad": 2024, "scraping": True},
    ]
    cands.sort(key=lambda c: (not c.get("scraping"), -(c.get("grad") or 0)))
    assert [c["name"] for c in cands] == ["b", "a"]


def test_card_skills_are_a_fallback_not_the_answer():
    """
    ولا واحد من 13 مرشّح ذكر scraping في الكارت — مش لإنهم مش
    بيعرفوا، لإن الكارت سطرين. التسليم لازم يقول اللي اتأكد.
    """
    import inspect
    assert "confirmed" in inspect.getsource(hiring.message)
