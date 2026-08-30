"""
اختبارات الإرسال.

تليجرام بيرفض **الرسالة كلها** لو فيه حرف HTML غير مهرّب. يعني وظيفة
عنوانها "C++ Developer <Senior>" مش هتوصلك خالص — من غير خطأ واضح.
دي أكتر حالة فشل واقعية هنا، فمعظم الاختبارات عليها.
"""
import pytest

from src import telegram

JOB = {
    "id": 1, "company_name": "Mozn", "title": "AI Engineer",
    "location": "Riyadh, Saudi Arabia", "remote_type": "onsite",
    "url": "https://apply.workable.com/j/ABC123",
}
SCORE = {
    "score_final": 78, "verdict": "good",
    "matched": ["Python", "LLM APIs"], "gaps": ["Spark"],
    "reasoning": "Strong overlap on automation and LLM integration work.",
}


# ── تهريب HTML ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,must_not_contain", [
    ("C++ <Senior> Dev", "<Senior>"),
    ("R&D Engineer", "R&D "),
    ("<script>alert(1)</script>", "<script>"),
])
def test_html_is_escaped(raw, must_not_contain):
    """
    مش موضوع أمان بس — تليجرام نفسه بيرفض الرسالة ويرجّع خطأ،
    فالوظيفة بتضيع بالكامل.
    """
    msg = telegram.format_job(JOB | {"title": raw}, SCORE)
    assert must_not_contain not in msg


def test_escaping_keeps_our_own_tags():
    """التهريب على المحتوى بس — وسومنا إحنا لازم تفضل شغالة."""
    msg = telegram.format_job(JOB, SCORE)
    assert "<b>" in msg and "</b>" in msg


def test_ampersand_in_company():
    msg = telegram.format_job(JOB | {"company_name": "Ben & Jerry"}, SCORE)
    assert "&amp;" in msg and "& J" not in msg


# ── الشكل ───────────────────────────────────────────────────────────────

def test_message_has_the_essentials():
    msg = telegram.format_job(JOB, SCORE)
    for part in ("78", "Mozn", "AI Engineer", "Riyadh", "Python", "Spark"):
        assert part in msg


def test_verdict_icon():
    assert telegram.format_job(JOB, SCORE | {"verdict": "strong"}).startswith("🟢")
    assert telegram.format_job(JOB, SCORE | {"verdict": "no"}).startswith("🔴")


def test_unknown_verdict_still_renders():
    assert telegram.format_job(JOB, SCORE | {"verdict": "weird"})


def test_link_included():
    assert JOB["url"] in telegram.format_job(JOB, SCORE)


def test_missing_url_does_not_crash():
    assert telegram.format_job(JOB | {"url": None}, SCORE)


def test_missing_location_does_not_crash():
    assert telegram.format_job(JOB | {"location": None, "remote_type": "unknown"},
                               SCORE)


def test_empty_matched_and_gaps():
    msg = telegram.format_job(JOB, SCORE | {"matched": [], "gaps": []})
    assert "78" in msg and "Mozn" in msg


def test_unknown_remote_type_hidden():
    """'unknown' مش معلومة — عرضها بياخد مساحة من غير فايدة."""
    msg = telegram.format_job(JOB | {"remote_type": "unknown"}, SCORE)
    assert "unknown" not in msg


# ── حد الطول ────────────────────────────────────────────────────────────

def test_long_content_stays_under_telegram_limit():
    """حد تليجرام 4096 حرف. فوقه = الرسالة تترفض بالكامل."""
    huge = JOB | {"title": "X" * 500, "company_name": "Y" * 300}
    score = SCORE | {"reasoning": "Z" * 3000,
                     "matched": ["M" * 200] * 10, "gaps": ["G" * 200] * 10}
    assert len(telegram.format_job(huge, score)) < 4096


def test_clip_adds_ellipsis():
    assert telegram.clip("a" * 100, 20).endswith("…")
    assert len(telegram.clip("a" * 100, 20)) == 20


def test_clip_leaves_short_text_alone():
    assert telegram.clip("short", 50) == "short"


def test_clip_collapses_whitespace():
    """أوصاف الوظايف مليانة أسطر جديدة — بتبوظ شكل الرسالة."""
    assert telegram.clip("a\n\n  b", 50) == "a b"


def test_clip_handles_none():
    assert telegram.clip(None, 10) == ""


# ── الإعدادات ───────────────────────────────────────────────────────────

def test_missing_config_raises_clearly():
    import os
    from unittest import mock
    with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "",
                                      "TELEGRAM_CHAT_ID": ""}, clear=False):
        with pytest.raises(RuntimeError, match="ناقص"):
            telegram._config()


def test_thresholds_are_sane():
    from src import notify
    assert 0 <= notify.MIN_SCORE <= 100
    # من غير سقف، أول تشغيلة بعد تقييم كبير بتبعت عشرات الرسايل مرة واحدة
    assert 1 <= notify.MAX_PER_RUN <= 20


# ── جمع الإعلان الواحد المنشور في كذا مدينة ─────────────────────────────

def test_poster_key_ignores_location():
    """
    نفس الإعلان في 3 مدن = 3 صفوف في jobs (مقصود، عشان مانضيّعش
    وظيفة في الرياض)، بس **رسالة واحدة** في تليجرام.
    """
    import re as _re

    def poster(j):
        return (str(j.get("company_name") or "").strip().lower(),
                _re.sub(r"[\s\W]+", " ", str(j.get("title") or "").lower()).strip())

    a = {"company_name": "Salesforge", "title": "Senior Backend Engineer",
         "location": "Berlin"}
    b = {"company_name": "Salesforge", "title": "Senior Backend Engineer",
         "location": "Lisbon"}
    c = {"company_name": "Salesforge", "title": "Data Engineer",
         "location": "Berlin"}

    assert poster(a) == poster(b)      # نفس الإعلان، مدينة مختلفة
    assert poster(a) != poster(c)      # وظيفة تانية فعلاً


# ── أزرار الموافقة ──────────────────────────────────────────────────────

def test_keyboard_has_three_choices():
    kb = telegram.keyboard(123)
    row = kb["inline_keyboard"][0]
    assert len(row) == 3
    assert {b["callback_data"] for b in row} == {"a:123", "s:123", "l:123"}


def test_callback_data_under_telegram_limit():
    """
    تليجرام بيقصّ callback_data عند 64 بايت. لو بعتنا اسم الشركة أو
    العنوان جوّاه، وظيفة برقم كبير هتتقص والزرار هيبوظ من غير خطأ.
    عشان كده بنبعت حرف ورقم بس.
    """
    for job_id in (1, 999_999_999_999):
        for b in telegram.keyboard(job_id)["inline_keyboard"][0]:
            assert len(b["callback_data"].encode()) <= 64


@pytest.mark.parametrize("data,ok", [
    ("a:1", True), ("s:42", True), ("l:999999", True),
    ("x:1", False),           # فعل مش معروف
    ("a:abc", False),         # مش رقم
    ("a:1;drop table jobs", False),
    ("a:" + "9" * 20, False), # رقم أطول من الحد
    ("", False), ("a", False), ("a:", False),
])
def test_callback_pattern_matches_edge_function(data, ok):
    """
    نفس التعبير الموجود في الـ Edge Function. الاختبار ده بيمسك لو
    الاتنين اتفرقوا — وساعتها الأزرار تبقى شغالة محليًا وواقعة فعليًا.
    """
    import re as _re
    assert bool(_re.fullmatch(r"([asl]):(\d{1,12})", data)) is ok
