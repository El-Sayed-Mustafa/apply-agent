"""
حارس على كل نصوص الـJS في المشروع.

الفخ ده كلّفنا تلات مرات، وكل مرة بشكل مختلف:

  · feed.JS_POSTS      → "0 منشور" بصمت، وتشخيص كامل ضاع وراه
  · harvest (بروب)      → SyntaxError في وش التشخيص
  · engage.JS_SEARCH_CO → 8 متابعات فشلت كلها

السبب واحد: `\n` جوّه نص Python عادي بيتحول لسطر حقيقي، فيكسر
الليترال في الـJS. الحل إن النص يبقى raw — والاختبار ده بيمسك
اللي نسيناه بدل ما المتصفح يمسكه بعد ما نبقى شغالين.
"""
import importlib
import pkgutil

import pytest

import src


def js_constants():
    """كل ثابت في المشروع شكله كود JS."""
    out = []
    for mod in pkgutil.walk_packages(src.__path__, prefix="src."):
        try:
            m = importlib.import_module(mod.name)
        except Exception:
            continue
        for name in dir(m):
            if not name.isupper():
                continue
            v = getattr(m, name)
            if isinstance(v, str) and v.lstrip().startswith("() =>"):
                out.append((mod.name, name, v))
    return out


CONSTANTS = js_constants()


def test_the_scan_finds_something():
    """لو الفحص رجع فاضي، الاختبار بقى بيحرس على لا حاجة."""
    assert len(CONSTANTS) >= 3


@pytest.mark.parametrize("mod,name,src_", CONSTANTS,
                         ids=[f"{m}.{n}" for m, n, _ in CONSTANTS])
def test_no_literal_broken_across_lines(mod, name, src_):
    """
    كل سطر لازم يقفل الاقتباسات اللي فتحها. سطر بعدد فردي من
    علامات الاقتباس معناه ليترال اتكسر على سطرين.
    """
    for i, line in enumerate(src_.split("\n"), 1):
        code = line.split("//")[0]
        assert code.count("'") % 2 == 0, f"{mod}.{name} سطر {i}: {line}"


@pytest.mark.parametrize("mod,name,src_", CONSTANTS,
                         ids=[f"{m}.{n}" for m, n, _ in CONSTANTS])
def test_newline_escape_survived(mod, name, src_):
    """
    `split('\n')` هو أكتر مكان الفخ بيضرب فيه — لازم يفضل
    محرفين، مش سطر حقيقي.
    """
    if "split(" not in src_:
        return
    assert "split('\n')" not in src_.replace("\n", "«»"), \
        f"{mod}.{name}: فيه سطر حقيقي جوّه ليترال"


# ── نفس الفخ في بايثون ──────────────────────────────────────────────────

def test_no_python_string_broken_across_lines():
    """
    نفس السبب، مكان تاني: `\n` جوّه نص بايثون بيتحول لسطر حقيقي
    ويكسر الـf-string. ضربنا في `engage.show_stats` وخلّى الملف
    كله ماينقراش.

    الفحص بسيط: أي ملف مصدر لازم يستورد. الاستيراد بيفشل على
    الليترال المكسور قبل أي حاجة تانية.
    """
    import importlib
    import pkgutil

    failed = []
    for mod in pkgutil.walk_packages(src.__path__, prefix="src."):
        try:
            importlib.import_module(mod.name)
        except SyntaxError as exc:
            failed.append(f"{mod.name}: {exc}")
        except Exception:
            pass          # الاستيراد ممكن يفشل لأسباب تانية (مفاتيح، شبكة)
    assert not failed, "ليترال مكسور: " + " · ".join(failed)


def test_no_control_characters_in_source():
    """
    `\b` جوّه نص بايثون بيتحول لمحرف backspace حقيقي (0x08) —
    فالـregex بيبقى سليم في القراءة وبيفشل في التنفيذ. ضربنا في
    `hiring.grad_year` ورجّع "مفيش سنة" لكل المرشّحين.

    نفس عيلة الفخ بتاع `\n`، بس ده مابيكسرش الصياغة فمابيتمسكش
    في الاستيراد.
    """
    import pathlib
    bad = []
    for f in pathlib.Path("src").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        for ch, name in ((chr(8), "backspace"), (chr(12), "formfeed"),
                         (chr(11), "vtab"), (chr(7), "bell")):
            if ch in text:
                bad.append(f"{f}: {name}")
    assert not bad, "محارف تحكّم في المصدر: " + " · ".join(bad)
