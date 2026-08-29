"""
Spike: هل Gemini بيقيّم الوظايف صح؟

  python spike/01_score.py            # النتايج، ورقم 3 مخفي
  python spike/01_score.py --reveal   # كل حاجة

بنقيس 4 حاجات:
  1. التمييز  — بيفرّق بين الوظيفة الحلوة والوحشة؟
  2. الشكل    — كام مرة رجّع JSON صالح؟
  3. الثبات   — نفس الوظيفة 3 مرات، الأرقام قريبة؟
  4. الاختلاق — الفجوات اللي بيقولها مكتوبة في الإعلان فعلاً؟
"""
from __future__ import annotations

import argparse, json, os, re, statistics, sys, time
import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
MODEL = os.getenv("SPIKE_MODEL", "gemini-3.6-flash")
RUNS = 3
PACE = 1.5      # ثانية بين النداءات — الحد المجاني ضيق
ATTEMPTS = 5    # محاولات لكل نداء

# الشكل المفروض يرجع بيه. الموديل فعليًا *مش قادر* يخرج بره الشكل ده —
# ده constrained decoding، مش رجاء في الـ prompt.
SCHEMA = {
    "type": "object",
    "properties": {
        "score":     {"type": "integer"},
        "verdict":   {"type": "string", "enum": ["strong", "good", "partial", "weak", "no"]},
        "matched":   {"type": "array", "items": {"type": "string"}},
        "gaps":      {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["score", "verdict", "matched", "gaps", "reasoning"],
}

PROMPT = """You are screening a job for one specific candidate. Score how good a fit it is.

SCORING SCALE — use these anchors:
  90-100  strong   meets nearly every requirement; would be a top applicant
  70-89   good     meets the core requirements; gaps are minor or learnable
  50-69   partial  meets some core requirements; has real, material gaps
  30-49   weak     missing multiple core requirements
  0-29    no       fundamentally the wrong profile

RULES:
- List gaps ONLY for requirements explicitly written in the job description.
  Never invent a requirement that is not in the text.
- `matched` and `gaps` must each be short phrases, max 8 words.
- `reasoning` max 40 words.
- Judge the candidate as they are. Do not assume they can learn something on the job.

CANDIDATE
{cv}

JOB
Title: {title}
Company: {company}
Location: {location}

{description}
"""


def retry_delay(msg: str) -> float | None:
    """السيرفر بيقولك تستنى قد إيه — استخدم رقمه هو، متخمنش."""
    m = re.search(r"retryDelay['\"]?:\s*['\"](\d+(?:\.\d+)?)s", msg)
    return float(m.group(1)) if m else None


def score_once(client, cv_text: str, job: dict) -> tuple[dict | None, int, str]:
    """رجّع (النتيجة، التوكنز، الخطأ). بيعيد المحاولة على 429/503."""
    prompt = PROMPT.format(
        cv=cv_text, title=job["title"], company=job["company"],
        location=job["location"], description=job["description"],
    )
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=SCHEMA,
    )

    last = ""
    for attempt in range(ATTEMPTS):
        try:
            r = client.models.generate_content(model=MODEL, contents=prompt, config=cfg)
            toks = getattr(r.usage_metadata, "total_token_count", 0) or 0
            try:
                return json.loads(r.text), toks, ""
            except Exception as exc:
                return None, toks, f"JSON باظ: {exc}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {str(exc)[:120]}"
            msg = str(exc)
            # مؤقت → استنى وحاول. دائم → استسلم فورًا.
            if not any(c in msg for c in ("429", "503", "500", "UNAVAILABLE")):
                return None, 0, last
            wait = retry_delay(msg) or 2 ** attempt      # تراجع أُسّي لو مفيش تلميح
            print(f"      ↻ {job['id']} محاولة {attempt+1} — استنى {wait:.0f}ث")
            time.sleep(wait + 0.5)

    return None, 0, f"فشل بعد {ATTEMPTS} محاولات — {last}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reveal", action="store_true")
    args = ap.parse_args()

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        sys.exit("مفيش GEMINI_API_KEY")
    client = genai.Client(api_key=key)

    data = yaml.safe_load(open("spike/data.yaml", encoding="utf-8"))
    cv_text = yaml.dump(data["cv"], allow_unicode=True, sort_keys=False)
    jobs = data["jobs"]

    print(f"الموديل: {MODEL}   |   {len(jobs)} وظايف × {RUNS} تشغيلات = {len(jobs)*RUNS} نداء\n")

    results, bad_format, bad_range, total_toks = {}, [], [], 0
    t0 = time.time()

    for job in jobs:
        runs = []
        for i in range(RUNS):
            out, toks, err = score_once(client, cv_text, job)
            total_toks += toks
            time.sleep(PACE)
            if out is None:
                bad_format.append(f"{job['id']}#{i+1} — {err}")
                continue
            if not isinstance(out.get("score"), int) or not 0 <= out["score"] <= 100:
                bad_range.append(f"{job['id']}#{i+1} — score={out.get('score')!r}")
            runs.append(out)
        results[job["id"]] = runs
        print(f"  {job['id']} خلصت ({len(runs)}/{RUNS})")

    secs = time.time() - t0
    print(f"\n{'='*62}")

    # ── 1. التمييز + 3. الثبات ────────────────────────────────────────────
    print("\n【1】 التمييز و【3】 الثبات\n")
    print(f"{'':4} {'المتوقع':<14} {'التشغيلات':<16} {'المتوسط':<9} {'المدى'}")
    for job in jobs:
        runs = results[job["id"]]
        if not runs:
            print(f"{job['id']:4} {job['expect']:<14} كلهم فشلوا")
            continue
        scores = [r["score"] for r in runs]
        hide = job["id"] == "J3" and not args.reveal
        shown = "؟؟ ؟؟ ؟؟" if hide else " ".join(f"{s:>3}" for s in scores)
        mean = "؟؟" if hide else f"{statistics.mean(scores):.1f}"
        rng = max(scores) - min(scores)
        flag = "" if rng <= 8 else "  ⚠️ متذبذب"
        print(f"{job['id']:4} {job['expect']:<14} {shown:<16} {mean:<9} ±{rng}{flag}")

    # ── 2. الشكل ─────────────────────────────────────────────────────────
    total = len(jobs) * RUNS
    ok = total - len(bad_format)
    print(f"\n【2】 الشكل: {ok}/{total} JSON صالح", "✅" if ok == total else "❌")
    for b in bad_format:
        print(f"      {b}")
    if bad_range:
        print(f"      ⚠️ سكور بره 0-100: {len(bad_range)}")
        for b in bad_range:
            print(f"      {b}")

    # ── 4. الاختلاق ──────────────────────────────────────────────────────
    print("\n【4】 الاختلاق — الفجوات دي مكتوبة في الإعلان فعلاً؟\n")
    for job in jobs:
        if job["id"] == "J3" and not args.reveal:
            print(f"  {job['id']}: (مخفي)\n")
            continue
        runs = results[job["id"]]
        if not runs:
            continue
        print(f"  {job['id']} — {job['title']}")
        for g in runs[0]["gaps"]:
            print(f"      · {g}")
        print(f"    ↳ {runs[0]['reasoning']}\n")

    # ── التكلفة ──────────────────────────────────────────────────────────
    # احفظ كل حاجة خام. أي نتيجة مش متحفظة = نتيجة ضايعة.
    json.dump({"model": MODEL, "runs": RUNS, "results": results},
              open("spike/results.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n[saved] spike/results.json")

    per_call = total_toks / max(ok, 1)
    print(f"{'='*62}")
    print(f"⏱  {secs:.1f} ثانية   ({secs/max(total,1):.1f} ث/نداء)")
    print(f"🔢 {total_toks:,} توكن   ({per_call:,.0f} للنداء الواحد)")
    print(f"📈 عند 120 وظيفة/شهر ≈ {per_call*120:,.0f} توكن — اضربها في سعر الموديل")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
