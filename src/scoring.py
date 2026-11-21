"""
المقيّم.

الفكرة: كل وظيفة بتعدّي سياسة الاستهداف بتتقيّم مرة واحدة، والنتيجة
بتتخزن. الجدول نفسه هو الطابور — الوظيفة اللي مالهاش صف في scores
بالنسخة الحالية هي شغل معلّق.

النتيجة العملية: التشغيلة تقدر تقع في نصها في أي لحظة، والجاية بتكمّل
من حيث وقفت. مفيش حالة في الذاكرة تتفقد.

النسخة (SCORER_VERSION) بصمة للـ prompt والقواعد. غيّرها → كل الوظايف
بتتقيّم من جديد تلقائيًا، والقديم بيفضل موجود للمقارنة.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone

import yaml
from pathlib import Path
from google import genai
from google.genai import types

from . import genai_pool, targeting

# الحصة المجانية **لكل موديل على حدة**. لما واحد يخلص، بننط للي بعده
# بدل ما التشغيلة كلها تقف. الترتيب بالجودة: الأقوى الأول.
#
# الأحدث مش الأول عن قصد — 3.7 كان بيرجّع 503 من كتر الضغط عليه.
#
# ⚠️ flash-lite اتشال من القايمة عن قصد. قِسناه في الـ spike: طلّع
# Python صفر مرة من 45 إعلان بتذكرها. ولما سبناه في القايمة، اتضح إنه
# عمل 173 من 234 تقييم — لأن الموديلات الكويسة بتخلص حصتها بسرعة
# فالتنقّل بيسقط عليه.
#
# تقييم غلط شكله سليم أسوأ من مفيش تقييم. لما كلهم يخلصوا، التشغيلة
# بتقف والطابور بيستنى — الجدول هو الطابور، فمفيش حاجة بتضيع.
MODELS = [m.strip() for m in os.getenv(
    "SCORER_MODELS",
    "gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview"
).split(",") if m.strip()]

# الموديلات اللي قِسنا إنها ضعيفة. تقييم اتعمل بواحد منها بيتعاد
# لما موديل كويس يبقى متاح.
WEAK_MODELS = {"gemini-3.1-flash-lite", "gemini-3.5-flash-lite"}

MODEL = MODELS[0]                                  # للعرض والتسجيل
SCORER_VERSION = os.getenv("SCORER_VERSION", "v1")

CV_PATH = os.getenv("CV_PATH", "cv.yaml")
BATCH = int(os.getenv("SCORE_BATCH", "20"))       # وظايف لكل تشغيلة
MAX_ATTEMPTS = 3                                   # قبل ما نستسلم لوظيفة
API_RETRIES = 4                                    # لكل نداء، على 429/503
TIME_BUDGET = int(os.getenv("SCORE_SECONDS", "420"))   # مهلة الـ workflow 10 دقايق

# النداء المخاصم. مفتاح عشان نقدر نقيس الفرق: شغّله شهر، اقفله شهر،
# وقارن. لو مفيش فرق في دقة التوقع — اقفله وخلاص، بيوفّر نص التكلفة.
REFUTE = os.getenv("SCORER_REFUTE", "1") not in ("0", "false", "no")

# المخاصمة بتنزّل الدرجة بس — مابترفعهاش أبدًا. يعني وظيفة جابت 30
# مش هتوصل 70 مهما حصل، والنداء المخاصم عليها بيتحرق على قرار
# محسوم سلفًا.
#
# القياس: من 35 تقييم، 4 بس عدّوا 70. يعني 88% من النداءات
# المخاصمة كانت بتتصرف على وظايف مرفوضة أصلاً — والحصة اليومية
# هي القيد الحقيقي في المنظومة.
REFUTE_FLOOR = int(os.getenv("SCORER_REFUTE_FLOOR", "70"))

REFUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "unmet":   {"type": "array", "items": {"type": "string"}},
        "score":   {"type": "integer"},
        "verdict": {"type": "string",
                    "enum": ["strong", "good", "partial", "weak", "no"]},
        "note":    {"type": "string"},
    },
    "required": ["unmet", "score", "verdict", "note"],
}

REFUTER_PROMPT = """A first pass judged this candidate a fit for this job and
claimed the strengths listed below. Your job is to find where that judgement is
too generous.

For every claim, check it against the job description and the candidate:
- Is the requirement actually in the job description, or was it assumed?
- Does the candidate genuinely have it, or is it adjacent experience being
  stretched to fit?
- Is there a hard requirement the first pass skipped entirely?

Then score the fit yourself, using the same scale:
  90-100 strong · 70-89 good · 50-69 partial · 30-49 weak · 0-29 no

RULES:
- When you are unsure whether the candidate meets something, treat it as NOT met.
  The cost of an optimistic score is a wasted application; the cost of a
  pessimistic one is one missed listing among many.
- `unmet`: hard requirements the candidate does not meet, max 5, short phrases.
  Only requirements written in the job description.
- `note`: max 30 words, why your score differs from the first pass, or why it
  does not.

FIRST PASS CLAIMED THESE STRENGTHS
{matched}

CANDIDATE
{cv}

JOB
Title: {title}
Company: {company}
Location: {location}

{description}
"""

# أنواع التوظيف اللي بتتسقّف مهما كان التطابق. الذاكرة: وظايف تدريب
# وشغل "AI Training" كانت بتاخد تقييم عالي لإن المسمى فيه AI.
EMPLOYMENT = ["full_time", "contract", "part_time", "internship",
              "graduate_program", "ai_training_gig", "freelance_task",
              "unknown"]
CAPPED_EMPLOYMENT = {"internship", "graduate_program", "ai_training_gig"}
REMOTE_SCOPE = ["worldwide", "includes_egypt", "mena_or_emea",
                "excludes_egypt", "not_remote", "unknown"]
FACT_CAP = 30

SCHEMA = {
    "type": "object",
    "properties": {
        "score":     {"type": "integer"},
        "verdict":   {"type": "string",
                      "enum": ["strong", "good", "partial", "weak", "no"]},
        "matched":   {"type": "array", "items": {"type": "string"}},
        "gaps":      {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
        # حقايق من نص الإعلان نفسه — نفس النداء، فمفيش تكلفة زيادة
        "facts": {
            "type": "object",
            "properties": {
                "employment_type": {"type": "string", "enum": EMPLOYMENT},
                "remote_scope":    {"type": "string", "enum": REMOTE_SCOPE},
                "min_years":       {"type": "integer", "nullable": True},
                "salary":          {"type": "string"},
                "visa_sponsorship": {"type": "string",
                                     "enum": ["yes", "no", "unknown"]},
                "evidence":        {"type": "string"},
            },
            "required": ["employment_type", "remote_scope", "min_years",
                         "salary", "visa_sponsorship", "evidence"],
        },
    },
    "required": ["score", "verdict", "matched", "gaps", "reasoning", "facts"],
}

PROMPT = """You are screening a job for one specific candidate. Score the fit.

SCORING SCALE — use these anchors:
  90-100  strong   meets nearly every requirement; would be a top applicant
  70-89   good     meets the core requirements; gaps are minor or learnable
  50-69   partial  meets some core requirements; has real, material gaps
  30-49   weak     missing multiple core requirements
  0-29    no       fundamentally the wrong profile

RULES:
- List gaps ONLY for requirements explicitly written in the job description.
  Never invent a requirement that is not in the text.
- Judge the candidate exactly as described. Do not assume skills they did not
  list, and do not infer anything from their location.
- If the job requires local work authorisation the candidate does not have,
  cap the score at 40 and say so in `reasoning`.
- If the role is not one the candidate is seeking, cap the score at 50.
- `matched` and `gaps`: short phrases, max 8 words each, max 6 items each.
- `reasoning`: max 40 words.

SKILL LEVELS (in the candidate's `skill_levels`):
- verified: full credit.
- developing: partial credit only, and never describe it as an established
  skill.
- future: counts as missing.

FACTS — copy from the job text only. Use "unknown" (or null / "") when the
text does not say. Never infer salary, sponsorship or remote scope.
- employment_type: ai_training_gig = paid tasks writing, rating or labelling
  data to train AI models ("AI Trainer", "AI training", data annotation).
- remote_scope: worldwide; includes_egypt; mena_or_emea; excludes_egypt
  (remote limited to places that do not include Egypt, e.g. "US only");
  not_remote; unknown.
- min_years: the highest minimum years of experience explicitly required.
- salary: as written in the text, else "".
- visa_sponsorship: "yes" only if explicitly offered, "no" only if explicitly
  refused.
- evidence: the exact short phrases you relied on, max 30 words.

CAPS:
- employment_type internship, graduate_program or ai_training_gig: cap the
  score at 30.
- remote_scope excludes_egypt and the job is not on-site in Saudi Arabia,
  the UAE, Qatar, Kuwait, Bahrain, Oman or Egypt: cap the score at 30.

CANDIDATE
{cv}

JOB
Title: {title}
Company: {company}
Location: {location}
Work mode: {remote}

{description}
"""


# ── المدخلات ────────────────────────────────────────────────────────────

def load_cv(path: str | None = None) -> str:
    """
    السيرة كنص YAML. بنبعت المهارات والخبرة بس — مفيش اسم ولا إيميل
    ولا تليفون ولا لينكات. المقيّم مش محتاجهم، وأقل بيانات = أقل تعرّض.

    قايمة استبعاد صريحة مش ضمنية: لما اتضاف قسم contact للملف، الاختبار
    وقع فورًا وقال إن الإيميل بيتسرّب. لو كنا شايلين حقول معروفة بس،
    كان عدّى بصمت.
    """
    with open(path or CV_PATH, encoding="utf-8") as f:
        cv = yaml.safe_load(f) or {}

    SEND = ("profile", "skills", "skill_levels", "skill_synonyms",
            "not_experienced_with", "experience", "projects",
            "certificates", "seeking")
    trimmed = {k: v for k, v in cv.items() if k in SEND}
    # المشاريع المتعطّلة مش في السيرة الحالية — المقيّم مايشوفهاش
    if isinstance(trimmed.get("projects"), list):
        trimmed["projects"] = [p for p in trimmed["projects"]
                               if p.get("active") is not False]

    # الروابط بتتشال كمان: المقيّم مش هيقيّم أحسن لأنه شايف رابط الريبو،
    # وفيه اسم حسابك. بتفضل في المستند بس.
    def strip_urls(node):
        if isinstance(node, dict):
            return {k: strip_urls(v) for k, v in node.items() if k != "url"}
        if isinstance(node, list):
            return [strip_urls(x) for x in node]
        return node

    return yaml.dump(strip_urls(trimmed), allow_unicode=True,
                     sort_keys=False, width=100)


def build_prompt(cv_text: str, job: dict) -> str:
    return PROMPT.format(
        cv=cv_text,
        title=job.get("title", ""),
        company=job.get("company_name", ""),
        location=job.get("location") or "not stated",
        remote=job.get("remote_type") or "unknown",
        description=(job.get("description") or "")[:12_000],
    )


# ── النداء ──────────────────────────────────────────────────────────────

def _retry_delay(msg: str) -> float | None:
    """السيرفر بيقول تستنى قد إيه — استخدم رقمه هو، متخمنش."""
    m = re.search(r"retryDelay.{0,4}(\d+(?:\.\d+)?)s", msg)
    return float(m.group(1)) if m else None


def cv_version(path: str | None = None) -> str:
    """
    بصمة الـ CV وقت التقييم.

    لما تعدّل سيرتك، التقييمات القديمة بتبقى محسوبة على نسخة تانية.
    من غير العمود ده، أي قياس بيخلط تقييمات مبنية على بيانات مختلفة.
    """
    import hashlib
    raw = open(path or CV_PATH, encoding="utf-8").read()
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def refute(client, cv_text: str, job: dict, first: dict,
           models: list[str]) -> tuple[dict | None, int, str]:
    """
    نداء تاني بيحاول يهدّ التقييم الأول.

    بيشوف **المزايا اللي ادّعاها** الأول من غير ما يشوف رقمه — عشان
    ماينجرّش لنفس الرقم. الرقم النهائي بيبقى الأقل من الاتنين.

    ليه أصلاً: قِسنا تذبذب ±10 على نفس الوصف بالحرف. الأقل من نداءين
    بيقلّل التذبذب ده وبيخلي الخطأ في الاتجاه الآمن — وظيفة كويسة
    اتقيّمت أقل تكلفتها إعلان فاتك، ووظيفة وحشة اتقيّمت أعلى تكلفتها
    ساعة من وقتك.
    """
    matched = "\n".join(f"- {m}" for m in (first.get("matched") or [])) or "- (none)"
    prompt = REFUTER_PROMPT.format(
        matched=matched, cv=cv_text,
        title=job.get("title", ""), company=job.get("company_name", ""),
        location=job.get("location") or "not stated",
        description=(job.get("description") or "")[:12_000],
    )
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=REFUTER_SCHEMA)

    for model in models:
        for attempt in range(API_RETRIES):
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt, config=cfg)
            except Exception as exc:
                msg = str(exc)
                if _is_daily_quota(msg):
                    break
                if not genai_pool.is_transient(msg):
                    return None, 0, f"{type(exc).__name__}: {msg[:110]}"
                time.sleep((_retry_delay(msg) or 2 ** attempt) + 0.5)
                continue

            tokens = getattr(r.usage_metadata, "total_token_count", 0) or 0
            try:
                out = json.loads(r.text)
            except Exception as exc:
                return None, tokens, f"JSON باظ: {exc}"
            sc = out.get("score")
            if not isinstance(sc, int) or not 0 <= sc <= 100:
                return None, tokens, f"سكور بره المدى: {sc!r}"
            out["model"] = model
            return out, tokens, ""

    return None, 0, "كل الموديلات فشلت"


def _is_daily_quota(msg: str) -> bool:
    """
    فرق مهم: حد الدقيقة بيتحل بالانتظار، وحد اليوم لأ.
    الأول نستنى، والتاني ننط لموديل تاني فورًا.
    """
    return "429" in msg and bool(
        re.search(r"PerDay|per day|daily", msg, re.I)
        or (_retry_delay(msg) or 0) > 120
    )


def score_job(client, cv_text: str, job: dict,
              models: list[str] | None = None) -> tuple[dict | None, int, str, str]:
    """رجّع (النتيجة، التوكنز، الخطأ، الموديل اللي اشتغل)."""
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=SCHEMA,
    )
    prompt = build_prompt(cv_text, job)
    last = ""

    for model in (models or MODELS):
        for attempt in range(API_RETRIES):
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt, config=cfg)
            except Exception as exc:
                msg = str(exc)
                last = f"{type(exc).__name__}: {msg[:130]}"

                # حصة يومية خلصت → الموديل ده مات النهاردة، انط للي بعده
                if _is_daily_quota(msg):
                    print(f"   (حصة {model} اليومية خلصت — بنط للي بعده)")
                    break

                # خطأ دائم (400، 404، مفتاح غلط) → مفيش فايدة من التكرار
                if not genai_pool.is_transient(msg):
                    return None, 0, last, model

                time.sleep((_retry_delay(msg) or 2 ** attempt) + 0.5)
                continue

            tokens = getattr(r.usage_metadata, "total_token_count", 0) or 0
            try:
                out = json.loads(r.text)
            except Exception as exc:
                return None, tokens, f"JSON باظ: {exc}", model

            # المخطط بيضمن الشكل، مش المعنى. المدى بيتفحص هنا.
            s = out.get("score")
            if not isinstance(s, int) or not 0 <= s <= 100:
                return None, tokens, f"سكور بره المدى: {s!r}", model
            return out, tokens, "", model

    return None, 0, f"كل الموديلات فشلت — {last}", MODELS[-1]


# ── الطابور ─────────────────────────────────────────────────────────────

# أولوية التقييم حسب المصدر — اتحسبت من نتايج فعلية، مش من رأي.
#
# التوكنز بتتصرف في التقييم، فالمصدر المكلف هو اللي بيعدّي وظايف
# مؤهلة بتطلع تقييمها واطي. القياس (بعد استبعاد الموديل الضعيف):
#
#   remoteok       متوسط 68 · 3 فوق السبعين · 17 ألف توكن
#   ashby          متوسط 38 · 4 فوق السبعين · 262 ألف
#   greenhouse     متوسط 26 · صفر         · 296 ألف
#   himalayas      متوسط 23 · صفر         · 106 ألف
#
# 537 ألف توكن اتحرقوا على مصادر ماطلّعتش ولا فرصة. مابنحذفش
# المصادر دي — العينة لسه صغيرة والكتالوج كبير — بس بناخد اللي
# أثبت نفسه الأول. لو الحصة خلصت، بتخلص على الأحسن مش على الأول
# في الطابور.
PRIORITY = {
    "linkedin_post": 0,     # أعلى تأهيل: 23.5% (وأقرب مصدر للخليج)
    "remoteok": 1,
    "ashby": 2,
    "workable": 3,
    "greenhouse": 4,
    "lever": 4,
    "arbeitnow": 5,
    "jobicy": 5,
    "himalayas": 6,
}
DEFAULT_PRIORITY = 4


PAGE = 1000                                        # سقف PostgREST للنداء الواحد


def _all(query) -> list[dict]:
    """
    كل صفوف الاستعلام، صفحة ورا صفحة.

    PostgREST بيرجّع 1000 صف بحد أقصى — من غير خطأ ومن غير تحذير.
    لما scores عدّى الألف، الزيادة بقت مش بتتشاف: 114 وظيفة متقيّمة
    رجعت الطابور، وكل تشغيلة كانت بتعيد تقييمهم وتحرق الحصة عليهم.

    `query` دالة بترجّع استعلام جديد كل مرة، ولازم يكون مترتّب —
    من غير ترتيب ثابت الصفحات ممكن تتداخل.
    """
    out, off = [], 0
    while True:
        rows = query().range(off, off + PAGE - 1).execute().data
        out += rows
        if len(rows) < PAGE:
            return out
        off += PAGE


def pending(db, limit: int) -> list[dict]:
    """
    الوظايف اللي بتعدّي السياسة ولسه متقيّمتش بالنسخة الحالية.

    Postgres مبيعملش anti-join مباشر من PostgREST، فبنجيب المُقيَّم
    كله (بالصفحات — شوف `_all`) ونستبعده محليًا.
    """
    # التقييمات اللي اتعملت بموديل ضعيف مش بتتحسب كمنجَزة — بتتعاد
    # لما موديل كويس يبقى متاح.
    rows = _all(lambda: db.table("scores").select("job_id,model,created_at")
                .eq("scorer_version", SCORER_VERSION).order("job_id"))
    # تقييم ضعيف أقدم من أسبوعين = الوظيفة غالبًا اتقفلت؛ مش هنصرف عليها
    # حصة تاني (135 من 30 أغسطس كانوا مستنيين يتعادوا — 21 نوفمبر).
    from datetime import datetime, timedelta, timezone
    stale = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    scored = {r["job_id"] for r in rows if r.get("model") not in WEAK_MODELS
              or str(r.get("created_at") or "9999") < stale}
    weak = {r["job_id"] for r in rows if r.get("model") in WEAK_MODELS} - scored
    redo = len(weak)
    if redo:
        print(f"   ({redo} تقييم بموديل ضعيف — هيتعاد)")

    burned = {r["job_id"] for r in _all(
        lambda: db.table("score_attempts").select("job_id")
        .eq("scorer_version", SCORER_VERSION)
        .gte("attempts", MAX_ATTEMPTS).order("job_id"))}

    skip = scored | burned

    # على مرحلتين عشان نقل البيانات: الأوصاف هي الحجم كله، وأغلب
    # الوظايف بتترفض من العنوان أو المكان. فالصفحات بتيجي من غير وصف
    # (آخر SCAN_ROWS وظيفة)، والوصف بيتجاب بس للي عدّى الشرط اللازم.
    cols = "id,ats,company_name,title,location,remote_type"
    # GitHub بيحفظ 3500–8000 وظيفة في اليوم من فيدز العالم، فآخر 3000
    # صف بيغطّوا ساعات بس. المصادر المحلية (لينكدإن ومواقع التوظيف)
    # بتتجاب لوحدها بالمصدر، آخر 14 يوم، وبعدين أحدث SCAN_ROWS للباقي.
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    rows = (db.table("jobs").select(cols)
            .in_("ats", sorted(PRIORITY_SOURCES)).gte("first_seen_at", since)
            .order("id", desc=True).limit(1000).execute().data)
    cands = [r for r in rows if r["id"] not in skip and _could_pass(r)]
    have, start = {r["id"] for r in cands}, 0
    while start < SCAN_ROWS:
        rows = (db.table("jobs").select(cols)
                .order("id", desc=True).range(start, start + 499)
                .execute().data)
        if not rows:
            break
        start += 500
        cands += [r for r in rows if r["id"] not in skip and r["id"] not in have
                  and _could_pass(r)]

    # نفس الإعلان اتقيّم قبل كده برقم تاني (RemoteOK بيعيد النشر كل يوم:
    # "Platform and Integration Engineer" اتقيّم 7 مرات في أسبوع) —
    # مايروحش للموديل، التقييم بيتنسخ في run().
    index = recent_postings(db)
    pending.repeats = [(r, index[_posting_key(r)]) for r in cands
                       if _posting_key(r) in index]
    rep = {r["id"] for r, _ in pending.repeats}
    cands = [r for r in cands if r["id"] not in rep]

    # الخليج ومصر ومواقع التوظيف الأول، بعدين الريموت، بعدين الباقي —
    # الأحدث الأول جوّه كل مجموعة. من غير الترتيب ده، فيدز العالم (Lever،
    # Greenhouse) كانت بتاخد الحصة كلها ووظايف Bayt وLinkedIn الخليج
    # فضلت مستنية من غير تقييم (اتقاس 21 نوفمبر: 400+ في الطابور).
    # و"Senior" في العنوان آخر كل مجموعة: مش بنرميها (Mozn)، بس من 98
    # وظيفة Senior اتقيّمت 1–21 نوفمبر، 2 بس وصلوا 70.
    cands.sort(key=lambda r: (_priority(r), bool(_SENIOR.search(r.get("title") or "")),
                              -r["id"]))

    out, step = [], max(limit * 2, 50)
    for i in range(0, len(cands), step):
        chunk = cands[i:i + step]
        desc = {d["id"]: d.get("description") or "" for d in
                db.table("jobs").select("id,description")
                .in_("id", [r["id"] for r in chunk]).execute().data}
        for r in chunk:
            if r["id"] not in desc:
                continue
            r = {**r, "description": desc[r["id"]]}
            if targeting.evaluate(_as_job(r)).eligible:
                out.append(r)
                if len(out) >= limit:
                    return out
    return out


SCAN_ROWS = int(os.getenv("SCORE_SCAN_ROWS", "3000"))     # ~أسبوع من الوظايف
# بتتجاب بالمصدر (قليلة وسط آلاف الفيدز)
PRIORITY_SOURCES = {"linkedin_job", "linkedin_post", "wuzzuf", "bayt", "gulftalent",
                    "indeed", "naukrigulf", "wellfound"}
# ودول كلهم خليج/مصر من الأساس، حتى لو المكان مش مكتوب. المنشورات
# وWellfound من كل حتة، فبيتحكم عليهم بالمكان زي الباقي.
LOCAL_SOURCES = {"linkedin_job", "wuzzuf", "bayt", "gulftalent", "indeed", "naukrigulf"}


REPEAT_DAYS = 30
pending.repeats = []
_SENIOR = re.compile(r"\b(?:senior|sr\.?)\b", re.I)


def _posting_key(row: dict) -> tuple[str, str, str]:
    """نفس الشركة + نفس المسمى + نفس المدينة = نفس الإعلان."""
    def norm(s):
        return re.sub(r"[\W_]+", " ", str(s or "").lower()).strip()
    return (norm(row.get("company_name")), norm(row.get("title")),
            norm(str(row.get("location") or "").split(",")[0]))


def recent_postings(db) -> dict:
    """{مفتاح الإعلان: صف التقييم} لكل اللي اتقيّم آخر REPEAT_DAYS يوم."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=REPEAT_DAYS)).isoformat()
    try:
        rows = _all(lambda: db.table("scores")
                    .select("job_id,model,score_initial,refuter_score,score_final,"
                            "verdict,matched,gaps,reasoning")
                    .eq("scorer_version", SCORER_VERSION).gte("created_at", since)
                    .order("job_id"))
        rows = [r for r in rows if r.get("model") not in WEAK_MODELS]
        by_id = {r["job_id"]: r for r in rows}
        ids, out = list(by_id), {}
        for i in range(0, len(ids), 200):
            for j in (db.table("jobs").select("id,company_name,title,location")
                      .in_("id", ids[i:i + 200]).execute().data):
                out.setdefault(_posting_key(j), by_id[j["id"]])
        return out
    except Exception as exc:              # مايوقفش التقييم — أسوأ حالة نقيّم تاني
        print(f"   (مقدرتش أجيب التقييمات القديمة: {type(exc).__name__})")
        return {}


def copy_repeats(db, repeats: list) -> int:
    """انسخ تقييم الإعلان الأصلي للنسخة الجديدة — من غير ولا طلب."""
    n = 0
    for job, src in repeats:
        try:
            db.table("scores").upsert({
                "job_id": job["id"], "scorer_version": SCORER_VERSION,
                "model": "repeat", "cv_version": cv_version(),
                "score_initial": src.get("score_initial"),
                "refuter_score": src.get("refuter_score"),
                "score_final": src.get("score_final"), "verdict": src.get("verdict"),
                "matched": src.get("matched") or [], "gaps": src.get("gaps") or [],
                "reasoning": f"نفس إعلان #{src['job_id']} — التقييم منسوخ. "
                             f"{src.get('reasoning') or ''}"[:600],
                "total_tokens": 0,
            }, on_conflict="job_id,scorer_version").execute()
            n += 1
        except Exception as exc:
            print(f"   ✗ نسخ #{job['id']} — {type(exc).__name__}")
    return n


def _priority(row: dict) -> int:
    """0 = الخليج/مصر · 1 = ريموت · 2 = الباقي."""
    country, _ = targeting.detect_country(row.get("location"))
    if row.get("ats") in LOCAL_SOURCES or country in GULF_EGYPT:
        return 0
    return 1 if row.get("remote_type") == "remote" else 2


FACTS_COLUMN = [True]          # بيتقفل لوحده لو العمود مش موجود
GULF_EGYPT = {"Saudi Arabia", "United Arab Emirates", "Qatar", "Kuwait",
              "Bahrain", "Oman", "Egypt"}


def cap_by_facts(score: int, job: dict, facts: dict | None) -> int:
    """
    السقف بيتطبّق هنا كمان، مش متروك للموديل. الموديل بيستخرج الحقيقة،
    والكود بيقرر — عشان قاعدة زي "مفيش تدريب" تفضل ثابتة.
    """
    if not facts:
        return score
    if facts.get("employment_type") in CAPPED_EMPLOYMENT:
        return min(score, FACT_CAP)
    if facts.get("remote_scope") == "excludes_egypt":
        country, _ = targeting.detect_country(job.get("location"))
        onsite_ok = country in GULF_EGYPT and job.get("remote_type") != "remote"
        if not onsite_ok:
            return min(score, FACT_CAP)
    return score


def _could_pass(row: dict) -> bool:
    return targeting.could_pass(row.get("title"), row.get("location"),
                                row.get("remote_type"))


class _J:
    """أقل شكل تحتاجه targeting.evaluate."""
    __slots__ = ("title", "location", "remote_type", "description")


def _as_job(row: dict):
    j = _J()
    j.title = row.get("title") or ""
    j.location = row.get("location")
    j.remote_type = row.get("remote_type") or "unknown"
    j.description = row.get("description") or ""
    return j


# ── الفرز السريع ────────────────────────────────────────────────────────
# قبل التقييم الكامل (طلب أو اتنين لكل وظيفة)، طلب واحد بيبص على 15
# وظيفة مرة واحدة ويرمي الواضح إنه مش ليك. بموديلات Lite: حصتها منفصلة،
# فالفرز مابياكلش من حصة التقييم. ضعيفة في التقييم الدقيق (WEAK_MODELS)،
# بس "مستوى 8 سنين؟ تصنيف بيانات؟" سؤال سهل. ولو فشل، الكل بيعدّي.
TRIAGE = os.getenv("SCORER_TRIAGE", "1") not in ("0", "false", "no")
TRIAGE_MODELS = [m.strip() for m in os.getenv(
    "TRIAGE_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",") if m.strip()]
TRIAGE_BATCH = 15
TRIAGE_SCORE = 15
TRIAGE_DESC = 700

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {"jobs": {"type": "array", "items": {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "keep": {"type": "boolean"},
                       "reason": {"type": "string"}},
        "required": ["n", "keep", "reason"]}}},
    "required": ["jobs"],
}

TRIAGE_PROMPT = """You are pre-screening job postings for ONE candidate, before a detailed review.

Candidate: {profile}

For every job below return keep=true or keep=false with a short reason (under 12 words).
Set keep=false ONLY when the job is clearly not a fit:
- it requires 5+ years of experience, or a level clearly far beyond ~2 years
- it is a different field: data labeling/annotation, sales, recruiting, pure DevOps/SRE/Kubernetes administration, embedded/C/C++/firmware, mobile, front-end only, hardware, academic research needing a PhD
- it requires living in, or work authorization for, one specific country outside the Gulf and Egypt
- it requires a spoken language other than English or Arabic
- it is an internship, student or graduate program
When in doubt, keep=true. Missing a good job costs far more than one extra review.

Jobs:
{jobs}"""


def _triage_profile() -> str:
    try:
        cv = yaml.safe_load(Path(CV_PATH).read_text(encoding="utf-8"))
        p = cv.get("profile") or {}
        skills = (cv.get("skill_levels") or {}).get("verified") or []
        return (f"{p.get('title')}, about {p.get('years_experience')} years of experience, "
                f"based in {p.get('location')}, open to {', '.join(p.get('open_to') or [])}. "
                f"Targets the Gulf, Egypt and remote roles. Skills: {', '.join(skills[:28])}.")
    except Exception:
        return "AI & Automation Engineer, about 2 years of experience, Cairo, Egypt."


def _triage_text(jobs: list[dict]) -> str:
    return "\n\n".join(
        f"[{i}] {j.get('title')} | {j.get('company_name')} | {j.get('location') or '?'} | "
        f"{j.get('remote_type') or '?'}\n{(j.get('description') or '')[:TRIAGE_DESC]}"
        for i, j in enumerate(jobs, 1))


def triage(client, jobs: list[dict], models: list[str] | None = None) -> tuple[list, list, int]:
    """(اللي يعدّي، [(وظيفة، سبب الرفض)]، عدد الطلبات). الدفعة اللي تفشل بتعدّي كلها."""
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=TRIAGE_SCHEMA)
    profile = _triage_profile()
    keep, drop, calls = [], [], 0
    for i in range(0, len(jobs), TRIAGE_BATCH):
        chunk = jobs[i:i + TRIAGE_BATCH]
        verdict = None
        for model in (models or TRIAGE_MODELS):
            calls += 1
            try:
                r = client.models.generate_content(
                    model=model, config=cfg,
                    contents=TRIAGE_PROMPT.format(profile=profile, jobs=_triage_text(chunk)))
                verdict = {it["n"]: it for it in json.loads(r.text).get("jobs") or []
                           if isinstance(it.get("n"), int)}
                break
            except Exception as exc:
                print(f"   (الفرز على {model} فشل: {type(exc).__name__}: {str(exc)[:60]})")
        for n, job in enumerate(chunk, 1):
            v = (verdict or {}).get(n)
            if v and v.get("keep") is False:
                drop.append((job, str(v.get("reason") or "")[:200]))
            else:
                keep.append(job)
    return keep, drop, calls


def record_triaged(db, dropped: list) -> int:
    """المرفوض في الفرز بياخد صف تقييم واطي عشان مايرجعش الطابور تاني."""
    n = 0
    for job, why in dropped:
        try:
            db.table("scores").upsert({
                "job_id": job["id"], "scorer_version": SCORER_VERSION,
                "model": "triage", "cv_version": cv_version(),
                "score_initial": TRIAGE_SCORE, "score_final": TRIAGE_SCORE,
                "verdict": "no", "matched": [], "gaps": [why] if why else [],
                "reasoning": f"اترفض في الفرز السريع: {why}"[:600], "total_tokens": 0,
            }, on_conflict="job_id,scorer_version").execute()
            n += 1
        except Exception as exc:
            print(f"   ✗ تسجيل فرز #{job['id']} — {type(exc).__name__}")
    return n


def _note_failure(db, job_id: int, error: str) -> None:
    try:
        prev = db.table("score_attempts").select("attempts") \
            .eq("job_id", job_id).eq("scorer_version", SCORER_VERSION) \
            .execute().data
        n = (prev[0]["attempts"] if prev else 0) + 1
        db.table("score_attempts").upsert({
            "job_id": job_id, "scorer_version": SCORER_VERSION, "attempts": n,
            "last_error": error[:400],
            "last_try_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="job_id,scorer_version").execute()
    except Exception as exc:
        print(f"   (مقدرتش أسجّل الفشل — {type(exc).__name__}: {exc})"[:160])


def run(db, limit: int = BATCH) -> dict:
    """قيّم دفعة. رجّع ملخّص."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {"error": "مفيش GEMINI_API_KEY"}

    # ضعف العدد للفرز: نص الدفعة تقريبًا بيترمي، والباقي يكمّل التقييم
    jobs = pending(db, limit * 2 if TRIAGE else limit)
    copied = copy_repeats(db, pending.repeats)
    if copied:
        print(f"   ({copied} إعلان متكرر — التقييم اتنسخ من غير ما نسأل الموديل)")
    if not jobs:
        return {"pending": 0, "scored": 0, "failed": 0, "tokens": 0, "copied": copied}

    client = genai_pool.client()
    triaged = 0
    if TRIAGE:
        jobs, dropped, tcalls = triage(client, jobs)
        triaged = record_triaged(db, dropped)
        print(f"   (الفرز: {len(dropped)} اترفضوا في {tcalls} طلب Lite · {len(jobs)} يكمّلوا)")
        for j, why in dropped[:12]:
            print(f"   ↷ {j['title'][:40]:<42}{why[:50]}")
        jobs = jobs[:limit]
    cv_text = load_cv()
    started = time.time()
    scored = failed = tokens = refuted = 0
    used: dict[str, int] = {}
    cv_fingerprint = cv_version()

    # موديل خلصت حصته اليومية بيتشال من القايمة للتشغيلة كلها — مش
    # منطقي نكتشف نفس الحاجة 20 مرة.
    live = list(MODELS)

    for job in jobs:
        if time.time() - started > TIME_BUDGET:
            print(f"   (المهلة خلصت — وقفت عند {scored + failed} من {len(jobs)})")
            break
        if not live:
            print("   (كل الموديلات خلصت حصتها اليومية)")
            break

        out, tk, err, model = score_job(client, cv_text, job, live)
        tokens += tk

        if out is None:
            failed += 1
            # كل الموديلات خلصت → مفيش فايدة من باقي الدفعة. الوظايف
            # المتبقية بتفضل في الطابور للتشغيلة الجاية.
            if err.startswith("كل الموديلات"):
                live = []
            print(f"   ✗ {job['title'][:40]} — {err[:70]}")
            _note_failure(db, job["id"], err)
            continue

        used[model] = used.get(model, 0) + 1
        # الموديل اللي اشتغل بينط لأول القايمة — التالي غالبًا هينجح بيه
        if live and live[0] != model:
            live.remove(model)
            live.insert(0, model)

        # ── النداء المخاصم ──
        # بياخد المزايا اللي ادّعاها الأول ويحاول يهدّها. الرقم النهائي
        # الأقل من الاتنين — الخطأ بيروح في الاتجاه الآمن.
        #
        # لو فشل، بنكمّل بالتقييم الأول. مخاصمة ناقصة أحسن من وظيفة
        # مش متقيّمة خالص.
        ref, rtk, rerr = (None, 0, "متخطّى")
        if REFUTE and live and out["score"] >= REFUTE_FLOOR:
            ref, rtk, rerr = refute(client, cv_text, job, out, live)
            tokens += rtk

        final = min(out["score"], ref["score"]) if ref else out["score"]
        final = cap_by_facts(final, job, out.get("facts"))
        drop = out["score"] - final

        try:
            db.table("scores").upsert({
                "job_id": job["id"],
                "scorer_version": SCORER_VERSION,
                "model": model,
                "cv_version": cv_fingerprint,
                "score_initial": out["score"],
                "refuter_score": ref["score"] if ref else None,
                "refuter_notes": (ref.get("note", "")[:400] if ref else rerr[:200]),
                "refuter_model": ref.get("model") if ref else None,
                "score_final": final,
                "verdict": (ref["verdict"] if ref and ref["score"] < out["score"]
                            else out["verdict"]),
                "matched": out["matched"][:6],
                # الفجوات = فجوات الأول + اللي المخاصم اكتشفه زيادة
                "gaps": (out["gaps"] + [g for g in (ref.get("unmet") or [])
                                        if g not in out["gaps"]])[:6] if ref
                        else out["gaps"][:6],
                "reasoning": out["reasoning"][:600],
                "total_tokens": tk + rtk,
                **({"facts": out.get("facts")} if FACTS_COLUMN[0] else {}),
            }, on_conflict="job_id,scorer_version").execute()
            scored += 1
            refuted += 1 if drop else 0
            mark = f" ↓{drop}" if drop else ""
            print(f"   {final:>3}{mark:<5} {job['company_name'][:16]:<18}"
                  f"{job['title'][:40]}")
        except Exception as exc:
            # عمود facts لسه ما اتضافش (sql/007_score_facts.sql) — نكمّل من
            # غيره بدل ما التقييم كله يقع، ونقول مرة واحدة
            if FACTS_COLUMN[0] and "facts" in str(exc):
                FACTS_COLUMN[0] = False
                print("   (عمود facts مش موجود — شغّل sql/007_score_facts.sql؛ "
                      "الحقايق مش هتتحفظ لحد ساعتها)")
            failed += 1
            print(f"   ✗ حفظ فشل — {type(exc).__name__}: {exc}"[:150])
            _note_failure(db, job["id"], f"save: {exc}")

    return {"pending": len(jobs), "scored": scored, "failed": failed, "copied": copied,
            "triaged": triaged,
            "refuted": refuted, "refute_on": REFUTE,
            "cv_version": cv_fingerprint,
            "tokens": tokens, "seconds": round(time.time() - started),
            "models": used}
