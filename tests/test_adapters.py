"""
اختبارات عقد المصادر.

الخطر الحقيقي في المشروع ده مش إن الكود يقع — إن نظام توظيف يغيّر شكل
الـ API من غير ما يقول لحد، فالسحب يفضل "ناجح" وهو راجع بوظايف فاضية
أو ناقصة. الاختبارات دي بتشتغل على عيّنات محفوظة من الـ APIs الحقيقية،
فلو الشكل اتغيّر بتقع فورًا.

مفيش إنترنت هنا — الشبكة مقفولة عن قصد.
"""
import json
from pathlib import Path

import pytest

from src import adapters

FIXTURES = Path(__file__).parent / "fixtures"

CASES = [
    ("greenhouse", adapters.fetch_greenhouse),
    ("lever", adapters.fetch_lever),
    ("ashby", adapters.fetch_ashby),
    ("recruitee", adapters.fetch_recruitee),
    ("workable", adapters.fetch_workable),
]


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


@pytest.fixture
def offline(monkeypatch):
    """أي محاولة نداء شبكة في الاختبارات = خطأ صريح."""
    def blocked(*a, **k):
        raise AssertionError("الاختبارات مالهاش حق تنادي الشبكة")
    monkeypatch.setattr(adapters.requests, "get", blocked)


def load(ats: str, monkeypatch):
    payload = json.loads((FIXTURES / f"{ats}.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(adapters, "_get", lambda url: FakeResponse(payload))


@pytest.mark.parametrize("ats,fn", CASES)
def test_returns_jobs(ats, fn, monkeypatch, offline):
    load(ats, monkeypatch)
    jobs = fn("TestCo", "token")
    assert jobs, f"{ats}: رجّع صفر وظيفة من عيّنة فيها وظايف"


@pytest.mark.parametrize("ats,fn", CASES)
def test_required_fields_present(ats, fn, monkeypatch, offline):
    """
    العنوان والبصمة هما الحد الأدنى. من غيرهم الصف مش هيدخل الداتابيز
    أصلاً (not null)، فالأحسن نمسكها هنا.
    """
    load(ats, monkeypatch)
    for j in fn("TestCo", "token"):
        assert j.company_name == "TestCo"
        assert j.ats == ats
        assert j.title.strip(), f"{ats}: وظيفة من غير عنوان"
        assert len(j.content_hash) == 64
        assert j.external_id is not None


@pytest.mark.parametrize("ats,fn", CASES)
def test_description_extracted(ats, fn, monkeypatch, offline):
    """
    الوصف هو مدخل التقييم كله. لو رجع فاضي، التقييم هيدي أرقام
    من العنوان بس — وهيبان معقول وهو غلط تمامًا.
    """
    load(ats, monkeypatch)
    jobs = fn("TestCo", "token")
    assert any(len(j.description) > 50 for j in jobs), \
        f"{ats}: كل الأوصاف فاضية أو قصيرة — الشكل اتغيّر غالبًا"


@pytest.mark.parametrize("ats,fn", CASES)
def test_no_html_left_in_description(ats, fn, monkeypatch, offline):
    """الـ HTML لازم يتشال — الموديل مش المفروض يقرا وسوم."""
    load(ats, monkeypatch)
    for j in fn("TestCo", "token"):
        assert "<p>" not in j.description
        assert "<div" not in j.description


@pytest.mark.parametrize("ats,fn", CASES)
def test_remote_type_is_valid(ats, fn, monkeypatch, offline):
    load(ats, monkeypatch)
    allowed = {"remote", "hybrid", "onsite", "unknown"}
    for j in fn("TestCo", "token"):
        assert j.remote_type in allowed


@pytest.mark.parametrize("ats,fn", CASES)
def test_hashes_unique_within_source(ats, fn, monkeypatch, offline):
    """وظيفتين مختلفتين في نفس السحبة مايبقاش ليهم نفس البصمة."""
    load(ats, monkeypatch)
    jobs = fn("TestCo", "token")
    if len(jobs) > 1:
        assert len({j.content_hash for j in jobs}) == len(jobs)


@pytest.mark.parametrize("ats,fn", CASES)
def test_empty_board_is_not_an_error(ats, fn, monkeypatch, offline):
    """
    شركة مقفلة التوظيف مؤقتًا = صفر وظيفة، مش استثناء.
    الفرق مهم: صفر = عادي، استثناء = الـ token باظ.
    """
    empty = {"jobs": [], "offers": []} if ats != "lever" else []
    monkeypatch.setattr(adapters, "_get", lambda url: FakeResponse(empty))
    assert fn("TestCo", "token") == []


# ── التوجيه ─────────────────────────────────────────────────────────────

def test_unknown_ats_raises():
    with pytest.raises(ValueError, match="غير مدعوم"):
        adapters.fetch({"name": "X", "ats": "monster", "token": "t"})


def test_every_adapter_is_registered():
    """adapter اتكتب ومتسجّلش = شغل ضايع ومفيش حد هيلاحظ."""
    for ats, _ in CASES:
        assert ats in adapters.ADAPTERS


# ── تصنيف الريموت ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Remote - Europe", "remote"),
    ("Hybrid, Riyadh", "hybrid"),
    ("Riyadh, On-site", "onsite"),
    ("Cairo, Egypt", "unknown"),
    ("Remote hybrid setup", "hybrid"),   # hybrid بتكسب remote
])
def test_guess_remote(text, expected):
    assert adapters._guess_remote(text) == expected
