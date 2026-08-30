"""
اختبارات تظبيط السيرة.

أهم اختبار في المشروع كله هو `validate`. لو عدّى معرّف مخترع، معناه
إن فيه سطر في سيرتك مالوش أصل في cv.yaml — يعني ادّعاء خبرة مش
موجودة، وإنت مش شايفه.

ده test مش eval: مفيش "نسبة نجاح" مقبولة هنا. لازم 100%.
"""
import pathlib
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
    h = render.build_html(tailor.full(), KNOWN, ["b1", "b7"], "Product AI Engineer")
    assert "Elsayed Mustafa" in h
    assert h.count("@font-face") == 4          # الخط متضمّن، مش خارجي


def test_title_comes_from_cv_not_model():
    """
    العنوان ثابت من cv.yaml. الموديل كان بيغيّره كل مرة
    ("Product AI Engineer" · "AI Automation and Workflow Engineer") —
    وده بيضيّق تصنيفك عند الـ recruiter من غير داعي.
    """
    h = render.build_html(tailor.full(), KNOWN, ["b1"], "Product AI Engineer")
    assert "Product AI Engineer" not in h
    assert "Automation Engineer" in h


def test_no_absolute_positioning():
    """
    position:absolute في النقط كان بيخلي Chromium يرسم القايمة في
    طبقة منفصلة، فالنقط بتتأخر في ترتيب النص جوّه الـ PDF وبتتقري
    بعد كل العناوين. الاختبار ده بيمنع رجوعها.
    """
    css = pathlib.Path("src/cv_template.html").read_text(encoding="utf-8")
    # التعليقات بتتشال الأول — الاختبار على الـ CSS الفعلي، مش على
    # الشرح اللي بيذكر الحاجة اللي بنمنعها
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"<!--.*?-->", "", css, flags=re.S)
    flat = css.replace(" ", "")
    assert "position:absolute" not in flat
    assert "position:fixed" not in flat
    # order: بيعيد الترتيب بصريًا من غير ما يغيّر الـ DOM — بالظبط
    # اللي بيخلي الـ ATS يقرا حاجة غير اللي إنت شايفه
    assert not re.search(r"[;{]order:", flat)


def test_job_is_one_block():
    """العنوان والنقط جوّه نفس الـ article — مايتفصلوش في ترتيب النص."""
    bullets, _ = tailor.load_catalogue()
    h = render.build_html(tailor.full(), bullets, ["b1", "b2"], "")
    art = h[h.index("<article"):h.index("</article>")]
    assert "BlueBug" in art and "<li>" in art


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


# ── توازن المشاريع ──────────────────────────────────────────────────────

PROJ = {
    "p1a": {"parent_id": "proj1", "block": "projects", "text": "a"},
    "p1b": {"parent_id": "proj1", "block": "projects", "text": "b"},
    "p1c": {"parent_id": "proj1", "block": "projects", "text": "c"},
    "p1d": {"parent_id": "proj1", "block": "projects", "text": "d"},
    "p2a": {"parent_id": "proj2", "block": "projects", "text": "e"},
    "p2b": {"parent_id": "proj2", "block": "projects", "text": "f"},
}


def test_project_capped_at_three():
    """مشروع بـ4 نقط والتاني بواحدة كان بيخلي التاني يبان ضعيف."""
    out = tailor.balance_projects(["p1a", "p1b", "p1c", "p1d", "p2a", "p2b"], PROJ)
    assert len([x for x in out if x.startswith("p1")]) == tailor.MAX_PER_PROJECT
    assert len([x for x in out if x.startswith("p2")]) == 2


def test_lonely_project_dropped():
    """مشروع بنقطة واحدة بيبان ناقص — يتشال أحسن من إنه يظهر ضعيف."""
    out = tailor.balance_projects(["p1a", "p1b", "p2a"], PROJ)
    assert "p2a" not in out and out == ["p1a", "p1b"]


def test_order_preserved():
    out = tailor.balance_projects(["p2a", "p2b", "p1a", "p1b"], PROJ)
    assert out == ["p2a", "p2b", "p1a", "p1b"]


def test_all_lonely_keeps_the_first():
    """لو كل المشاريع بنقطة واحدة، مانرجعش فاضي."""
    assert tailor.balance_projects(["p1a", "p2a"], PROJ)


# ── ترتيب النقط جوّه الجهة ──────────────────────────────────────────────

def test_bullets_sorted_by_rank_not_model_order():
    """
    الموديل بيقرر أنهي نقط. صاحب السيرة بيقرر ترتيبها.
    لو الترتيب اتساب للموديل، أقوى إنجاز ممكن يقع تالت أو رابع
    والقارئ يكون سابه قبل ما يوصله.
    """
    b = {"x": {"text": "weak", "rank": 3},
         "y": {"text": "strong", "rank": 1},
         "z": {"text": "mid", "rank": 2}}
    html = render._bullets(["x", "y", "z"], b)      # ترتيب الموديل
    assert html.index("strong") < html.index("mid") < html.index("weak")


def test_missing_rank_goes_last():
    b = {"x": {"text": "ranked", "rank": 1}, "y": {"text": "unranked"}}
    html = render._bullets(["y", "x"], b)
    assert html.index("ranked") < html.index("unranked")


def test_every_bullet_has_a_rank():
    """نقطة من غير rank بتقع في الآخر — وده غالبًا مش المقصود."""
    bullets, _ = tailor.load_catalogue()
    missing = [b for b, m in bullets.items() if "rank" not in m]
    assert not missing, f"نقط من غير rank: {missing}"
