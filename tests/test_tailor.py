"""
اختبارات تظبيط السيرة.

أهم اختبار في المشروع كله هو `validate`. لو عدّى معرّف مخترع، معناه
إن فيه سطر في سيرتك مالوش أصل في cv.yaml — يعني ادّعاء خبرة مش
موجودة، وإنت مش شايفه.

ده test مش eval: مفيش "نسبة نجاح" مقبولة هنا. لازم 100%.
"""
import re

import pytest

from src import render, tailor

KNOWN = {
    "b1": {"text": "بناء أنظمة أتمتة", "parent": "AI Engineer", "block": "experience"},
    "b2": {"text": "تكاملات LLM", "parent": "AI Engineer", "block": "experience"},
    "b7": {"text": "Meeting Copilot", "parent": "Copilot", "block": "projects"},
}


# ── الحاجز ──────────────────────────────────────────────────────────────

def test_valid_ids_pass():
    kept, dropped = tailor.validate(["b1", "b2"], KNOWN)
    assert kept == ["b1", "b2"] and dropped == []


@pytest.mark.parametrize("fake", [
    "b99",                     # معرّف مش موجود
    "b1x",                     # قريب من موجود
    "B1",                      # حالة أحرف مختلفة
    "",                        # فاضي
    "'; drop table jobs; --",  # حقن
    "../../etc/passwd",
])
def test_invented_ids_are_dropped(fake):
    """
    ده الحاجز اللي بيخلي الاختلاق مستحيل هندسيًا.
    الموديل مش بيكتب نص أصلاً — بيرجّع معرّفات، والمعرّف اللي
    مش في الكتالوج بيتشال.
    """
    kept, dropped = tailor.validate([fake], KNOWN)
    assert kept == [] and dropped == [fake]


def test_mixture_keeps_only_the_real():
    kept, dropped = tailor.validate(["b1", "b99", "b2", "fake"], KNOWN)
    assert kept == ["b1", "b2"]
    assert dropped == ["b99", "fake"]


def test_duplicates_removed():
    """نفس النقطة مرتين في السيرة = شكل وحش."""
    kept, _ = tailor.validate(["b1", "b1", "b2"], KNOWN)
    assert kept == ["b1", "b2"]


def test_order_is_preserved():
    """
    الترتيب هو نص التظبيط: نفس النقط، أولوية مختلفة حسب الوظيفة.
    لو الترتيب اتبهدل، التظبيط بيفقد نص قيمته.
    """
    assert tailor.validate(["b7", "b1", "b2"], KNOWN)[0] == ["b7", "b1", "b2"]


def test_capped_at_max():
    kept, _ = tailor.validate(["b1", "b2", "b7"] * 10, KNOWN)
    assert len(kept) <= tailor.MAX_BULLETS


@pytest.mark.parametrize("bad", [None, [], [None], [123], [{"id": "b1"}]])
def test_junk_input_does_not_crash(bad):
    kept, _ = tailor.validate(bad, KNOWN)
    assert isinstance(kept, list)


# ── الكتالوج ────────────────────────────────────────────────────────────

def test_catalogue_loads_from_real_cv():
    bullets, text = tailor.load_catalogue()
    assert bullets, "cv.yaml مفيهوش نقط بمعرّفات"
    assert all(re.fullmatch(r"b\d+", b) for b in bullets)


def test_every_bullet_has_text():
    bullets, _ = tailor.load_catalogue()
    for bid, b in bullets.items():
        assert b.get("text", "").strip(), f"{bid} من غير نص"


def test_catalogue_text_lists_every_id():
    """
    الموديل بيشوف النص ده بس. معرّف مش مكتوب فيه = نقطة مستحيل تتختار.
    """
    bullets, text = tailor.load_catalogue()
    for bid in bullets:
        assert f"{bid}:" in text


def test_context_has_no_bullets():
    """
    السياق (مهارات وملف شخصي) بيتبعت كمعلومة، مش كمادة للاختيار.
    لو النقط اتسربت جوّاه، الموديل ممكن ينسخ نص بدل ما يختار معرّف.
    """
    ctx = tailor.context()
    assert "experience" not in ctx and "projects" not in ctx
    assert "skills" in ctx


# ── المستند ─────────────────────────────────────────────────────────────

def test_document_builds():
    buf = render.build(tailor.context(), KNOWN, ["b1", "b7"], "AI Engineer")
    data = buf.getvalue()
    assert data[:2] == b"PK"          # docx = أرشيف zip
    assert len(data) > 5_000


def test_document_contains_only_chosen_bullets():
    """
    الاختبار اللي بيقفل الدايرة: النص اللي في الملف لازم يكون **بس**
    من النقط المختارة. لو ظهر نص نقطة مااتختارتش، يبقى فيه مسار
    بيسرّب محتوى — وده أخطر من معرّف مخترع لأنه شكله سليم.
    """
    from docx import Document
    buf = render.build(tailor.context(), KNOWN, ["b1"], "")
    text = "\n".join(p.text for p in Document(buf).paragraphs)
    assert KNOWN["b1"]["text"] in text
    assert KNOWN["b2"]["text"] not in text
    assert KNOWN["b7"]["text"] not in text


def test_document_handles_empty_selection():
    assert render.build(tailor.context(), KNOWN, [], "").getvalue()[:2] == b"PK"


def test_filename_is_clean():
    f = render.filename({"company_name": "Mozn / AI", "title": "AI Engineer (m/f/d)"})
    assert f.endswith(".docx")
    for ch in "/\\:*?\"<>|":
        assert ch not in f


def test_filename_survives_missing_fields():
    assert render.filename({}).endswith(".docx")
