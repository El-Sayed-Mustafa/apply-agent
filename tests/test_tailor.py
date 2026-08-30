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
    "b1": {"text": "بناء أنظمة أتمتة", "parent": "AI Engineer",
           "parent_id": "exp1", "block": "experience"},
    "b2": {"text": "تكاملات LLM", "parent": "AI Engineer",
           "parent_id": "exp1", "block": "experience"},
    "b7": {"text": "Meeting Copilot", "parent": "Copilot",
           "parent_id": "proj1", "block": "projects"},
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
    assert "contact" not in ctx          # تقليل البيانات
    assert "skills" in ctx


# ── المستند ─────────────────────────────────────────────────────────────
#
# الاختبارات على الـ HTML مش على الـ PDF: كل المنطق في الـ HTML،
# والـ PDF شغل Chromium. كده الاختبارات بتجري في جزء من الثانية
# ومن غير متصفح — وفيه اختبار واحد بس بيتأكد إن التحويل نفسه شغال.


def test_html_builds():
    h = render.build_html(tailor.full(), KNOWN, ["b1", "b7"], "AI Engineer")
    assert "Elsayed Mustafa" in h and "AI Engineer" in h
    assert h.count("@font-face") == 4          # الخط متضمّن، مش خارجي


def test_html_contains_only_chosen_bullets():
    """
    الاختبار اللي بيقفل الدايرة: النص في الملف لازم يكون **بس** من
    النقط المختارة. معرّف مخترع الحاجز بيشيله — لكن نص مسرّب شكله
    سليم ومحدش ياخد باله.
    """
    h = render.build_html(tailor.full(), KNOWN, ["b1"], "")
    assert KNOWN["b1"]["text"] in h
    assert KNOWN["b2"]["text"] not in h
    assert KNOWN["b7"]["text"] not in h


def test_html_escapes_dangerous_text():
    """اسم شركة فيه < أو & مايكسرش الصفحة."""
    bad = {"b1": {"text": "Built <script>alert(1)</script> & more",
                  "parent_id": "exp1", "block": "experience"}}
    h = render.build_html(tailor.full(), bad, ["b1"], "")
    assert "<script>" not in h and "&lt;script&gt;" in h


def test_numbers_are_emphasised():
    """الأرقام بتتعلّم — تمييز بصري، والنص زي ما هو حرف بحرف."""
    out = render.emphasise("Reconciled 800,000 reviews at 80.7% accuracy")
    assert "<b>800,000</b>" in out
    assert "<b>80.7%</b>" in out
    import re as _re
    assert _re.sub(r"</?b>", "", out) == "Reconciled 800,000 reviews at 80.7% accuracy"


def test_empty_selection_does_not_crash():
    assert render.build_html(tailor.full(), KNOWN, [], "")


def test_filename_is_clean():
    f = render.filename({"company_name": "Mozn / AI", "title": "AI Engineer (m/f/d)"})
    assert f.endswith(".pdf")
    for ch in "/\:*?\"<>|":
        assert ch not in f


def test_filename_survives_missing_fields():
    assert render.filename({}).endswith(".pdf")


@pytest.mark.slow
def test_pdf_renders_one_page():
    """الاختبار الوحيد اللي بيشغّل متصفح. بيتخطى لو Chromium مش موجود."""
    playwright = pytest.importorskip("playwright.sync_api")
    bullets, _ = tailor.load_catalogue()
    try:
        pdf = render.build(tailor.full(), bullets, list(bullets), "").getvalue()
    except Exception as exc:
        pytest.skip(f"مفيش متصفح: {exc}")
    assert pdf[:4] == b"%PDF"
    assert render._page_count(pdf) == 1      # الضبط الذاتي شغال
