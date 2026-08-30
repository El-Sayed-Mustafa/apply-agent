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
from google import genai
from google.genai import types

from . import targeting

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

SCHEMA = {
    "type": "object",
    "properties": {
        "score":     {"type": "integer"},
        "verdict":   {"type": "string",
                      "enum": ["strong", "good", "partial", "weak", "no"]},
        "matched":   {"type": "array", "items": {"type": "string"}},
        "gaps":      {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["score", "verdict", "matched", "gaps", "reasoning"],
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

    SEND = ("profile", "skills", "not_experienced_with",
            "experience", "projects", "certificates", "seeking")
    trimmed = {k: v for k, v in cv.items() if k in SEND}

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
                if not any(c in msg for c in ("429", "503", "500", "UNAVAILABLE")):
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
                if not any(c in msg for c in ("429", "503", "500", "UNAVAILABLE")):
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

def pending(db, limit: int) -> list[dict]:
    """
    الوظايف اللي بتعدّي السياسة ولسه متقيّمتش بالنسخة الحالية.

    Postgres مبيعملش anti-join مباشر من PostgREST، فبنجيب المُقيَّم
    ونستبعده محليًا. عدد الصفوف صغير (مئات)، فده مقبول.
    """
    # التقييمات اللي اتعملت بموديل ضعيف مش بتتحسب كمنجَزة — بتتعاد
    # لما موديل كويس يبقى متاح.
    rows = db.table("scores").select("job_id,model")         .eq("scorer_version", SCORER_VERSION).execute().data
    scored = {r["job_id"] for r in rows if r.get("model") not in WEAK_MODELS}
    redo = sum(1 for r in rows if r.get("model") in WEAK_MODELS)
    if redo:
        print(f"   ({redo} تقييم بموديل ضعيف — هيتعاد)")

    burned = {r["job_id"] for r in
              db.table("score_attempts").select("job_id")
              .eq("scorer_version", SCORER_VERSION)
              .gte("attempts", MAX_ATTEMPTS).execute().data}

    skip = scored | burned
    out, start = [], 0

    while len(out) < limit:
        rows = db.table("jobs") \
            .select("id,company_name,title,location,remote_type,description") \
            .order("id", desc=True).range(start, start + 499).execute().data
        if not rows:
            break
        start += 500

        for r in rows:
            if r["id"] in skip:
                continue
            job = _as_job(r)
            if targeting.evaluate(job).eligible:
                out.append(r)
                if len(out) >= limit:
                    break
    return out


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

    jobs = pending(db, limit)
    if not jobs:
        return {"pending": 0, "scored": 0, "failed": 0, "tokens": 0}

    client = genai.Client(api_key=key)
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
        if REFUTE and live:
            ref, rtk, rerr = refute(client, cv_text, job, out, live)
            tokens += rtk

        final = min(out["score"], ref["score"]) if ref else out["score"]
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
            }, on_conflict="job_id,scorer_version").execute()
            scored += 1
            refuted += 1 if drop else 0
            mark = f" ↓{drop}" if drop else ""
            print(f"   {final:>3}{mark:<5} {job['company_name'][:16]:<18}"
                  f"{job['title'][:40]}")
        except Exception as exc:
            failed += 1
            print(f"   ✗ حفظ فشل — {type(exc).__name__}: {exc}"[:150])
            _note_failure(db, job["id"], f"save: {exc}")

    return {"pending": len(jobs), "scored": scored, "failed": failed,
            "refuted": refuted, "refute_on": REFUTE,
            "cv_version": cv_fingerprint,
            "tokens": tokens, "seconds": round(time.time() - started),
            "models": used}
