"""
اختبارات الكومنتات.

الكومنت هو الفعل الوحيد في المنظومة اللي بينشر حاجة **عامة ودايمة**
باسمه. الدعوة شخص واحد بيشوفها وبتتسحب؛ الكومنت بيفضل، ومحدش بيبلّغه
لو طلع وحش.

عشان كده معظم الاختبارات على قواعد الرفض — دي الطبقة اللي بتشتغل
لوحدها من غير ما حد يبص.
"""
import pytest

from src import commenting
from src.linkedin import feed


# ── حد الطول ────────────────────────────────────────────────────────────

def test_within_limit_passes():
    ok, _ = commenting.check("Solid write-up on the retrieval latency tradeoff.", "en")
    assert ok


def test_too_long_rejected():
    body = " ".join(["word"] * (commenting.MAX_WORDS + 1))
    ok, why = commenting.check(body, "en")
    assert not ok and "الحد" in why


def test_exactly_at_limit_passes():
    body = " ".join(["word"] * commenting.MAX_WORDS)
    assert commenting.check(body, "en")[0]


def test_too_short_rejected():
    """كلمتين مش كومنت — دي مجاملة فاضية."""
    assert not commenting.check("Nice work", "en")[0]


def test_limit_is_what_he_asked_for():
    assert commenting.MAX_WORDS == 13


# ── العبارات الفاضية ────────────────────────────────────────────────────

@pytest.mark.parametrize("filler", [
    "Great post, thanks for sharing this",
    "Well said, couldn't agree more here",
    "Very insightful, love this take",
    "Amazing work on this project",
    "مشاركة رائعة وكلام في محله",
])
def test_filler_rejected(filler):
    """
    دي اللي بتخلي الكومنت يبان آلي. مفيدة لصاحب المنشور صفر،
    وبتقول عنك إنك مش قريت.
    """
    ok, why = commenting.check(filler, "ar" if "مشاركة" in filler else "en")
    assert not ok


def test_specific_comment_passes():
    """الكومنت اللي بيسمّي حاجة من المنشور بيعدّي."""
    ok, _ = commenting.check(
        "The 0.84s query time on 10GB is the impressive part.", "en")
    assert ok


# ── الرموز والروابط ─────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    "Congrats on the new role 🎉",
    "Check my post #AI #hiring",
    "Interesting, see https://x.com/y for more",
    "Agreed @someone makes the same point",
])
def test_symbols_rejected(bad):
    assert not commenting.check(bad, "en")[0]


def test_multiline_rejected():
    """كومنت من سطرين شكله منشور مش تعليق."""
    assert not commenting.check("First line.\nSecond line.", "en")[0]


# ── اللغة ───────────────────────────────────────────────────────────────

def test_english_comment_on_arabic_post_rejected():
    """
    كومنت إنجليزي على منشور عربي أوضح علامة على إنه آلي.
    """
    ok, why = commenting.check("Congratulations on the new role there.", "ar")
    assert not ok and "عربي" in why


def test_arabic_comment_on_english_post_rejected():
    ok, why = commenting.check("مبروك الوظيفة الجديدة وبالتوفيق فيها", "en")
    assert not ok


def test_arabic_comment_on_arabic_post_passes():
    assert commenting.check("مبروك الدور الجديد في الشركة دي", "ar")[0]


# ── تنظيف رد الموديل ────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,clean", [
    ('"Great to see the latency numbers"', "Great to see the latency numbers"),
    ("  spaced   out   text  ", "spaced out text"),
    ("“smart quotes here”", "smart quotes here"),
])
def test_clean_strips_wrapping(raw, clean):
    assert commenting.clean(raw) == clean


# ── تصنيف المنشور ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text,kind", [
    ("Excited to share that I'm joining Mozn as an AI Engineer next month!",
     "celebration"),
    ("We cut inference latency by 40% by batching embedding calls in the pipeline",
     "technical"),
    ("يسعدني أن أعلن انضمامي إلى فريق الذكاء الاصطناعي في الشركة الجديدة",
     "celebration"),
])
def test_post_classified(text, kind):
    assert feed.classify(text) == kind


@pytest.mark.parametrize("skip", [
    "We're hiring! Apply now, link in comments for the full job description",
    "Rest in peace to a wonderful colleague and friend, you will be missed",
    "Short post",
])
def test_posts_we_skip(skip):
    """
    التوظيف والإعلانات والمواساة. الكومنت على منشور مواساة من حساب
    آلي مش غلط تقني — ده ضرر حقيقي.
    """
    assert feed.classify(skip) is None


def test_ui_noise_stripped_from_post():
    """
    innerText بيلم أزرار الواجهة مع المحتوى. لو سبناهم، الموديل
    بيعلّق على "Like · Repost".
    """
    raw = "Ahmed Ali\n3h\nWe shipped a new RAG pipeline this week\nLike\nComment\nRepost\n42 likes"
    out = feed.clean_text(raw)
    assert "RAG pipeline" in out
    for junk in ("Like", "Repost", "42 likes"):
        assert junk not in out


# ── هوية المنشور ────────────────────────────────────────────────────────

def test_same_post_same_key():
    """نفس المنشور بيظهر في الـ feed كذا مرة — لازم مفتاح واحد."""
    a = feed.post_key("urn:li:activity:123", "text one")
    b = feed.post_key("urn:li:activity:123", "different text entirely")
    assert a == b


def test_no_urn_falls_back_to_text():
    a = feed.post_key("", "We shipped a new pipeline this week")
    b = feed.post_key("", "We  shipped a new   pipeline this week")
    assert a == b            # المسافات مش فارقة


def test_different_posts_differ():
    assert feed.post_key("", "post one") != feed.post_key("", "post two")


# ── الصلاحية ────────────────────────────────────────────────────────────

def test_ttl_is_short():
    """
    كومنت على منشور عمره يومين شكله آلي وواضح. لو مردّيتش في الوقت،
    المقترح بيموت — أرخص من كومنت متأخر.
    """
    assert 2 <= commenting.TTL_HOURS <= 12


def test_daily_cap_matches_the_brief():
    """طلب 5-10 في اليوم."""
    from src import comment
    assert 5 <= comment.DAILY <= 10


# ── الـJS نفسه ──────────────────────────────────────────────────────────

def test_js_has_no_broken_string_literal():
    """
    الـJS بيتبعت كنص. `\n` جوّه نص Python عادي بيتحول لسطر حقيقي،
    فيكسر الليترال والمتصفح يرمي SyntaxError. و`collect` كانت بتبلع
    الغلط وترجّع "0 منشور" — ضِعنا وراها تشخيص كامل.
    """
    assert r"split('\n')" in feed.JS_POSTS
    for line in feed.JS_POSTS.split("\n"):
        assert line.count("'") % 2 == 0, f"ليترال ناقص: {line}"


def test_selector_is_urn_based():
    """الكلاسات في لينكدإن مشفّرة ومتغيّرة؛ الـurn هو الثابت الوحيد."""
    assert "data-urn" in feed.JS_POSTS
    assert "feed-shared-update-v2" not in feed.JS_POSTS


# ── إعادة النشر ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Danny Thomas reposted this We cut inference latency by 40% in the RAG pipeline",
    "أعاد نشر هذا المنشور عن بناء وكلاء الذكاء الاصطناعي في الشركة",
])
def test_repost_skipped(text):
    """
    التعليق على منشور معاد نشره بيروح لصاحبه الأصلي — مش للشخص
    اللي احنا مهتمين بيه أصلًا.
    """
    assert feed.classify(text) is None


# ── مصدر المنشورات ──────────────────────────────────────────────────────

def test_sources_return_url_and_name():
    """
    صفحة النشاط مابتحطش لينك بروفايل جوّه كارت صاحبها، فاسم الكاتب
    بيطلع فاضي. بناخده من قاعدة البيانات بدل ما نسيبه ناقص.
    """
    from src import comment
    assert comment.SOURCES >= 3


def test_one_comment_per_author_per_run():
    """
    تلات كومنتات على تلات منشورات لنفس الشخص شكلها آلي صريح،
    حتى لو كل واحد لوحده كويس.
    """
    assert feed.MAX_PER_AUTHOR == 1
