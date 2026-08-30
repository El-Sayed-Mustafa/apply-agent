"""
اختبارات دعوات LinkedIn.

الخطر هنا مش إن الكود يقع — إنه يشتغل صح ويحرق الحساب. فمعظم
الاختبارات على الحدود: الميزانية، منع التكرار، والوقف عند الاعتراض.
"""
import pytest

from src import connect
from src.linkedin import people, session


# ── الوقف عند الاعتراض ──────────────────────────────────────────────────

class FakePage:
    def __init__(self, url="https://www.linkedin.com/feed/", body=""):
        self.url = url
        self._body = body

    def inner_text(self, sel, timeout=None):
        return self._body


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/checkpoint/challenge",
    "https://www.linkedin.com/authwall?trk=x",
])
def test_blocked_urls_stop_us(url):
    """صفحة تحقق أو جدار = وقف. مش بنحاول نعدّي."""
    with pytest.raises(session.Blocked):
        session.guard(FakePage(url=url))


@pytest.mark.parametrize("text", [
    "We've restricted your account",
    "Please verify it's you",
    "You've reached the weekly invitation limit",
    "unusual activity detected on your account",
])
def test_warning_text_stops_us(text):
    with pytest.raises(session.Blocked):
        session.guard(FakePage(body=text))


def test_normal_page_passes():
    session.guard(FakePage(body="People at Mozn · 240 employees"))


def test_guard_survives_unreadable_page():
    """صفحة مش بتقرا مايوقفناش — بس الرابط لازم يتفحص."""
    class Broken(FakePage):
        def inner_text(self, sel, timeout=None):
            raise RuntimeError("detached")
    session.guard(Broken())


# ── هوية الشخص ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,key", [
    ("https://www.linkedin.com/in/el-sayed-mustafa/", "el-sayed-mustafa"),
    ("https://www.linkedin.com/in/el-sayed-mustafa?trk=abc&x=1", "el-sayed-mustafa"),
    ("/in/El-Sayed-Mustafa/", "el-sayed-mustafa"),
    ("https://www.linkedin.com/company/mozn/", None),
    ("", None),
])
def test_profile_key(url, key):
    """
    الرابط هو الهوية، والباراميترات بتتغير. لو مطبّعناش، نفس الشخص
    بيتسجّل مرتين — والقيد في الداتابيز مش هيمسكه.
    """
    assert people.profile_key(url) == key


def test_same_person_different_links_same_key():
    a = "https://www.linkedin.com/in/someone/?trk=feed"
    b = "https://linkedin.com/in/SomeOne"
    assert people.profile_key(a) == people.profile_key(b)


# ── الفلترة ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("headline,kind", [
    ("Technical Recruiter at Mozn", "recruiter"),
    ("Talent Acquisition Partner", "recruiter"),
    ("People Operations, MENA", "recruiter"),
    ("CTO & Co-founder", "leader"),
    ("Head of AI", "leader"),
    ("Senior Machine Learning Engineer", "peer"),
    ("Backend Developer", "peer"),
    ("Account Executive, EMEA", None),
    ("Real Estate Consultant", None),
    ("", None),
])
def test_classify(headline, kind):
    assert people.classify(headline) == kind


def test_recruiters_come_first():
    """
    ناس التوظيف أولوية أولى — دول اللي بيقروا تقديمك فعلاً.
    """
    order = sorted(["peer", "leader", "recruiter"],
                   key=lambda k: people.PRIORITY[k])
    assert order == ["recruiter", "leader", "peer"]


def test_skip_beats_everything():
    """'Sales Engineer' فيها engineer — بس sales بتغلب."""
    assert people.classify("Sales Engineer at X") is None


# ── الميزانية ───────────────────────────────────────────────────────────

def test_weekly_budget_under_the_platform_limit():
    """
    سقف LinkedIn حوالي 100 في الأسبوع. الاقتراب منه بيرفع احتمال
    المراجعة، فبنشتغل تحته بهامش واضح.
    """
    assert connect.WEEKLY_BUDGET <= 80


def test_daily_fits_inside_weekly():
    assert connect.DAILY_BUDGET * 7 >= connect.WEEKLY_BUDGET
    assert connect.DAILY_BUDGET <= connect.WEEKLY_BUDGET


def test_run_batch_is_small():
    """
    6 دعوات في التشغيلة بتباعد عشوائي = جلسة تصفّح عادية.
    30 دعوة ورا بعض = آلة.
    """
    assert connect.PER_RUN <= 10


def test_pacing_is_random_not_fixed():
    """
    الإيقاع المنتظم أول حاجة بتفرّق الآلة عن الإنسان.
    """
    import time as _t
    calls = []
    orig = _t.sleep
    _t.sleep = lambda s: calls.append(s)
    try:
        for _ in range(12):
            session.human_pause(2, 7)
    finally:
        _t.sleep = orig
    assert len(set(calls)) > 8, "التباعد مش عشوائي كفاية"
    assert all(2 <= c <= 7 for c in calls)


# ── تحليل كرت الشخص ─────────────────────────────────────────────────────

def test_parse_card_skips_connection_noise():
    """
    الشكل الحقيقي من الصفحة:
        Akram Ibrahem | (فاضي) | 2nd degree connection | · 2nd | Fincrime...

    أول نسخة كانت بتاخد أول سطرين، فالمسمى كان بيطلع
    "2nd degree connection" وكل التصنيف بيبوظ — كل الناس بتترفض.
    """
    name, headline = people.parse_card(
        ["Akram Ibrahem , CFE", "", "2nd degree connection", "· 2nd",
         "Fincrime & Compliance Lead"])
    assert name == "Akram Ibrahem , CFE"
    assert headline == "Fincrime & Compliance Lead"


def test_headline_does_not_absorb_the_next_person():
    """
    الكرت أحيانًا بيلمّ اسم اللي بعده. ضم سطرين كان بيطلّع
    "Software Engineer · Ahmed Abulkhair, Nora ..." — أسماء ناس
    تانيين جوّه مسمى شخص.
    """
    name, headline = people.parse_card(
        ["Yousef Khaled", "· 2nd", "Software Engineer", "Ahmed Abulkhair, Nora"])
    assert headline == "Software Engineer"
    assert "Ahmed" not in headline


def test_parse_card_real_engineer():
    name, headline = people.parse_card(
        ["Mohamed Alkaoud", "· 2nd", "AI | NLP | Data Science"])
    assert name == "Mohamed Alkaoud"
    assert people.classify(headline) == "peer"


@pytest.mark.parametrize("noise", [
    "2nd", "· 3rd", "1st degree connection", "View profile",
    "Message", "Connect", "  ", "—",
])
def test_noise_lines_dropped(noise):
    name, headline = people.parse_card(["Real Name", noise, "Data Engineer"])
    assert name == "Real Name" and "Data Engineer" in headline


def test_parse_card_empty():
    assert people.parse_card([]) == ("", "")
    assert people.parse_card(["", "  "]) == ("", "")


def test_name_not_repeated_in_headline():
    name, headline = people.parse_card(["Sara Ali", "Sara Ali", "ML Engineer"])
    assert name == "Sara Ali" and headline == "ML Engineer"


# ── الحاجز: الزرار لازم يبقى بتاع الشخص المقصود ─────────────────────────

def test_button_must_belong_to_target():
    """
    الخلل اللي بعت دعوة لشخص محدش اختاره:

        الهدف:       Albatul A.
        الزرار لقاه: "Invite Ahmed Alrabraba to connect"

    aria-label بيقول الاسم. لو مختلف، يبقى الزرار من القايمة الجانبية
    ("أشخاص قد تعرفهم") مش من الملف المفتوح.
    """
    assert people.belongs_to("Invite Albatul Alharbi to connect", "Albatul A.")
    assert not people.belongs_to("Invite Ahmed Alrabraba to connect", "Albatul A.")


def test_belongs_to_needs_a_real_overlap():
    assert not people.belongs_to("Invite Sara Ali to connect", "Mohamed Hassan")
    assert people.belongs_to("Invite Mohamed Hassan to connect", "Mohamed Hassan")


def test_belongs_to_ignores_titles():
    """'Dr' و'Eng' مش أسماء — مايتحسبوش تطابق."""
    assert not people.belongs_to("Invite Dr Ahmed to connect", "Dr Sara")


@pytest.mark.parametrize("bad", ["", None, "   ", "A B"])
def test_empty_target_never_matches(bad):
    """
    اسم فاضي أو من حروف مفردة = مانضغطش. الشك يوقف الفعل.
    """
    assert not people.belongs_to("Invite Someone to connect", bad)


def test_arabic_names_supported():
    assert people.belongs_to("دعوة محمد حسن للتواصل", "محمد حسن")


# ── الحاجز بالعربي ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "لاحظنا نشاط غير معتاد على حسابك",
    "تم تقييد حسابك مؤقتًا",
    "من فضلك تحقق من هويتك",
    "لقد وصلت إلى الحد الأسبوعي للدعوات",
])
def test_arabic_warnings_stop_us(text):
    """
    واجهة الحساب عربي. حاجز بيدوّر على إنجليزي بس مش هيشوف التحذير —
    يعني يفضل شغال وهو المفروض واقف. حماية على الورق وغايبة فعليًا.
    """
    with pytest.raises(session.Blocked):
        session.guard(FakePage(body=text))


def test_arabic_normal_page_passes():
    session.guard(FakePage(body="الأشخاص في Mozn · ٢٤٠ موظف"))
