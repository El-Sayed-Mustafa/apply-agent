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
    i_filter = src.index("could_pass")
    i_open = src.index("describe(page")
    assert i_filter < i_open, "الفلترة لازم تسبق فتح الصفحات"


# ── الطابور والأولوية ───────────────────────────────────────────────────

def _card(i, loc="Riyadh, Saudi Arabia", remote="onsite",
          queued="2026-10-20T00:00:00+00:00"):
    return {"id": str(i), "title": "AI Engineer", "company": "X",
            "location": loc, "remote_type": remote,
            "url": f"https://www.linkedin.com/jobs/view/{i}/",
            "queued_at": queued}


def test_reads_the_whole_first_page_not_six():
    """
    "AI Engineer" في السعودية في أسبوع = 34 نتيجة، وكنا بناخد أول 6.
    قراءة الكروت مبتفتحش صفحات — اللي بيكلّف الحساب هو MAX_DESCRIBE.
    """
    assert jobboard.PER_SEARCH >= 25
    assert jobboard.MAX_DESCRIBE <= 12


def test_cards_beyond_the_ceiling_wait_instead_of_vanishing():
    cards = {str(i): _card(i) for i in range(20)}
    todo, rest = jobboard.pick(cards, {}, known=set(), limit=12)
    assert len(todo) == 12
    assert len(rest) == 8


def test_gulf_and_remote_come_before_tier_three():
    cards = {"1": _card(1, "London, United Kingdom"),
             "2": _card(2, "Dubai, UAE"),
             "3": _card(3, "EMEA", remote="remote")}
    todo, _ = jobboard.pick(cards, {}, known=set(), limit=2)
    assert {c["id"] for c in todo} == {"2", "3"}


def test_queued_cards_go_first_within_the_same_priority():
    queue = {"9": _card(9, queued="2026-10-18T00:00:00+00:00")}
    cards = {"1": _card(1)}
    todo, rest = jobboard.pick(cards, queue, known=set(), limit=1)
    assert todo[0]["id"] == "9"
    assert list(rest) == ["1"]


def test_queued_card_saved_meanwhile_is_dropped():
    queue = {"9": _card(9)}
    todo, rest = jobboard.pick({}, queue, known={"9"}, limit=12)
    assert todo == [] and rest == {}


def test_queue_forgets_cards_older_than_a_week(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timedelta, timezone
    p = tmp_path / "q.json"
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps({"1": _card(1, queued=old),
                             "2": _card(2, queued=new)}), encoding="utf-8")
    monkeypatch.setattr(jobboard, "QUEUE", p)
    assert list(jobboard.load_queue()) == ["2"]


def test_missing_queue_file_is_an_empty_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(jobboard, "QUEUE", tmp_path / "nope.json")
    assert jobboard.load_queue() == {}


def test_bahrain_and_oman_are_searched():
    """في المستوى الأول من الأول، بس عمرهم ما اتدوّر عليهم في اللوحة."""
    _, locations = jobboard.config()
    assert "Bahrain" in locations and "Oman" in locations
