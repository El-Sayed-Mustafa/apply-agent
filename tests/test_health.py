"""
اختبارات مراقبة صحة المصادر.

الفكرة: الفشل الصامت أخطر من الفشل الصريح. مصدر بيرمي استثناء بتشوفه
فورًا؛ مصدر بيرجّع 3 وظايف بدل 248 بيعدّي كأنه ناجح.
"""
import pytest

from src import main


class FakeQuery:
    """محاكاة سلسلة استعلامات supabase — كلها بترجّع نفسها لحد execute."""

    def __init__(self, data, fail=False):
        self._data = data
        self._fail = fail

    def __getattr__(self, _):
        return lambda *a, **k: self

    def execute(self):
        if self._fail:
            raise ConnectionError("الداتابيز مش راضية")
        return type("R", (), {"data": self._data})()


class FakeClient:
    def __init__(self, data, fail=False):
        self._q = FakeQuery(data, fail)

    def table(self, _):
        return self._q


def prev_run(**counts):
    """تشغيلة سابقة بالأرقام دي."""
    return [{"detail": {"sources": [{"company": c, "status": "ok", "count": n}
                                    for c, n in counts.items()]}}]


def now(**counts):
    return [{"company": c, "status": "ok", "count": n} for c, n in counts.items()]


# ── لازم تصحّى ──────────────────────────────────────────────────────────

def test_big_drop_is_flagged():
    """248 → 3. ده اللي المراقبة موجودة عشانه."""
    client = FakeClient(prev_run(ElevenLabs=248))
    alerts = main.check_health(client, now(ElevenLabs=3))
    assert len(alerts) == 1
    assert "ElevenLabs" in alerts[0] and "99%" in alerts[0]


def test_source_going_to_zero_is_flagged():
    client = FakeClient(prev_run(Mozn=14))
    assert main.check_health(client, now(Mozn=0))


def test_multiple_drops_all_reported():
    client = FakeClient(prev_run(Mozn=14, Cohere=146))
    assert len(main.check_health(client, now(Mozn=2, Cohere=10))) == 2


# ── مالهاش حق تصحّى ─────────────────────────────────────────────────────

def test_stable_source_is_quiet():
    client = FakeClient(prev_run(Cohere=146))
    assert main.check_health(client, now(Cohere=144)) == []


def test_growth_is_never_an_alert():
    """الشركة فتحت توظيف — خبر حلو مش مشكلة."""
    client = FakeClient(prev_run(Mozn=14))
    assert main.check_health(client, now(Mozn=40)) == []


def test_exactly_half_is_not_flagged():
    """الحد أقل من النص. 146 → 73 بالظبط مايتبلغش عنه."""
    client = FakeClient(prev_run(Cohere=146))
    assert main.check_health(client, now(Cohere=73)) == []


def test_tiny_source_ignored():
    """
    Lean Tech عندها 4 وظايف. تنزل 1 ده تذبذب طبيعي مش عطل.
    من غير الحد ده، البورد الصغيرة هتزنّ كل يوم لحد ما تتجاهل التنبيهات كلها.
    """
    client = FakeClient(prev_run(LeanTech=4))
    assert main.check_health(client, now(LeanTech=1)) == []


# ── الحالات الحدية ──────────────────────────────────────────────────────

def test_no_history_is_silent():
    """أول تشغيلة في حياة المشروع — مفيش حاجة تتقارن بيها."""
    assert main.check_health(FakeClient([]), now(Mozn=14)) == []


def test_new_source_is_silent():
    """شركة اتضافت النهاردة — مالهاش تاريخ."""
    client = FakeClient(prev_run(Mozn=14))
    assert main.check_health(client, now(Mozn=14, Tamara=38)) == []


def test_removed_source_does_not_crash():
    """شركة اتشالت من السجل."""
    client = FakeClient(prev_run(Mozn=14, Gone=100))
    assert main.check_health(client, now(Mozn=14)) == []


def test_db_error_does_not_break_the_run():
    """
    المراقبة حاجة كمالية. لو مقدرناش نقرا التاريخ، السحب لازم يكمّل —
    مش منطقي إن أداة تنبيه توقّف الشغل الأصلي.
    """
    assert main.check_health(FakeClient([], fail=True), now(Mozn=14)) == []


def test_malformed_history_does_not_crash():
    """صف قديم بشكل مختلف."""
    client = FakeClient([{"detail": None}])
    assert main.check_health(client, now(Mozn=14)) == []
