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


# ── 17 نوفمبر: قراية أكتر من غير ما الحصة تخلص ─────────────────────────

@pytest.mark.parametrize("text", [
    # من الصفحة الرئيسية الحقيقية: توظيف، بس برّه مجالك — مايستاهلش نداء
    "NEW JOB OPPORTUNITY: Polisher (United Arab Emirates) Ras Al Khaimah. Apply now",
    "بنك الرياض تفتح باب التوظيف المسمى: Quantity Surveyor المكان: أبها. التقديم عبر الرابط",
    "We're hiring a Senior Mechanical Engineer (Maintenance) in Abu Dhabi",
])
def test_hiring_outside_your_field_costs_nothing(text):
    assert not harvest.worth_asking(text)


def test_the_post_we_missed_reaches_the_model():
    """Hamed Minaei، 16 نوفمبر — فاتنا لإننا كنا بنقرا 25 منشور بس."""
    text = ("WE'RE HIRING | REMOTE AI ENGINEER Worldwide Opportunity | Work From Anywhere "
            "Compensation: $350–$500 USD per week SMART VISIONS is expanding its global AI team")
    assert harvest.worth_asking(text)


def test_a_post_is_asked_about_once(tmp_path, monkeypatch):
    monkeypatch.setattr(harvest, "SEEN", str(tmp_path / "seen.json"))
    a = "Hiring AI Engineer in Riyadh. Apply now!"
    assert harvest.post_hash(a) == harvest.post_hash("  hiring ai engineer in riyadh  apply now ")
    harvest._remember({harvest.post_hash(a): "2099-01-01", "old": "2000-01-01"})
    assert harvest._seen() == {harvest.post_hash(a): "2099-01-01"}     # القديم اتمسح


def test_email_post_keeps_the_post_link_the_email_and_the_subject():
    """SMART VISIONS: صفحة التقديم كانت بروفايل اللي نشر، والعنوان المطلوب ضاع."""
    from src import prepare
    post = {"author": "Hamed Minaei", "author_url": "https://www.linkedin.com/in/hamed/",
            "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:752806/",
            "links": [], "query": "x",
            "text": "We're hiring. Send your CV to: manager@connect.smartvisionsai.com "
                    "Email Subject: Remote AI Engineer – Your Full Name GitHub profiles appreciated."}
    j = harvest.to_job(post, {"title": "Remote AI Engineer", "company": "SMART VISIONS",
                              "apply": "manager@connect.smartvisionsai.com", "summary": "AI role"})
    assert j.url == post["post_url"]
    job = {"description": j.description, "ats": "linkedin_post"}
    assert prepare.apply_email(job) == ("manager@connect.smartvisionsai.com",
                                        "Remote AI Engineer – Elsayed Mustafa")
    kb = prepare.package_markup(job)["inline_keyboard"]
    assert kb[1][0]["copy_text"]["text"] == "Remote AI Engineer – Elsayed Mustafa"
    # من غير لينك منشور: mailto أحسن من بروفايل اللي نشر
    j2 = harvest.to_job(dict(post, post_url=""), {"title": "x", "apply": "a@b.com"})
    assert j2.url == "mailto:a@b.com"


# ── 21 نوفمبر: المنشورات على دفعات ──────────────────────────────────────

class _FakeModels:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, []

    def generate_content(self, model, contents, config):
        self.calls.append(contents)
        if self.exc:
            raise self.exc
        return type("R", (), {"text": self.reply})()


def test_one_request_reads_a_whole_batch_and_answers_line_up():
    """125 منشور كانوا 125 طلب وبياكلوا حصة Gemini قبل التقييم."""
    import json
    item = {"title": "AI Engineer", "company": "Acme", "location": "Dubai",
            "remote_type": "onsite", "apply": "", "summary": "s"}
    reply = json.dumps({"posts": [
        {"n": 2, "is_job": True, **item},
        {"n": 1, "is_job": False, **{**item, "title": ""}},
        {"n": 9, "is_job": True, **item},                 # رقم مش موجود — يتجاهل
        {"n": 3, "is_job": True, **{**item, "title": "  "}},
    ]})
    m = _FakeModels(reply)
    client = type("C", (), {"models": m})()
    posts = [{"text": f"post {i}"} for i in range(3)]
    out, err = harvest.extract_batch(client, posts, models=["m"])
    assert err == "" and len(m.calls) == 1
    assert out[0] is None and out[1]["company"] == "Acme" and out[2] is None
    assert "[1]" in m.calls[0] and "[3]" in m.calls[0] and "قايمة وظايف" in m.calls[0]


def test_a_failed_batch_is_not_marked_as_asked():
    m = _FakeModels(exc=ValueError("400 INVALID_ARGUMENT bad request"))
    client = type("C", (), {"models": m})()
    out, err = harvest.extract_batch(client, [{"text": "x"}], models=["m"])
    assert out is None and "INVALID_ARGUMENT" in err
    import inspect
    src = inspect.getsource(harvest.run)
    # الحفظ في seen بيحصل بعد ما الدفعة ترجع، مش قبلها
    assert src.index("extract_batch(") < src.index("seen[post_hash(")
