"""
اختبارات المتابعة.

الجدول ده هو الحقيقة الأرضية للمشروع كله. أي خلل هنا بيلوّث كل قياس
هيتبني عليه بعدين — والخلل ده مش بيبان في أي مكان تاني.
"""
import re

import pytest

from src import followup


# ── التوقيتات ───────────────────────────────────────────────────────────

def test_stages_are_ordered():
    """
    تأكيد بالساعات، نتيجة بالأيام، إغلاق بعدها.
    لو الترتيب اتقلب، هنسأل عن نتيجة تقديم لسه ماتأكدش إنه حصل.
    """
    confirm_days = followup.CONFIRM_AFTER_HOURS / 24
    assert confirm_days < followup.OUTCOME_AFTER_DAYS < followup.AUTO_CLOSE_DAYS


def test_confirm_window_is_same_day():
    """
    قريّب كفاية إنك لسه فاكر، وبعيد كفاية إنك خلصت أو استسلمت.
    """
    assert 0.25 <= followup.CONFIRM_AFTER_HOURS <= 6


def test_outcome_window_is_a_week_ish():
    """أقل من كده بدري على أي رد، وأكتر بتنسى."""
    assert 4 <= followup.OUTCOME_AFTER_DAYS <= 14


def test_auto_close_is_generous():
    """
    الإغلاق التلقائي بيسجّل "مفيش رد". لازم يبقى بعيد كفاية إن الرد
    الحقيقي يكون وصل — تسجيل "مفيش" بدري بيكذب على القياس.
    """
    assert followup.AUTO_CLOSE_DAYS >= 14


def test_batch_size_bounded():
    """5 أسئلة في الساعة مقبولة. 50 سبام."""
    assert 1 <= followup.MAX_PER_RUN <= 10


# ── الأزرار ─────────────────────────────────────────────────────────────

JOB = {"id": 42, "company_name": "Mozn", "title": "AI Engineer"}


def test_confirm_buttons():
    _, markup = followup.confirm_message(JOB)
    data = {b["callback_data"] for row in markup["inline_keyboard"] for b in row}
    assert data == {"c:42", "n:42"}


def test_outcome_buttons_cover_every_case():
    """
    كل نتيجة ممكنة ليها زرار. لو ناقصة واحدة، الحالة دي هتفضل مفتوحة
    لحد ما الإغلاق التلقائي يسجّلها "مفيش رد" — وده كذب.
    """
    _, markup = followup.outcome_message(JOB, 7)
    data = {b["callback_data"] for row in markup["inline_keyboard"] for b in row}
    assert data == {"or:42", "oi:42", "oj:42", "on:42"}


def test_outcome_keys_map_to_valid_values():
    """
    القيم دي عليها قيد check في الداتابيز. لو واحدة غلط، الكتابة
    بتترفض والضغطة بتضيع من غير ما حد ياخد باله.
    """
    allowed = {"reply", "interview", "offer", "rejected", "none"}
    assert set(followup.OUTCOME_KEYS.values()) <= allowed


@pytest.mark.parametrize("key", list(followup.OUTCOME_KEYS))
def test_outcome_keys_match_webhook_pattern(key):
    """
    نفس التعبير الموجود في الـ Edge Function. لو الاتنين اتفرقوا،
    الأزرار تبقى شغالة في الاختبارات وواقعة في الواقع.
    """
    assert re.fullmatch(r"[a-z]{1,2}", key)
    assert re.fullmatch(r"([a-z]{1,2}):(\d{1,12})", f"{key}:42")


def test_no_key_collision_between_stages():
    """حرف واحد للقرار، حرفين للنتيجة — مايتلخبطوش."""
    decide = {"a", "s", "l"}
    confirm = {"c", "n"}
    outcome = set(followup.OUTCOME_KEYS)
    assert not (decide | confirm) & outcome


# ── الرسايل ─────────────────────────────────────────────────────────────

def test_messages_escape_html():
    """اسم شركة فيه & أو < بيخلي تليجرام يرفض الرسالة كلها."""
    bad = JOB | {"company_name": "R&D <Labs>"}
    for text, _ in (followup.confirm_message(bad),
                    followup.outcome_message(bad, 7)):
        assert "<Labs>" not in text
        assert "&amp;" in text


def test_outcome_message_shows_the_wait():
    """الرقم بيفكّرك بالسياق — 7 يوم مش نفس 30."""
    text, _ = followup.outcome_message(JOB, 12)
    assert "12" in text


def test_messages_stay_short():
    for text, _ in (followup.confirm_message(JOB),
                    followup.outcome_message(JOB, 7)):
        assert len(text) < 400
