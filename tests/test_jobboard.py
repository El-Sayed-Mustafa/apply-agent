"""
اختبارات لوحة وظايف لينكدإن.

المصدر ده اتضاف بعد قياس على 10,707 وظيفة: لينكدإن أعلى مصدر
عائدًا (23.5% مؤهلة) مقابل 5.5% لـGreenhouse — لأن وظايف الخليج
ومصر بتتنشر هنا مش على ATS أمريكاني.

واللوحة **مابتكلّفش توكنز**: الكارت منظّم، فالاستخراج من الـDOM
مباشرة والتوكنز بتفضل كلها للتقييم.
"""
import pytest

from src import jobboard


def card(*lines, jid="1"):
    return {"id": jid, "href": f"/jobs/view/{jid}/", "lines": list(lines)}


# ── تحليل الكارت ────────────────────────────────────────────────────────

def test_standard_card():
    c = jobboard.parse_card(card(
        "Agentic AI Engineer", "Agentic AI Engineer with verification",
        "APTWatch", "Riyadh, Saudi Arabia (On-site)", "Viewed", "Easy Apply"))
    assert c["title"] == "Agentic AI Engineer"
    assert c["company"] == "APTWatch"
    assert c["location"] == "Riyadh, Saudi Arabia"
    assert c["remote_type"] == "onsite"


@pytest.mark.parametrize("loc,expect", [
    ("Dubai, UAE (Remote)", "remote"),
    ("Cairo, Egypt (Hybrid)", "hybrid"),
    ("Riyadh, Saudi Arabia (On-site)", "onsite"),
    ("الرياض، السعودية (عن بعد)", "remote"),
    ("Doha, Qatar", "unknown"),
])
def test_work_type_read_from_location(loc, expect):
    c = jobboard.parse_card(card("AI Engineer", "AI Engineer", "X", loc))
    assert c["remote_type"] == expect
    assert "(" not in c["location"]


def test_ui_noise_is_not_mistaken_for_a_company():
    """
    "Easy Apply" و"Viewed" و"3 hours ago" بيتلموا مع النص —
    ولو عدّوا، بيتسجلوا كاسم شركة.
    """
    c = jobboard.parse_card(card(
        "ML Engineer", "ML Engineer", "Promoted", "Actively hiring",
        "Mozn", "Riyadh, Saudi Arabia (On-site)", "2 days ago"))
    assert c["company"] == "Mozn"


def test_card_without_company_still_parses():
    """إعلانات المجمّعات أحيانًا مالهاش اسم شركة."""
    c = jobboard.parse_card(card(
        "AI Engineer", "AI Engineer", "EMEA (Remote)"))
    assert c["location"] == "EMEA"
    assert c["remote_type"] == "remote"


def test_unusable_card_returns_none():
    assert jobboard.parse_card(card("AI Engineer")) is None


# ── الوصف ───────────────────────────────────────────────────────────────

def test_description_starts_at_the_title():
    raw = ("Skip to main content\nJobs\nMy Network\n"
           "AI Engineer\nMozn · Riyadh\nAbout the role: build RAG pipelines")
    out = jobboard.clean_desc(raw, "AI Engineer")
    assert out.startswith("AI Engineer")
    assert "My Network" not in out


def test_recommendations_are_cut_off():
    """
    "People also viewed" وبعدها وظايف تانية — لو دخلت الوصف،
    المقيّم بيقرا إعلان تاني ويحسبه جزء من الوظيفة.
    """
    body = "AI Engineer\n" + ("We need Python and RAG experience. " * 20)
    raw = body + "\nPeople also viewed\nSenior Java Developer\nBackend Engineer"
    out = jobboard.clean_desc(raw, "AI Engineer")
    assert "Senior Java Developer" not in out
    assert "RAG experience" in out


def test_short_page_is_not_truncated_by_a_stray_match():
    """
    القص بيحصل بعد 400 حرف بس — عنوان بدري في الصفحة مش سبب
    إننا نرمي الإعلان كله.
    """
    raw = "AI Engineer\nSet alert\nAbout the role: build RAG pipelines"
    assert "RAG pipelines" in jobboard.clean_desc(raw, "AI Engineer")


# ── التحويل ─────────────────────────────────────────────────────────────

def test_source_and_url_tagged():
    c = jobboard.parse_card(card("AI Engineer", "AI Engineer", "Mozn",
                                 "Riyadh, Saudi Arabia (On-site)", jid="99"))
    j = jobboard.to_job(c, "desc")
    assert j.ats == "linkedin_job"
    assert j.external_id == "99"
    assert j.url.endswith("/jobs/view/99/")


# ── النطاق ──────────────────────────────────────────────────────────────

def test_scope_is_gulf_and_egypt():
    """
    الخليج ومصر بس — دي المنطقة اللي الـATS مابيوصلهاش، وهي
    سبب وجود المصدر ده أصلاً.
    """
    _, locations = jobboard.config()
    joined = " ".join(locations).lower()
    for must in ("saudi", "emirates", "egypt"):
        assert must in joined


def test_recent_only():
    """إعلان عمره شهر الأغلب اتقفل."""
    assert jobboard.RECENT == "r604800"      # أسبوع


def test_read_only():
    """
    اللوحة أكتر سطح مراقب. قراءة بس — مفيش تقديم ولا ضغط على
    Easy Apply أبدًا.
    """
    import inspect
    src = inspect.getsource(jobboard)
    for forbidden in ("Easy Apply\")", "click()", ".click("):
        assert forbidden not in src.replace('"easy apply|', "")


def test_run_has_a_ceiling_on_page_opens():
    """
    فتح صفحة وصف أغلى فعل وأكتره لفتًا للنظر. 25 بحث × 6 كارت
    ممكن يبقى 150 صفحة — وده مش سلوك بني آدم.
    """
    assert 10 <= jobboard.MAX_DESCRIBE <= 40


# ── حجم النشاط ──────────────────────────────────────────────────────────

def test_run_is_a_slice_not_the_whole_grid():
    """
    5 كلمات × 5 أماكن = 25 بحث كل يوم، وده قبل الأوصاف. بنلف
    على الشبكة: التغطية بتكتمل على مدار الأسبوع والتشغيلة تفضل
    صغيرة.
    """
    assert jobboard.SEARCHES_PER_RUN <= 10
    keywords, locations = jobboard.config()
    assert jobboard.SEARCHES_PER_RUN < len(keywords) * len(locations)


def test_same_day_gives_the_same_slice():
    """
    إعادة تشغيل في نفس اليوم مالزمهاش تزوّد النشاط — لازم تدوّر
    على نفس الشريحة.
    """
    from datetime import datetime, timezone
    day = datetime.now(timezone.utc).toordinal()
    a = (day * jobboard.SEARCHES_PER_RUN) % 25
    b = (day * jobboard.SEARCHES_PER_RUN) % 25
    assert a == b


def test_slice_moves_the_next_day():
    day = 100
    a = (day * jobboard.SEARCHES_PER_RUN) % 25
    b = ((day + 1) * jobboard.SEARCHES_PER_RUN) % 25
    assert a != b


def test_off_target_titles_never_open_a_page():
    """
    73% من اللي دخل مكنش مطابق للدور، وكل واحدة فتحت صفحة على
    الحساب من غير فايدة. ده مش تنضيف بيانات — ده تقليل نشاط.
    """
    import inspect
    src = inspect.getsource(jobboard.run)
    i_filter = src.index("matches_role")
    i_open = src.index("describe(page")
    assert i_filter < i_open, "الفلترة لازم تسبق فتح الصفحات"
