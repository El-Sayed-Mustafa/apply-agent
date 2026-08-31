"""
اختبارات المتابعة والتنبيهات.

المتابعة فعل **عام**: بتظهر لصاحب الحساب وأحيانًا لشبكته. وهي
كمان مش قابلة للتراجع بصمت — فك المتابعة إشارة أوضح من إنك
ماتابعتش أصلاً.

عشان كده معظم الاختبارات هنا على اللي **مابيتعملش**.
"""
import pytest

from src import engage


# ── الحد ────────────────────────────────────────────────────────────────

def test_threshold_matches_delivery():
    """
    لو الوظيفة ماتستاهلش توصلك على تليجرام، شركتها ماتستاهلش
    متابعة. حد واحد يمنع "الحماس" من إنه يبقى سلوك آلي.
    """
    assert engage.MIN_SCORE == 70


def test_daily_caps_are_modest():
    """عشرين متابعة في الساعة سلوك بوت مهما كان الحد."""
    assert engage.DAILY_COMPANIES <= 10
    assert engage.DAILY_PEOPLE <= 8


def test_send_is_opt_in():
    """
    الافتراضي معاينة. أي فعل عام لازم يتطلب نية صريحة — نفس
    قاعدة الدعوات.
    """
    import inspect
    src = inspect.getsource(engage.run)
    assert "if not send:" in src


# ── الزرار ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label", [
    "Following", "following", "متابَع", "Unfollow", "إلغاء المتابعة",
])
def test_already_following_is_detected(label):
    """
    أخطر حاجة هنا: الضغط على زرار مكتوب عليه "إلغاء المتابعة"
    بيفك متابعة قديمة. الكشف ده هو اللي بيمنع ده.
    """
    assert engage.ALREADY.search(label)


@pytest.mark.parametrize("label", ["Follow", "متابعة", "Follow Mozn"])
def test_not_following_is_actionable(label):
    assert not engage.ALREADY.search(label)


# ── الحالة ──────────────────────────────────────────────────────────────

def test_state_survives_a_corrupt_file(tmp_path, monkeypatch):
    """
    الملف كاش مش مصدر حقيقة. لو باظ، أسوأ حاجة إننا نفتح صفحة
    زيادة ونلاقي إننا متابعين — مش إننا نتابع مرتين.
    """
    bad = tmp_path / "engage.json"
    bad.write_text("{ليس JSON", encoding="utf-8")
    monkeypatch.setattr(engage, "STATE", bad)
    s = engage.load()
    assert s == {"companies": {}, "people": {}, "alerts": {}}


def test_daily_count_only_counts_today(monkeypatch, tmp_path):
    monkeypatch.setattr(engage, "STATE", tmp_path / "s.json")
    state = {"companies": {"a": "2020-01-01T00:00:00+00:00",
                           "b": engage._today() + "T10:00:00+00:00"}}
    assert engage.done_today(state, "companies") == 1


def test_company_slug_extracted():
    import re
    m = re.search(r"/company/([^/?]+)",
                  "https://www.linkedin.com/company/apt-watch/life/")
    assert m.group(1) == "apt-watch"


def test_one_company_once_per_run():
    """
    شركة عندها تلات وظايف عالية كانت بتاخد تلات خانات من الثمانية
    وتتابع تلات مرات. اتقاس: ElevenLabs و Cohere ظهروا 3 مرات كل
    واحد في أول معاينة.
    """
    import inspect
    src = inspect.getsource(engage.run)
    assert "picked" in src and "picked.add" in src
