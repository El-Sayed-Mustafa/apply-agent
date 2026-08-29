"""
اختبارات البصمة.

البصمة هي الحاجة الوحيدة اللي بتمنع الوظيفة تتسجل مرتين. لو غلطت،
هتلاقي نفس الوظيفة في التليجرام كل يوم — أو الأسوأ، وظيفة اتبلعت.

دي tests مش evals: كل واحدة ليها إجابة واحدة صح، ولازم تعدي 100%.
"""
from src.adapters import Job


def make(**over) -> Job:
    base = dict(
        company_name="Mozn", ats="workable", external_id="1",
        title="AI Engineer", location="Riyadh, Saudi Arabia",
        description="Build AI systems for financial crime prevention.",
    )
    base.update(over)
    return Job(**base)


# ── الثبات: اختلاف شكلي مش المفروض يعمل بصمة جديدة ──────────────────────

def test_whitespace_ignored():
    """الشركة زوّدت مسافات في الوصف — نفس الوظيفة."""
    a = make(description="Build   AI\n\nsystems.")
    b = make(description="Build AI systems.")
    assert a.content_hash == b.content_hash


def test_case_ignored():
    """العنوان اتكتب بحروف كبيرة — نفس الوظيفة."""
    assert make(title="AI ENGINEER").content_hash == make(title="ai engineer").content_hash


def test_external_id_ignored():
    """
    دي أهم واحدة: الشركة شالت الإعلان ونشرته تاني برقم جديد.
    لو البصمة اتغيّرت، هتوصلك كأنها وظيفة جديدة.
    """
    assert make(external_id="AAA").content_hash == make(external_id="ZZZ").content_hash


def test_url_ignored():
    """اللينك اتغيّر بس المحتوى زي ما هو."""
    a = make(url="https://a.com/1")
    b = make(url="https://b.com/2")
    assert a.content_hash == b.content_hash


# ── التمييز: اختلاف حقيقي لازم يعمل بصمة جديدة ──────────────────────────

def test_location_matters():
    """
    قرار معماري صريح: نفس الوظيفة في الرياض والقاهرة = فرصتين.
    لو الاختبار ده وقع، معناه إن حد شال الموقع من البصمة —
    ووقتها هتضيع وظايف من غير ما حد ياخد باله.
    """
    riyadh = make(location="Riyadh, Saudi Arabia")
    cairo = make(location="Cairo, Egypt")
    assert riyadh.content_hash != cairo.content_hash


def test_description_matters():
    """الشركة عدّلت المتطلبات — دي وظيفة مختلفة فعلًا."""
    assert make(description="Python").content_hash != make(description="Java").content_hash


def test_title_matters():
    assert make(title="AI Engineer").content_hash != make(title="Data Engineer").content_hash


def test_company_matters():
    """نفس عنوان الوظيفة في شركتين مختلفتين."""
    assert make(company_name="Mozn").content_hash != make(company_name="Tamara").content_hash


# ── الحالات الحدية ──────────────────────────────────────────────────────

def test_empty_location_is_stable():
    """وظيفة من غير موقع — لازم تشتغل من غير ما ترمي خطأ."""
    a, b = make(location=None), make(location=None)
    assert a.content_hash == b.content_hash
    assert len(a.content_hash) == 64


def test_none_vs_empty_location_same():
    """None و '' نفس المعنى — مايبقاش وظيفتين."""
    assert make(location=None).content_hash == make(location="").content_hash


def test_long_description_truncated():
    """
    الوصف بيتقص عند 4000 حرف. وظيفتين مختلفتين بعد الحد ده هيبقى ليهم
    نفس البصمة — قرار مقصود عشان نتجنب اختلافات تافهة في آخر الإعلان.
    """
    prefix = "x" * 4000
    assert make(description=prefix + "A").content_hash == make(description=prefix + "B").content_hash
