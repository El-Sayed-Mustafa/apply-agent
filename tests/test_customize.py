"""
تظبيط السيرة وقت التقديم — الفحص هو الضمانة، فده اللي بيتختبر.
مفيش نداءات Claude هنا.
"""
from src import cover, customize, tailor

LEVELS = {"verified": {"python"}, "banned": ["Docker", "AWS", "LangGraph", "Kubernetes"]}
VOCAB = {"Python", "FastAPI", "Supabase", "AWS", "Docker", "LangChain", "RAG", "LLM"}
ORIG = ("Rebuilt a bilingual field-service CRM in Bahrain: moved 17,000+ records "
        "into a secured database and cut the slowest page from 5.6 seconds to 0.56.")
CTX = "Supabase, PostgreSQL, Apps Script, Green API " + ORIG


def test_title_close_to_the_job_passes():
    assert customize.check_title("Applied AI Engineer", LEVELS) == []
    assert customize.check_title("AI Automation Engineer", LEVELS) == []


def test_title_never_claims_a_higher_level():
    assert customize.check_title("Senior AI Engineer", LEVELS)
    assert customize.check_title("Lead LLM Engineer", LEVELS)
    assert customize.check_title("AI Engineer II", LEVELS)


def test_title_never_names_a_skill_he_lacks():
    assert customize.check_title("AWS AI Engineer", LEVELS)


def test_rewording_with_the_same_numbers_passes():
    new = ("Migrated 17,000+ records of a bilingual CRM into a secured database "
           "and cut the slowest page from 5.6 seconds to 0.56.")
    assert customize.check_bullet(new, ORIG, CTX, VOCAB, LEVELS) == []


def test_changed_or_added_numbers_are_rejected():
    new = "Migrated 20,000+ records and cut load time from 5.6 to 0.56 seconds."
    assert customize.check_bullet(new, ORIG, CTX, VOCAB, LEVELS)
    new = ORIG + " Served 3 teams."
    assert customize.check_bullet(new, ORIG, CTX, VOCAB, LEVELS)


def test_number_words_count_as_claims():
    orig = "Build and maintain three internal AI and automation products."
    assert customize.check_bullet(
        "Build and maintain five internal AI products.", orig, orig, VOCAB, LEVELS)


def test_new_tool_not_in_that_project_is_rejected():
    new = ORIG.replace("a secured database", "a secured database on AWS")
    probs = customize.check_bullet(new, ORIG, CTX, VOCAB, LEVELS)
    assert any("AWS" in p for p in probs)
    new = ORIG.replace("a secured database", "a LangChain pipeline")
    assert any("LangChain" in p for p in customize.check_bullet(new, ORIG, CTX, VOCAB, LEVELS))


def test_tool_from_the_same_project_stack_is_fine():
    new = ORIG.replace("a secured database", "a secured Supabase database")
    assert customize.check_bullet(new, ORIG, CTX, VOCAB, LEVELS) == []


def test_validate_on_the_real_cv_drops_bad_parts_and_keeps_good():
    cv = tailor.full()
    bullets, _ = tailor.load_catalogue()
    good = bullets["b33"]["text"].replace("Rebuilt", "Re-architected")
    plan, rejected = customize.validate({
        "title": "Senior Applied AI Engineer",
        "summary": "AI Engineer with 9 years of experience.",
        "bullets": {"b33": good, "b32": "Delivered 40 platforms.", "zzz": "x"},
        "bullet_order": ["b33", "nope"],
        "projects": ["proj2", "proj5", "fake"],
        "skill_groups": ["AI & Machine Learning", "Made Up"],
    }, cv)
    assert "title" not in plan and "summary" not in plan
    assert plan["bullets"] == {"b33": good}
    assert plan["bullet_order"] == ["b33"]
    assert plan["projects"] == ["proj2"]               # proj5 مش active
    assert plan["skill_groups"] == ["AI & Machine Learning"]
    assert len(rejected) == 3                          # العنوان والملخص وb32


def test_apply_changes_text_order_and_title_only():
    cv = tailor.full()
    plan = {"title": "Applied AI Engineer", "bullets": {"b30": "NEW TEXT"},
            "bullet_order": ["b31", "b30"], "skill_groups": ["AI & Machine Learning"]}
    out = customize.apply(cv, plan, "We use FastAPI and Ollama")
    assert out["profile"]["title"] == "Applied AI Engineer"
    exp1 = sorted(out["experience"][0]["bullets"], key=lambda b: b["rank"])
    assert [b["id"] for b in exp1] == ["b31", "b30", "b29"]
    assert exp1[1]["text"] == "NEW TEXT"
    assert list(out["skills"])[0] == "AI & Machine Learning"
    assert out["skills"]["AI & Machine Learning"][0] == "Ollama"
    assert out["skills"]["Python & Backend"][:2] == ["FastAPI", "Python"]
    # مفيش مهارة اتضافت ولا اتشالت، والأصل ماتلمسش
    assert sorted(map(str, sum(out["skills"].values(), []))) == \
           sorted(map(str, sum(cv["skills"].values(), [])))
    assert cv["profile"]["title"] == "AI & Automation Engineer"


def test_empty_plan_is_the_original_cv():
    cv = tailor.full()
    out = customize.apply(cv, {}, "")
    assert out["profile"] == cv["profile"]
    assert customize.chosen_ids(cv, {}) == []


def test_letter_cliches_and_length_are_rejected():
    cv = "Rating model 80.7% exact."
    lv = {"verified": set(), "banned": []}
    assert any("passionate" in p for p in cover.check("I am passionate about AI.", cv, lv))
    assert any("em dash" in p for p in cover.check("I built it — fast.", cv, lv))
    assert any("طويل" in p for p in cover.check("word " * 130, cv, lv))


def test_greeting():
    assert cover.greeting({"ats": "linkedin_post",
                           "company_name": "Tamer Omar, MBA, PMP"}) == "Hi Tamer,"
    assert cover.greeting({"ats": "linkedin_post",
                           "company_name": "Talent Recruiters Group"}) == "Hello,"
    assert cover.greeting({"ats": "ashby", "company_name": "Scale"}) == "Hi Scale team,"
    assert cover.greeting({"ats": "ashby", "company_name": ""}) == "Hello,"


def test_cv_title_is_the_jobs_own_title_when_true():
    j = customize.job_title
    assert j("Forward Deployed Engineer, Agentic Platform") == "Forward Deployed Engineer"
    assert j("AI/ML ENGINEER, INTERNAL PLATFORMS") == "AI/ML Engineer"
    assert j("Lead Generative AI Engineer") == "Generative AI Engineer"
    assert j("Data Engineer (m/f/d)") == "Data Engineer"
    assert j("Senior MLOps Engineer") == ""             # مش شغلك — Sonnet يختار
    assert j("iOS Developer") == ""


def test_greeting_never_takes_a_company_word_as_a_first_name():
    """17 نوفمبر: "Hi SMART," — SMART VISIONS اتعاملت كاسم شخص."""
    post = {"ats": "linkedin_post", "company_name": "SMART VISIONS",
            "description": "Remote AI role.\nنشره على لينكدإن: Hamed Minaei"}
    assert cover.greeting(post) == "Hi Smart Visions team,"
    # الشركة ناقصة فاتسجّل اللي نشر: ده شخص فعلًا
    post = {"ats": "linkedin_post", "company_name": "Hamed Minaei",
            "description": "x\nنشره على لينكدإن: Hamed Minaei"}
    assert cover.greeting(post) == "Hi Hamed,"
    # منشور قديم من غير "نشره": الكابيتال كله مش اسم شخص
    assert cover.greeting({"ats": "linkedin_post", "company_name": "SMART VISIONS"}) \
        == "Hi Smart Visions team,"
