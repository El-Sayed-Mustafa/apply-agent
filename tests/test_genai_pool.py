"""
اختبارات تدوير مفاتيح Gemini.

القيد الحقيقي في المنظومة هو الحصة مش الذكاء: تشغيلة حصاد رجعت
13 فشل من 14 منشور، وكلها 429 — مش حكم غلط. الحصة اليومية بتتقاس
لكل مفتاح لوحده، فالتدوير بيضرب السقف في عدد المفاتيح.
"""
import pytest

from src import genai_pool


class FakeModels:
    def __init__(self, owner):
        self.owner = owner

    def generate_content(self, *, model, contents, config=None):
        return self.owner._answer(model)


class FakeClient:
    """عميل بيرمي أخطاء مبرمَجة حسب المفتاح."""

    def __init__(self, key, script):
        self.key = key
        self.script = script
        self.calls = 0
        self.models = FakeModels(self)

    def _answer(self, model):
        self.calls += 1
        err = self.script.get(self.key)
        if err:
            raise RuntimeError(err)
        return f"ok:{self.key}"


def pool_with(keys, script):
    p = genai_pool.Pool(keys)
    p._clients = {k: FakeClient(k, script) for k in keys}
    return p


DAILY = ("429 RESOURCE_EXHAUSTED quota_id: "
         "GenerateRequestsPerDayPerProjectPerModel")
MINUTE = ("429 RESOURCE_EXHAUSTED quota_id: "
          "GenerateRequestsPerMinutePerProjectPerModel")


# ── التمييز اللي كل حاجة بتتبنى عليه ────────────────────────────────────

def test_daily_and_minute_are_told_apart():
    """
    من غير التمييز ده، مفتاح خلصت حصته بيتجرّب تاني كل نداء —
    وتلات مفاتيح شغالة بتتحرق على انتظار مفتاح ميّت.
    """
    assert genai_pool.is_daily(DAILY)
    assert not genai_pool.is_daily(MINUTE)


# ── التدوير ─────────────────────────────────────────────────────────────

def test_falls_through_to_a_live_key():
    p = pool_with(["a", "b"], {"a": DAILY})
    assert p.models.generate_content(model="m", contents="x") == "ok:b"


def test_dead_key_is_not_retried():
    """المفتاح الميّت لازم يتعلّم عليه مرة واحدة بس."""
    p = pool_with(["a", "b"], {"a": DAILY})
    for _ in range(3):
        p.models.generate_content(model="m", contents="x")
    assert p._clients["a"].calls == 1
    assert p._clients["b"].calls == 3


def test_key_dies_per_model_not_globally():
    """
    الحصة اليومية لكل (مفتاح، موديل). لو علّمنا المفتاح ميّت على
    طول الخط، بنرمي حصة موديل تاني كاملة من غير سبب.
    """
    p = pool_with(["a"], {})
    p._dead.add(("a", "m1"))
    assert p.alive("m1") == 0
    assert p.alive("m2") == 1


def test_minute_limit_moves_on_without_killing_the_key():
    p = pool_with(["a", "b"], {"a": MINUTE})
    assert p.models.generate_content(model="m", contents="x") == "ok:b"
    assert ("a", "m") not in p._dead      # لسه عايش


def test_all_exhausted_raises_clearly():
    p = pool_with(["a", "b"], {"a": DAILY, "b": DAILY})
    with pytest.raises(Exception):
        p.models.generate_content(model="m", contents="x")
    with pytest.raises(RuntimeError, match="حصتها اليومية"):
        p.models.generate_content(model="m", contents="x")


def test_permanent_error_is_not_rotated():
    """
    مفتاح باطل أو طلب غلط مش هيتصلّح بمفتاح تاني — التدوير عليه
    بيخفي الغلط الحقيقي ورا أربع محاولات.
    """
    p = pool_with(["a", "b"], {"a": "400 INVALID_ARGUMENT bad request"})
    with pytest.raises(RuntimeError, match="INVALID_ARGUMENT"):
        p.models.generate_content(model="m", contents="x")
    assert p._clients["b"].calls == 0


# ── المفاتيح من البيئة ──────────────────────────────────────────────────

def test_keys_are_ordered_and_deduped(monkeypatch):
    # الـ.env الحقيقي فيه مفاتيح — لازم نفضّي الأول
    for v in genai_pool.KEY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "one")
    monkeypatch.setenv("GEMINI_API_KEY_2", "two")
    monkeypatch.setenv("GEMINI_API_KEY_3", "one")     # مكرر
    monkeypatch.setenv("GEMINI_API_KEY_4", "four")
    assert genai_pool.keys() == ["one", "two", "four"]


def test_no_keys_fails_loudly(monkeypatch):
    for v in genai_pool.KEY_VARS:
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        genai_pool.Pool()


def test_drop_in_shape():
    """
    الشكل لازم يفضل `client.models.generate_content` — منطق إعادة
    المحاولة في scoring مكتوب عليه، ومكنش ينفع يتعاد في أربع أماكن.
    """
    p = pool_with(["a"], {})
    assert hasattr(p, "models")
    assert callable(p.models.generate_content)
