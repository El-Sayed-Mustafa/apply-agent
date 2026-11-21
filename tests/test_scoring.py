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


# ── أولوية التقييم ──────────────────────────────────────────────────────

def test_priority_favours_measured_producers():
    """
    537 ألف توكن اتحرقوا على مصادر ماطلّعتش ولا فرصة. المصادر
    اللي أثبتت نفسها لازم تتقيّم الأول — لو الحصة خلصت، تخلص
    على الأحسن مش على الأقدم في الطابور.
    """
    P = scoring.PRIORITY
    assert P["linkedin_post"] < P["greenhouse"]
    assert P["remoteok"] < P["greenhouse"]
    assert P["ashby"] < P["himalayas"]


def test_unknown_source_is_not_starved():
    """
    مصدر جديد لسه مالوش تاريخ لازم ياخد فرصة — مش يتحط في الآخر
    وميتقيّمش أبدًا فيفضل من غير تاريخ للأبد.
    """
    assert scoring.DEFAULT_PRIORITY < max(scoring.PRIORITY.values())


def test_queue_sorted_by_priority(monkeypatch):
    """الطابور بيرتّب بالمصدر، وبعدين بالأحدث."""
    rows = [
        {"id": 9, "ats": "greenhouse", "title": "AI Engineer", "location": "Remote",
         "remote_type": "remote", "description": "python", "company_name": "A"},
        {"id": 3, "ats": "remoteok", "title": "AI Engineer", "location": "Remote",
         "remote_type": "remote", "description": "python", "company_name": "B"},
    ]
    ordered = sorted(rows, key=lambda r: (
        scoring.PRIORITY.get(r["ats"], scoring.DEFAULT_PRIORITY), -r["id"]))
    assert [r["ats"] for r in ordered] == ["remoteok", "greenhouse"]


# ── سقف الألف صف ────────────────────────────────────────────────────────

class _Q:
    """استعلام مزيّف بيقلّد سقف PostgREST: 1000 صف في النداء، بصمت."""

    CAP = 1000

    def __init__(self, rows):
        self.rows = list(rows)
        self._range = None

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def gte(self, col, val):
        self.rows = [r for r in self.rows if r.get(col, 0) >= val]
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self.rows = [r for r in self.rows if r.get(col) in vals]
        return self

    def order(self, col, desc=False):
        self.rows.sort(key=lambda r: r[col], reverse=desc)
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def limit(self, n):
        self._range = (0, n - 1)
        return self

    def execute(self):
        rows = self.rows
        if self._range:
            a, b = self._range
            rows = rows[a:b + 1]
        return type("R", (), {"data": rows[:self.CAP]})()


class _DB:
    def __init__(self, **tables):
        self.tables = tables

    def table(self, name):
        return _Q(self.tables.get(name, []))


def _job(i):
    return {"id": i, "company_name": "X", "title": "AI Engineer",
            "location": "", "remote_type": "remote", "description": "d"}


def test_scored_jobs_past_row_1000_stay_out_of_the_queue(monkeypatch):
    """
    اتقاست: scores فيه 1114 صف، والنداء الواحد بيرجّع 1000. الـ114
    الزيادة كانوا بيتعاد تقييمهم كل تشغيلة — 8 وظايف اتقيّموا 13:44
    و7 منهم اتقيّموا تاني 13:51 — والحصة اليومية 40 طلب بس.
    """
    monkeypatch.setattr(scoring.targeting, "evaluate",
                        lambda job: type("E", (), {"eligible": True})())
    v = scoring.SCORER_VERSION
    db = _DB(
        jobs=[_job(i) for i in range(1, 1104)],
        scores=[{"job_id": i, "model": "gemini-3.6-flash",
                 "scorer_version": v} for i in range(1, 1101)],
    )
    got = [j["id"] for j in scoring.pending(db, 40)]
    assert got == [1103, 1102, 1101]


def test_burned_jobs_past_row_1000_stay_out_too(monkeypatch):
    """نفس السقف على score_attempts: وظيفة فشلت 3 مرات متتجرّبش تاني."""
    monkeypatch.setattr(scoring.targeting, "evaluate",
                        lambda job: type("E", (), {"eligible": True})())
    v = scoring.SCORER_VERSION
    db = _DB(
        jobs=[_job(i) for i in range(1, 1103)],
        score_attempts=[{"job_id": i, "attempts": scoring.MAX_ATTEMPTS,
                         "scorer_version": v} for i in range(1, 1101)],
    )
    assert [j["id"] for j in scoring.pending(db, 40)] == [1102, 1101]


def test_descriptions_fetched_only_for_jobs_that_could_pass():
    """
    الأوصاف هي الحجم كله في نقل البيانات، وSupabase وقف المشروع يوم
    23 أكتوبر على exceed_egress_quota. الوظيفة اللي عنوانها أو مكانها
    بيرفضها مالهاش لازمة ننزّل وصفها.
    """
    jobs = [
        {"id": 3, "company_name": "A", "title": "AI Engineer",
         "location": "Riyadh", "remote_type": "onsite", "description": "d"},
        {"id": 2, "company_name": "B", "title": "Sales Manager",
         "location": "Riyadh", "remote_type": "onsite", "description": "d"},
        {"id": 1, "company_name": "C", "title": "AI Engineer",
         "location": "Bucharest, Romania", "remote_type": "onsite",
         "description": "d"},
    ]
    asked = []

    class DB(_DB):
        def table(self, name):
            q = super().table(name)
            if name == "jobs":
                real = q.in_

                def spy(col, vals):
                    if col == "id":              # مش فلتر المصدر
                        asked.extend(vals)
                    return real(col, vals)
                q.in_ = spy
            return q

    got = scoring.pending(DB(jobs=jobs, scores=[]), 40)
    assert [j["id"] for j in got] == [3]
    assert asked == [3]                      # وصف واحد بس اتنزّل
    assert got[0]["description"] == "d"


# ── حقايق الوظيفة والسقف ───────────────────────────────────────────────

def test_ai_training_gigs_and_internships_are_capped_in_code():
    """الذاكرة: وظايف تدريب و"AI Training" كانت بتاخد تقييم عالي."""
    job = {"location": "Riyadh", "remote_type": "onsite"}
    for kind in ("internship", "graduate_program", "ai_training_gig"):
        assert scoring.cap_by_facts(88, job, {"employment_type": kind}) == scoring.FACT_CAP
    assert scoring.cap_by_facts(88, job, {"employment_type": "full_time"}) == 88


def test_remote_closed_to_egypt_is_capped_unless_onsite_in_the_gulf():
    facts = {"employment_type": "full_time", "remote_scope": "excludes_egypt"}
    remote = {"location": "United States", "remote_type": "remote"}
    dubai = {"location": "Dubai, UAE", "remote_type": "onsite"}
    assert scoring.cap_by_facts(80, remote, facts) == scoring.FACT_CAP
    assert scoring.cap_by_facts(80, dubai, facts) == 80


def test_missing_facts_change_nothing():
    assert scoring.cap_by_facts(77, {}, None) == 77


def test_scorer_sees_skill_levels_but_never_contact_details():
    text = scoring.load_cv()
    assert "skill_levels" in text and "developing" in text
    assert "@gmail.com" not in text and "+20" not in text
    assert "Apply Agent" not in text            # مشروع متعطّل


def test_schema_asks_for_facts():
    assert "facts" in scoring.SCHEMA["required"]
    assert "ai_training_gig" in scoring.EMPLOYMENT


def test_gulf_and_local_sources_are_scored_before_global_feeds(monkeypatch):
    """
    اتقاس 21 نوفمبر: 400+ وظيفة مستنية، والأحدث كانت دايمًا من Lever
    وGreenhouse — فوظايف Bayt وLinkedIn الخليج ماكانتش بتوصل للتقييم.
    """
    monkeypatch.setattr(scoring.targeting, "evaluate",
                        lambda job: type("E", (), {"eligible": True})())
    jobs = [
        {"id": 9, "ats": "lever", "company_name": "A", "title": "AI Engineer",
         "location": "Berlin, Germany", "remote_type": "onsite", "description": "d"},
        {"id": 8, "ats": "greenhouse", "company_name": "B", "title": "AI Engineer",
         "location": "Remote", "remote_type": "remote", "description": "d"},
        {"id": 7, "ats": "ashby", "company_name": "C", "title": "AI Engineer",
         "location": "Dubai, UAE", "remote_type": "onsite", "description": "d"},
        {"id": 6, "ats": "bayt", "company_name": "D", "title": "AI Engineer",
         "location": "", "remote_type": "unknown", "description": "d",
         "first_seen_at": "2999-01-01"},
    ]
    monkeypatch.setattr(scoring.targeting, "could_pass", lambda *a: True)
    got = [j["id"] for j in scoring.pending(_DB(jobs=jobs, scores=[]), 3)]
    assert got == [7, 6, 8]


def test_a_reposted_job_copies_its_old_score_instead_of_asking(monkeypatch):
    """RemoteOK: "Platform and Integration Engineer" اتقيّم 7 مرات في أسبوع."""
    monkeypatch.setattr(scoring.targeting, "evaluate",
                        lambda job: type("E", (), {"eligible": True})())
    monkeypatch.setattr(scoring.targeting, "could_pass", lambda *a: True)
    v = scoring.SCORER_VERSION
    old = {"id": 1, "company_name": "Acme", "title": "Platform Engineer",
           "location": "Remote", "remote_type": "remote", "description": "d"}
    new = {**old, "id": 2, "title": "Platform  Engineer!"}        # نفس الإعلان
    other = {**old, "id": 3, "title": "AI Engineer"}
    db = _DB(jobs=[old, new, other],
             scores=[{"job_id": 1, "model": "gemini-3.6-flash", "scorer_version": v,
                      "created_at": "2999-01-01", "score_final": 33, "verdict": "weak"}])
    got = [j["id"] for j in scoring.pending(db, 10)]
    assert got == [3]
    assert [(j["id"], s["score_final"]) for j, s in scoring.pending.repeats] == [(2, 33)]


# ── 21 نوفمبر: الفرز السريع قبل التقييم ────────────────────────────────

class _TriageModels:
    def __init__(self, reply=None, fail=False):
        self.reply, self.fail, self.calls = reply, fail, []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        if self.fail:
            raise RuntimeError("503 UNAVAILABLE")
        return type("R", (), {"text": self.reply})()


def test_triage_drops_only_what_the_model_rejects_in_one_call():
    import json
    jobs = [{"id": i, "title": f"T{i}", "company_name": "C", "location": "Dubai",
             "remote_type": "onsite", "description": "d"} for i in range(1, 4)]
    reply = json.dumps({"jobs": [{"n": 1, "keep": True, "reason": "ok"},
                                 {"n": 2, "keep": False, "reason": "needs 8 years"}]})
    m = _TriageModels(reply)          # رقم 3 مارجعش — يعدّي (مش بنرمي من غير سبب)
    keep, drop, calls = scoring.triage(type("C", (), {"models": m})(), jobs, models=["lite"])
    assert [j["id"] for j in keep] == [1, 3] and calls == 1
    assert [(j["id"], why) for j, why in drop] == [(2, "needs 8 years")]


def test_triage_failure_lets_everything_through():
    jobs = [{"id": 1, "title": "T", "company_name": "C", "description": "d"}]
    m = _TriageModels(fail=True)
    keep, drop, _ = scoring.triage(type("C", (), {"models": m})(), jobs, models=["a", "b"])
    assert keep == jobs and drop == [] and m.calls == ["a", "b"]


def test_triage_uses_lite_models_that_have_their_own_quota():
    assert scoring.TRIAGE_MODELS and all("lite" in m for m in scoring.TRIAGE_MODELS)
    assert not set(scoring.TRIAGE_MODELS) & set(scoring.MODELS)
