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


# ── تحديد الشركة ────────────────────────────────────────────────────────

def _hit(slug, name):
    return {"slug": slug, "name": name}


def pick(hits, want):
    """نفس منطق find_company بعد جلب النتايج."""
    w = engage.norm(want)
    exact = [h for h in hits if engage.norm(h["name"]) == w]
    if not exact:
        return ""
    clean = [h for h in exact if engage.norm(h["slug"]) == w]
    if clean:
        return clean[0]["slug"]
    return "" if len(exact) > 1 else exact[0]["slug"]


def test_clean_slug_wins_over_search_rank():
    """
    البحث عن "moss" رجّع `mossconstruct` أول نتيجة — شركة
    إنشاءات. الترتيب مش دليل هوية؛ المعرّف النضيف دليل أقوى.
    """
    hits = [_hit("mossconstruct", "Moss"), _hit("moss", "MOSS")]
    assert pick(hits, "moss") == "moss"


def test_ambiguous_is_skipped_not_guessed():
    """
    خمس شركات بنفس الاسم ومفيش معرّف نضيف: التخمين بيتابع شركة
    تانية باسمه. أرخص إننا نسيبها.
    """
    hits = [_hit("lean-tech-sp", "Lean-Tech"), _hit("lean-tech-sg", "Lean Tech"),
            _hit("leantechpro", "Leantech")]
    assert pick(hits, "Lean Tech") == ""


def test_single_match_passes():
    assert pick([_hit("happyrobot", "HappyRobot")], "HappyRobot") == "happyrobot"


def test_different_company_never_matches():
    """"Mozn Real Estate" شركة تانية خالص."""
    assert pick([_hit("moznrealestate", "Mozn Real Estate")], "Mozn") == ""


def test_state_records_the_slug_not_just_the_name():
    """
    بعد حادثة `mossconstruct` مكانش في طريقة نعرف بيها الصفحة
    اللي اتفتحت فعلاً — السجل كان بيحفظ اسم الشركة بس. سجل من
    غير المعرّف مابيسمحش بمراجعة.
    """
    import inspect
    src = inspect.getsource(engage.run)
    assert '"slug": slug' in src


def test_old_state_format_still_counts():
    """الملف القديم كان نص تاريخ، الجديد قاموس — الاتنين لازم يتقروا."""
    today = engage._today()
    state = {"companies": {
        "a": today + "T10:00:00+00:00",
        "b": {"at": today + "T11:00:00+00:00", "slug": "b-co"},
        "c": "2020-01-01T00:00:00+00:00",
    }}
    assert engage.done_today(state, "companies") == 2
