"""
اختبارات حصاد منشورات التوظيف.

المصدر ده اتضاف عشان فجوة: منشورات التوظيف كانت بتتشاف وبتترمي.
مصادر الوظايف كلها كانت APIs، والحاجة الوحيدة اللي بتقرا منشورات
كانت وحدة الكومنتات — وهي بتدوّر على هدف كومنت مش على وظيفة.
"""
import pytest

from src import harvest


# ── الفلتر الرخيص ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Hiring - Data Analyst | Riyadh, Saudi Arabia | Apply through the form",
    "We're looking for an AI Engineer to join our team in Dubai",
    "فرصة وظيفية | محلل بيانات | جهة شبه حكومية | الدمام. طريقة التقديم",
    "مطلوب مهندس أتمتة للعمل عن بعد، أرسل السيرة الذاتية",
])
def test_hiring_posts_reach_the_model(text):
    assert harvest.worth_asking(text)


@pytest.mark.parametrize("text", [
    "I'm open to work as an AI Engineer, hiring managers please reach out",
    "أبحث عن عمل في مجال الذكاء الاصطناعي، وظيفة عن بعد",
])
def test_job_seekers_filtered_out(text):
    """
    منشور حد بيدوّر لنفسه على شغل فيه كل كلمات التوظيف — وهو عكس
    اللي احنا وراه بالظبط.
    """
    assert not harvest.worth_asking(text)


@pytest.mark.parametrize("text", [
    "Here are five lessons I learned building RAG pipelines this year",
    "Congratulations to the team on shipping our new model",
])
def test_ordinary_posts_cost_nothing(text):
    """
    الحصة اليومية هي القيد الحقيقي. منشور عادي لازم يترمي من غير
    ما يكلّف نداء موديل.
    """
    assert not harvest.worth_asking(text)


# ── تنظيف النص ──────────────────────────────────────────────────────────

def test_author_and_body_split():
    raw = ("Feed post\nMike Fralick\n • 3rd+\nHead of Global Talent at Tech9\n"
           "2d\nFollow\nHiring AI Engineer in Riyadh.\n12 comments")
    author, body = harvest.clean(raw)
    assert author == "Mike Fralick"
    assert "Hiring AI Engineer in Riyadh." in body
    for junk in ("Feed post", "Follow", "12 comments"):
        assert junk not in body


# ── الـJS ───────────────────────────────────────────────────────────────

def test_js_literal_is_intact():
    """نفس فخ الـescaping اللي خلى تجميع المنشورات يرجّع صفر بصمت."""
    for line in harvest.JS_SEARCH.split("\n"):
        assert line.count("'") % 2 == 0, f"ليترال ناقص: {line}"


def test_selector_not_class_based():
    """كلاسات لينكدإن مشفّرة ومتغيّرة."""
    assert "feed-shared-update" not in harvest.JS_SEARCH


# ── تحويل الوظيفة ───────────────────────────────────────────────────────

def _post(**kw):
    base = {"author": "Mike Fralick", "author_url": "https://linkedin.com/in/mf",
            "links": [], "text": "Hiring AI Engineer", "query": "q"}
    return {**base, **kw}


def test_missing_company_falls_back_to_poster():
    """
    البصمة محتاجة حاجة ثابتة. لو حطينا "مجهولة" لكل منشور، وظايف
    مختلفة هتبان مكررة وهتتبلع.
    """
    j = harvest.to_job(_post(), {"title": "AI Engineer", "company": "",
                                 "location": "Riyadh", "remote_type": "onsite",
                                 "apply": "", "summary": "Python"})
    assert j.company_name == "Mike Fralick"


def test_email_apply_reaches_the_description():
    """
    إيميل التقديم مش رابط، فمش هيتحط في url. لو ماوصلش في الوصف
    مش هتعرف تقدّم أصلاً.
    """
    j = harvest.to_job(_post(), {"title": "Data Analyst", "company": "X",
                                 "location": "Dammam", "remote_type": "onsite",
                                 "apply": "alwadeesa7@gmail.com",
                                 "summary": "Excel, Power BI"})
    assert "alwadeesa7@gmail.com" in j.description


def test_source_is_tagged():
    """لازم نعرف الوظيفة جت من منشور مش من ATS."""
    j = harvest.to_job(_post(), {"title": "AI Engineer", "company": "X",
                                 "location": "", "remote_type": "remote",
                                 "apply": "https://x.co/a", "summary": "s"})
    assert j.ats == "linkedin_post"
    assert j.url == "https://x.co/a"


# ── المكرر جوّا التشغيلة ────────────────────────────────────────────────

def test_repost_of_same_job_counted_once():
    """
    البصمة فيها اسم الشركة، ولما اتنين يعيدوا نشر نفس الإعلان
    الموديل بيقرا اسم الناشر كشركة — فنفس الوظيفة كانت بتوصل مرتين.
    اتقاست: "DEVOPS ENGINEER" وصلت مرتين من ناشرين مختلفين.
    """
    d = {"title": "DevOps Engineer", "location": "Toronto, Ontario",
         "remote_type": "onsite", "apply": "", "summary": "s"}
    a = harvest.to_job(_post(author="Offres d'Emploi"), {**d, "company": ""})
    b = harvest.to_job(_post(author="4 RECRUTE"), {**d, "company": ""})
    assert a.content_hash != b.content_hash        # البصمة مابتشيلهاش
    assert len(harvest.dedupe([a, b])) == 1        # ودي بتشيلها


def test_different_locations_both_kept():
    """نفس المسمى في الرياض وفي دبي = فرصتين مختلفتين."""
    d = {"title": "AI Engineer", "company": "X", "remote_type": "onsite",
         "apply": "", "summary": "s"}
    a = harvest.to_job(_post(), {**d, "location": "Riyadh"})
    b = harvest.to_job(_post(), {**d, "location": "Dubai"})
    assert len(harvest.dedupe([a, b])) == 2


def test_roundup_posts_rejected_by_prompt():
    """
    "10 AI / ML roles hiring right now" اتسجل كوظيفة اسمها كده
    وشركتها "Find me THE job" — قايمة مش وظيفة.
    """
    assert "قايمة وظايف" in harvest.PROMPT


def test_location_suffix_does_not_split_a_duplicate():
    """
    "Brampton/Toronto, Ontario" و"…, Ontario, Canada" نفس الإعلان.
    الفرق ده لوحده مرّره مرتين في تشغيلة حقيقية.
    """
    d = {"title": "DevOps Engineer", "company": "", "remote_type": "onsite",
         "apply": "", "summary": "s"}
    a = harvest.to_job(_post(author="A"), {**d, "location": "Toronto, Ontario"})
    b = harvest.to_job(_post(author="B"), {**d, "location": "Toronto, Ontario, Canada"})
    assert len(harvest.dedupe([a, b])) == 1


def test_every_query_gets_a_share():
    """
    من غير حصة لكل استعلام، أول استعلامين بيملوا العدد المطلوب
    والاستعلامات الخليجية والعربية مابتشتغلش. اتقاس: 20 منشور
    رجعوا كلهم أمريكا وأستراليا والهند.
    """
    import inspect
    src = inspect.getsource(harvest.collect)
    assert "per_query" in src


def test_no_arabic_queries():
    """
    الإعلانات العربية على لينكدإن غالبًا لأدوار إدارية ومبيعات،
    والمطابقة بترجّع نتايج برّه التخصص.
    """
    import re
    for q in harvest.searches():
        assert not re.search(r"[\u0600-\u06ff]", q), f"استعلام عربي: {q}"


def test_missing_location_does_not_split_a_duplicate():
    """
    نفس الإعلان بموقع في نسخة ومن غير موقع في التانية كان بيعدّي
    مرتين — حصل مع Qualcomm AI Hub. المسمى لوحده كفاية لما مفيش
    موقع نقارن بيه.
    """
    d = {"title": "AI Engineer", "company": "Qualcomm", "remote_type": "unknown",
         "apply": "", "summary": "s"}
    a = harvest.to_job(_post(author="A"), {**d, "location": ""})
    b = harvest.to_job(_post(author="B"), {**d, "location": "Chennai"})
    assert len(harvest.dedupe([a, b])) == 1


def test_ineligible_geography_is_dropped():
    """
    الوظيفة من منشور إحنا اللي بنركّبها، فمالهاش قيمة كتالوج
    تخلّينا نحتفظ باللي مايعديش. الضجيج كان بيوصل لـTokyo وChennai.
    """
    import inspect
    src = inspect.getsource(harvest.run)
    assert "targeting.evaluate" in src
