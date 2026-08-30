"""
اختبارات سياسة الاستهداف.

الفخ الأساسي هنا هو النفي: جملة "we do not offer visa sponsorship"
فيها كلمة sponsorship. لو الترتيب اتقلب، الوظايف المقفولة هتعدّي
كأنها مفتوحة — وده أسوأ من إننا نرفضها.
"""
import pytest

from src import targeting
from src.adapters import Job


def job(title="AI Engineer", location="Riyadh, Saudi Arabia",
        remote="unknown", desc="Build AI systems."):
    return Job(company_name="X", ats="ashby", external_id="1",
               title=title, location=location, remote_type=remote, description=desc)


# ── النفي: الفخ الأساسي ─────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "We do not offer visa sponsorship for this role.",
    "We don't sponsor work visas.",
    "Unfortunately we are unable to sponsor candidates.",
    "This role does not provide sponsorship.",
    "No visa sponsorship is available.",
    "Candidates must be authorized to work in the US without sponsorship.",
])
def test_negated_sponsorship_is_blocked(text):
    """كل واحدة فيهم فيها كلمة sponsor — ولازم كلهم يترفضوا."""
    assert targeting.classify_eligibility(text)[0] == "local_only"


@pytest.mark.parametrize("text", [
    "Visa sponsorship is available for exceptional candidates.",
    "We sponsor visas and provide relocation support.",
    "We are happy to sponsor the right person.",
    "Relocation package included.",
    "Remote - worldwide.",
    "Work from anywhere.",
])
def test_genuine_openness_is_detected(text):
    assert targeting.classify_eligibility(text)[0] == "open"


def test_blocking_wins_over_open():
    """
    إعلان فيه الاتنين. لازم يترفض — لإن العبارة المانعة أوضح
    وأصرح من كلام عام عن الانتقال.
    """
    text = ("We offer a generous relocation package for domestic moves. "
            "Please note we do not offer visa sponsorship.")
    assert targeting.classify_eligibility(text)[0] == "local_only"


@pytest.mark.parametrize("text", [
    "Must currently reside in Germany.",
    "US citizens only.",
    "Active security clearance required.",
    "Green card required.",
])
def test_other_blockers(text):
    assert targeting.classify_eligibility(text)[0] == "local_only"


def test_silence_is_unknown():
    """أغلب الإعلانات مبتقولش حاجة عن التأشيرة."""
    assert targeting.classify_eligibility("Build great software.")[0] == "unknown"


# ── الدول ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("loc,country,tier", [
    ("Riyadh, Saudi Arabia", "Saudi Arabia", 1),
    ("Dubai, United Arab Emirates", "United Arab Emirates", 1),
    ("Cairo, Egypt", "Egypt", 1),
    ("Berlin, Germany", "Germany", 2),
    ("Amsterdam, Netherlands", "Netherlands", 2),
    ("Toronto, Canada", "Canada", 3),
    ("San Francisco, United States", "United States", 4),
])
def test_country_tiers(loc, country, tier):
    assert targeting.detect_country(loc) == (country, tier)


def test_uae_not_confused_with_us():
    """
    'United Arab Emirates' فيه 'United'. لو المطابقة بالأقصر الأول،
    الإمارات هتتقرا أمريكا وتترفض. الأطول لازم يكسب.
    """
    assert targeting.detect_country("United Arab Emirates")[1] == 1


def test_unknown_country():
    assert targeting.detect_country("Lagos, Nigeria") == (None, None)


def test_no_location():
    assert targeting.detect_country(None) == (None, None)


# ── الأدوار ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "AI Engineer", "Machine Learning Engineer", "Data Platform Engineer",
    "Automation Engineer", "Forward Deployed Engineer", "Backend Engineer",
])
def test_relevant_roles(title):
    assert targeting.matches_role(title)


@pytest.mark.parametrize("title", [
    "Senior iOS Engineer", "Frontend Engineer", "Product Designer",
    "Account Executive", "Machine Learning Intern", "VP of Engineering",
    "Director of Data Science",
])
def test_irrelevant_roles(title):
    assert not targeting.matches_role(title)


def test_exclude_beats_include():
    """'Mobile AI Engineer' فيها ai — بس mobile بتغلب."""
    assert not targeting.matches_role("Mobile AI Engineer")


# ── القرار الكامل ───────────────────────────────────────────────────────

def test_gulf_onsite_passes():
    assert targeting.evaluate(job()).eligible


def test_remote_anywhere_passes():
    v = targeting.evaluate(job(location="Anywhere", remote="remote"))
    assert v.eligible and v.reason == "ريموت"


def test_germany_onsite_passes():
    """المستوى 2 — بيرعوا تأشيرات فعلاً."""
    assert targeting.evaluate(job(location="Berlin, Germany")).eligible


def test_us_onsite_rejected():
    """المستوى 4: الحضوري مرفوض، مش الشركة."""
    v = targeting.evaluate(job(location="New York, United States"))
    assert not v.eligible and "ريموت بس" in v.reason


def test_us_remote_passes():
    """نفس الشركة، وظيفة ريموت — تعدّي."""
    assert targeting.evaluate(
        job(location="United States", remote="remote")).eligible


def test_blocked_text_rejects_even_in_gulf():
    """حتى وظيفة في الرياض بتطلب إقامة سعودية مش مفيدة ليك دلوقتي."""
    v = targeting.evaluate(job(desc="Saudi nationals only."))
    assert not v.eligible and "محلي فقط" in v.reason


def test_unknown_country_onsite_rejected():
    assert not targeting.evaluate(job(location="Lagos, Nigeria")).eligible


def test_unknown_eligibility_still_passes():
    """
    الصمت عن التأشيرة مايمنعش. تكلفة الخطأ غير متماثلة:
    وظيفة زيادة = دقيقة ضايعة · وظيفة ضايعة = فرصة ضايعة.
    """
    v = targeting.evaluate(job(desc="Build great software."))
    assert v.eligible and v.eligibility == "unknown"


# ── الأقدمية ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,years", [
    ("We need 5+ years of experience.", 5),
    ("Minimum of 7 years experience required.", 7),
    ("At least 8 years of professional experience.", 8),
    ("3-5 years of relevant experience", 3),
    ("2 years experience", 2),
])
def test_years_extracted(text, years):
    assert targeting.required_years(text) == years


def test_takes_the_highest_requirement():
    """
    "3 years Python, 8 years distributed systems" هي فعليًا وظيفة
    8 سنين. لو أخدنا الأقل، هنقدّم على وظايف مالناش فيها.
    """
    t = "3+ years of Python and 8+ years of experience with distributed systems."
    assert targeting.required_years(t) == 8


def test_no_years_mentioned():
    assert targeting.required_years("Build cool things with Python.") is None


def test_absurd_numbers_ignored():
    """'50 years of combined team experience' مش متطلب عليك."""
    assert targeting.required_years("Our team has 50 years experience") is None


@pytest.mark.parametrize("text,blocked", [
    ("We require 8+ years of experience.", True),
    ("5 years experience needed.", True),
    ("2+ years experience is enough.", False),
    ("3 years of experience.", False),
    ("Experience with Python required.", False),
])
def test_too_senior(text, blocked):
    assert targeting.is_too_senior(text)[0] is blocked


def test_senior_title_excluded():
    """المفتاح exclude_senior_in_title شغال."""
    assert not targeting.matches_role("Senior AI Engineer")
    assert not targeting.matches_role("Sr. Data Engineer")


@pytest.mark.parametrize("title", [
    "Staff Software Engineer", "Principal AI Engineer",
    "Engineering Manager", "Tech Lead, Data Platform",
])
def test_beyond_level_titles_excluded(title):
    """Staff و Principal و Lead دايمًا 8+ سنين — مفيش استثناءات."""
    assert not targeting.matches_role(title)


def test_normal_titles_still_pass():
    assert targeting.matches_role("AI Engineer")
    assert targeting.matches_role("Data Engineer")
    assert targeting.matches_role("Backend Engineer")


def test_senior_job_rejected_end_to_end():
    v = targeting.evaluate(job(title="AI Engineer",
                               desc="We need 8+ years of experience."))
    assert not v.eligible and "8 سنين" in v.reason
