"""
اختبارات حلقة الاكتشاف.

الجزء اللي بينادي الشبكة مش بيتختبر هنا — بنختبر المنطق اللي حواليه:
توليد صيغ الأسماء، التطبيع، وفلترة الأسماء الوهمية. دول اللي بيحددوا
نسبة النجاح فعلاً.
"""
import pytest

from src import discovery


# ── التطبيع: المفتاح اللي بنقارن بيه ────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("Cohere", "cohere"),
    ("Cohere ", " COHERE"),
    ("Lean  Tech", "lean tech"),
])
def test_same_company_same_key(a, b):
    assert discovery.normalise(a) == discovery.normalise(b)


def test_different_companies_differ():
    assert discovery.normalise("Cohere") != discovery.normalise("Coherent")


# ── صيغ الـ token ───────────────────────────────────────────────────────

def test_legal_suffix_dropped():
    """
    "everdrop GmbH" الـ token بتاعها "everdrop". الشركات بتشيل
    اللواحق القانونية من الـ slug — ودي أكتر حالة بتتكرر.
    """
    assert "everdrop" in discovery.slugs("everdrop GmbH")


@pytest.mark.parametrize("name,expected", [
    ("Fuse Energy", "fuseenergy"),
    ("Fuse Energy", "fuse-energy"),
    ("Fuse Energy", "fuse"),        # أول كلمة لوحدها
    ("Shopware AG", "shopware"),
    ("Q Energy", "qenergy"),
])
def test_slug_variants(name, expected):
    assert expected in discovery.slugs(name)


def test_slugs_are_unique():
    """اسم من كلمة واحدة مايولّدش نفس الصيغة مرتين."""
    s = discovery.slugs("Cohere")
    assert len(s) == len(set(s))


def test_punctuation_stripped():
    assert "ucmagency" in discovery.slugs("ucm.agency")


def test_empty_name_gives_nothing():
    assert discovery.slugs("") == []
    assert discovery.slugs("   ") == []


def test_slugs_skip_one_letter():
    """صيغة من حرف واحد مش هتلاقي حاجة وبتضيّع نداءات."""
    assert all(len(s) >= 2 for s in discovery.slugs("A B"))


# ── فلترة الأسماء الوهمية ───────────────────────────────────────────────

@pytest.mark.parametrize("junk", [
    "Confidential", "confidential", "Undisclosed", "N/A", "Stealth",
    "  ", "", "12345",
])
def test_junk_rejected(junk):
    """
    المصادر التجميعية بتحط أسماء عامة كتير. من غير الفلتر ده،
    كل تشغيلة هتضيّع ميزانيتها في محاولة حل كلمة "Confidential".
    """
    assert not discovery.is_plausible(junk)


@pytest.mark.parametrize("real", ["Cohere", "Mozn", "Q Energy", "everdrop GmbH"])
def test_real_names_accepted(real):
    assert discovery.is_plausible(real)


# ── الميزانية ───────────────────────────────────────────────────────────

def test_budget_is_bounded():
    """
    الحل بياخد ~1 ثانية للشركة، ومهلة الـ workflow 10 دقايق.
    السقف ده هو اللي بيمنع التشغيلة إنها تتقطع في نصها.
    """
    assert 0 < discovery.MAX_PER_RUN <= 60


def test_retry_window_is_not_hourly():
    """
    شركة ملقناهاش مش هنجربها كل ساعة — ده هيحرق الميزانية على نفس
    الأسماء الفاشلة كل يوم، والأسماء الجديدة مش هتوصل لها أبدًا.
    """
    assert discovery.RETRY_AFTER_DAYS >= 7
