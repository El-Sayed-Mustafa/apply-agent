"""
اختبارات السجل ومنطق إزالة التكرار — الجزء اللي بين السحب والحفظ.
"""
import textwrap

import pytest

from src import main
from src.adapters import Job


def job(**over) -> Job:
    base = dict(company_name="Mozn", ats="workable", external_id="1",
                title="AI Engineer", location="Riyadh", description="Build things.")
    base.update(over)
    return Job(**base)


# ── قراءة السجل ─────────────────────────────────────────────────────────

def write_registry(tmp_path, monkeypatch, body: str):
    p = tmp_path / "companies.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setattr(main, "REGISTRY_PATH", str(p))
    return p


def test_registry_loads(tmp_path, monkeypatch):
    write_registry(tmp_path, monkeypatch, """
        companies:
          - name: Mozn
            ats: workable
            token: mozn-ai
            tier: 1
    """)
    c = main.load_companies()
    assert len(c) == 1 and c[0]["name"] == "Mozn"


def test_tier_defaults_to_2(tmp_path, monkeypatch):
    write_registry(tmp_path, monkeypatch, """
        companies:
          - name: Mozn
            ats: workable
            token: mozn-ai
    """)
    assert main.load_companies()[0]["tier"] == 2


@pytest.mark.parametrize("missing", ["name", "ats", "token"])
def test_missing_field_raises(tmp_path, monkeypatch, missing):
    """
    شركة ناقصة حقل لازم توقّف التشغيل فورًا، مش تتخطى بهدوء.
    غلطة في ملف نصي أسهل بكتير إنها تتصلّح دلوقتي من إنك تكتشف بعد
    أسبوعين إن شركة كانت مش بتتسحب.
    """
    fields = {"name": "Mozn", "ats": "workable", "token": "mozn-ai"}
    del fields[missing]
    body = "companies:\n  - " + "\n    ".join(f"{k}: {v}" for k, v in fields.items())
    write_registry(tmp_path, monkeypatch, body)
    with pytest.raises(ValueError, match=missing):
        main.load_companies()


def test_empty_registry_is_allowed(tmp_path, monkeypatch):
    """سجل فاضي = مفيش شغل، مش خطأ."""
    write_registry(tmp_path, monkeypatch, "companies: []")
    assert main.load_companies() == []


# ── إزالة التكرار جوّا السحبة ───────────────────────────────────────────

def test_dedupe_removes_repeat():
    """مصدر رجّع نفس الوظيفة مرتين في نفس النداء."""
    jobs = [job(external_id="1"), job(external_id="2")]   # نفس المحتوى
    assert len(main.dedupe_in_batch(jobs)) == 1


def test_dedupe_keeps_first():
    jobs = [job(external_id="first"), job(external_id="second")]
    assert main.dedupe_in_batch(jobs)[0].external_id == "first"


def test_dedupe_keeps_different_locations():
    """
    القرار المعماري بيتحقق هنا من الآخر: نفس الوظيفة في مدينتين
    لازم الاتنين يعدّوا.
    """
    jobs = [job(location="Riyadh"), job(location="Cairo")]
    assert len(main.dedupe_in_batch(jobs)) == 2


def test_dedupe_empty():
    assert main.dedupe_in_batch([]) == []


# ── تجميع المصادر ───────────────────────────────────────────────────────

def test_collect_survives_one_broken_source(monkeypatch):
    """
    مصدر واحد وقع مايوقّفش الباقي. لو 10 شركات وواحدة API بتاعها نازل،
    التسع الباقيين لازم يتسحبوا.
    """
    def fake_fetch(c):
        if c["name"] == "Broken":
            raise ConnectionError("boom")
        return [job(company_name=c["name"])]

    monkeypatch.setattr(main, "fetch", fake_fetch)
    jobs, report = main.collect([
        {"name": "Good", "ats": "ashby", "token": "a"},
        {"name": "Broken", "ats": "lever", "token": "b"},
        {"name": "Also Good", "ats": "greenhouse", "token": "c"},
    ])

    assert len(jobs) == 2
    assert [r["status"] for r in report] == ["ok", "failed", "ok"]


def test_collect_marks_empty_separately(monkeypatch):
    """
    فرق مهم: 'empty' يعني الـ token اشتغل بس البورد فاضي.
    'failed' يعني الـ token غلط. الاتنين محتاجين رد فعل مختلف.
    """
    monkeypatch.setattr(main, "fetch", lambda c: [])
    _, report = main.collect([{"name": "Quiet", "ats": "ashby", "token": "q"}])
    assert report[0]["status"] == "empty"
