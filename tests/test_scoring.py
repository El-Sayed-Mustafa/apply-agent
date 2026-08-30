"""
اختبارات المقيّم.

مفيش نداءات موديل هنا. اللي بيتختبر هو المنطق اللي حوالين النداء —
وده اللي بيقع فعلاً: التفريق بين حد الدقيقة وحد اليوم، التعامل مع
سكور بره المدى، ومنع البيانات الشخصية من إنها تتبعت.
"""
import pytest

from src import scoring


class FakeResp:
    def __init__(self, text, tokens=100):
        self.text = text
        self.usage_metadata = type("U", (), {"total_token_count": tokens})()


class FakeModels:
    """بيرمي/بيرجّع حسب سيناريو معرّف مسبقًا."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        item = self.script.pop(0) if self.script else FakeResp('{"score":50,'
            '"verdict":"partial","matched":[],"gaps":[],"reasoning":"x"}')
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, script):
        self.models = FakeModels(script)


GOOD = '{"score":78,"verdict":"good","matched":["Python"],"gaps":["Spark"],"reasoning":"ok"}'
JOB = {"title": "AI Engineer", "company_name": "Mozn",
       "location": "Riyadh", "remote_type": "onsite", "description": "Build AI."}


# ── التفريق بين حد الدقيقة وحد اليوم ────────────────────────────────────

def test_per_minute_limit_is_not_daily():
    """
    الفرق ده هو كل الحكاية: حد الدقيقة بيتحل بالانتظار 30 ثانية.
    لو عاملناه كحد يومي، هنحرق الموديل من غير سبب.
    """
    msg = ("429 RESOURCE_EXHAUSTED quotaId: "
           "GenerateRequestsPerMinutePerProjectPerModel 'retryDelay': '13s'")
    assert not scoring._is_daily_quota(msg)


@pytest.mark.parametrize("msg", [
    "429 quotaId: GenerateRequestsPerDayPerProject",
    "429 exceeded your daily quota",
    "429 RESOURCE_EXHAUSTED 'retryDelay': '3600s'",   # مهلة طويلة = يومي عمليًا
])
def test_daily_limit_detected(msg):
    assert scoring._is_daily_quota(msg)


def test_non_429_is_never_daily():
    assert not scoring._is_daily_quota("503 UNAVAILABLE model overloaded")


@pytest.mark.parametrize("msg,expected", [
    ("'retryDelay': '13s'", 13.0),
    ('"retryDelay": "12.8s"', 12.8),
    ("no hint here", None),
])
def test_retry_delay_parsing(msg, expected):
    assert scoring._retry_delay(msg) == expected


# ── التنقل بين الموديلات ────────────────────────────────────────────────

def test_falls_through_to_next_model_on_daily_quota():
    """أول موديل حصته خلصت → لازم يجرّب اللي بعده فورًا."""
    err = Exception("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProject")
    client = FakeClient([err, FakeResp(GOOD)])
    out, _, _, model = scoring.score_job(client, "cv", JOB, ["m1", "m2"])
    assert out["score"] == 78
    assert client.models.calls == ["m1", "m2"]
    assert model == "m2"


def test_all_models_exhausted_reports_clearly():
    err = Exception("429 GenerateRequestsPerDayPerProject")
    client = FakeClient([err, err, err])
    out, _, msg, _ = scoring.score_job(client, "cv", JOB, ["m1", "m2"])
    assert out is None and msg.startswith("كل الموديلات")


def test_permanent_error_does_not_burn_other_models():
    """
    مفتاح غلط أو موديل مش موجود مش هيتصلح بتجربة موديل تاني.
    لو جرّبنا الكل، بنضيّع وقت ونداءات على غلطة أكيدة.
    """
    client = FakeClient([Exception("400 INVALID_ARGUMENT bad key")])
    out, _, _, _ = scoring.score_job(client, "cv", JOB, ["m1", "m2", "m3"])
    assert out is None
    assert client.models.calls == ["m1"]


# ── التحقق من المخرج ────────────────────────────────────────────────────

def test_valid_score_accepted():
    out, tokens, err, _ = scoring.score_job(
        FakeClient([FakeResp(GOOD, 250)]), "cv", JOB, ["m"])
    assert out["score"] == 78 and tokens == 250 and err == ""


@pytest.mark.parametrize("bad", [
    '{"score":150,"verdict":"good","matched":[],"gaps":[],"reasoning":"x"}',
    '{"score":-5,"verdict":"good","matched":[],"gaps":[],"reasoning":"x"}',
    '{"score":"high","verdict":"good","matched":[],"gaps":[],"reasoning":"x"}',
])
def test_out_of_range_score_rejected(bad):
    """
    المخطط بيفرض الشكل، مش المعنى. "integer" مبتمنعش 150.
    لو عدّت، هتكسر ترتيب الوظايف كله من غير ما حد يلاحظ.
    """
    out, _, err, _ = scoring.score_job(FakeClient([FakeResp(bad)]), "cv", JOB, ["m"])
    assert out is None and "المدى" in err


def test_broken_json_rejected():
    out, _, err, _ = scoring.score_job(
        FakeClient([FakeResp("{not json")]), "cv", JOB, ["m"])
    assert out is None and "JSON" in err


# ── السيرة الذاتية ──────────────────────────────────────────────────────

def test_cv_loads():
    cv = scoring.load_cv()
    assert "Python" in cv and len(cv) > 200


def test_cv_has_no_contact_details():
    """
    تقليل البيانات: المقيّم مش هيقيّم وظيفة أحسن لأنه عارف إيميلك.
    كل حقل زيادة بيتبعت = تعرّض من غير مقابل.
    """
    cv = scoring.load_cv().lower()
    for leak in ("@", "phone", "+20", "linkedin.com", "github.com"):
        assert leak not in cv, f"السيرة فيها {leak}"


def test_prompt_includes_job_and_cv():
    p = scoring.build_prompt("MY_CV_MARKER", JOB)
    assert "MY_CV_MARKER" in p
    assert "AI Engineer" in p and "Mozn" in p and "Riyadh" in p


def test_prompt_truncates_huge_description():
    """إعلان ضخم مايفجّرش التكلفة."""
    p = scoring.build_prompt("cv", JOB | {"description": "x" * 100_000})
    assert len(p) < 20_000


def test_prompt_handles_missing_location():
    p = scoring.build_prompt("cv", {"title": "T", "company_name": "C",
                                    "location": None, "description": "d"})
    assert "not stated" in p


# ── الإعدادات ───────────────────────────────────────────────────────────

def test_models_list_not_empty():
    assert scoring.MODELS and scoring.MODEL == scoring.MODELS[0]


def test_attempt_cap_prevents_infinite_retry():
    """
    وظيفة بتكسّر الموديل لازم تتوقف بعد عدد محاولات — من غير كده
    هتتحاول كل ساعة للأبد وتاكل الحصة اليومية كلها.
    """
    assert 1 <= scoring.MAX_ATTEMPTS <= 5


def test_time_budget_fits_workflow():
    """مهلة الـ workflow 10 دقايق، والسحب بياخد منها."""
    assert scoring.TIME_BUDGET <= 540


# ── جودة الموديل ────────────────────────────────────────────────────────

def test_weak_models_not_in_rotation():
    """
    flash-lite قِسناه: طلّع Python صفر مرة من 45 إعلان بتذكرها.
    ولما كان في القايمة، عمل 173 من 234 تقييم — لأن الكويسين بيخلصوا
    حصتهم بسرعة فالتنقّل بيسقط عليه.
    """
    for weak in scoring.WEAK_MODELS:
        assert weak not in scoring.MODELS, f"{weak} رجع للقايمة"


def test_weak_model_list_not_empty():
    """لو القايمة فضيت، إعادة التقييم مش هتشتغل على حاجة."""
    assert scoring.WEAK_MODELS


def test_refuter_is_a_switch():
    """
    لازم نقدر نقفله عشان نقيس: شهر شغال، شهر مقفول، وقارن.
    لو مفيش فرق في دقة التوقع — نقفله ونوفّر نص التكلفة.
    """
    assert isinstance(scoring.REFUTE, bool)


def test_cv_version_changes_with_the_file(tmp_path):
    """بصمة مختلفة لملف مختلف — عشان مانخلطش تقييمات على بيانات مختلفة."""
    a = tmp_path / "a.yaml"; a.write_text("profile:\n  title: X\n", encoding="utf-8")
    b = tmp_path / "b.yaml"; b.write_text("profile:\n  title: Y\n", encoding="utf-8")
    assert scoring.cv_version(str(a)) != scoring.cv_version(str(b))
    assert scoring.cv_version(str(a)) == scoring.cv_version(str(a))
