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
MODELS = [m.strip() for m in os.getenv(
    "SCORER_MODELS",
    "gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview,gemini-3.1-flash-lite"
).split(",") if m.strip()]

MODEL = MODELS[0]                                  # للعرض والتسجيل
SCORER_VERSION = os.getenv("SCORER_VERSION", "v1")

CV_PATH = os.getenv("CV_PATH", "cv.yaml")
BATCH = int(os.getenv("SCORE_BATCH", "20"))       # وظايف لكل تشغيلة
MAX_ATTEMPTS = 3                                   # قبل ما نستسلم لوظيفة
API_RETRIES = 4                                    # لكل نداء، على 429/503
TIME_BUDGET = int(os.getenv("SCORE_SECONDS", "420"))   # مهلة الـ workflow 10 دقايق

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
    ولا تليفون. المقيّم مش محتاجهم، وأقل بيانات = أقل تعرّض.
    """
    with open(path or CV_PATH, encoding="utf-8") as f:
        cv = yaml.safe_load(f) or {}
    cv.pop("education", None)
    return yaml.dump(cv, allow_unicode=True, sort_keys=False, width=100)


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
    scored = {r["job_id"] for r in
              db.table("scores").select("job_id")
              .eq("scorer_version", SCORER_VERSION).execute().data}

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
    scored = failed = tokens = 0
    used: dict[str, int] = {}

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

        try:
            db.table("scores").upsert({
                "job_id": job["id"],
                "scorer_version": SCORER_VERSION,
                "model": model,
                "score_initial": out["score"],
                "score_final": out["score"],      # الـ refuter بيعدّلها في الشريحة 7
                "verdict": out["verdict"],
                "matched": out["matched"][:6],
                "gaps": out["gaps"][:6],
                "reasoning": out["reasoning"][:600],
                "total_tokens": tk,
            }, on_conflict="job_id,scorer_version").execute()
            scored += 1
            print(f"   {out['score']:>3}  {job['company_name'][:16]:<18}{job['title'][:44]}")
        except Exception as exc:
            failed += 1
            print(f"   ✗ حفظ فشل — {type(exc).__name__}: {exc}"[:150])
            _note_failure(db, job["id"], f"save: {exc}")

    return {"pending": len(jobs), "scored": scored, "failed": failed,
            "tokens": tokens, "seconds": round(time.time() - started),
            "models": used}
