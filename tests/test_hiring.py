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


def test_the_target_passes():
    assert ok("Junior Data Analyst | Python",
              "Web scraping with Selenium and SQL reporting")[0]


@pytest.mark.parametrize("headline,blurb,why", [
    ("Junior Data Analyst", "SQL reporting only", "مفيش scraping"),
    ("Junior Data Analyst", "Selenium scraping", "مفيش SQL"),
])
def test_needs_both_skills(headline, blurb, why):
    """
    المهارتين مطلوبين مع بعض — واحدة منهم بس مش المطلوب.
    """
    good, reason = ok(headline, blurb)
    assert not good and reason == why


def test_outside_cairo_rejected():
    good, reason = ok("Data Analyst", "scraping and SQL",
                      location="Mianwali District, Punjab, Pakistan")
    assert not good and "القاهرة" in reason


def test_senior_rejected():
    """
    "Senior Data Extraction Expert" ظهر في أول بحث حقيقي — عنده
    المهارتين بس مش خريج جديد.
    """
    good, reason = ok("Senior Data Extraction Expert",
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
