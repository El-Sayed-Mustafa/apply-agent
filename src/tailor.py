"""
تظبيط السيرة على وظيفة معيّنة.

القرار المعماري الأهم في المشروع كله:

    الموديل بيرجّع **معرّفات** — ["b1","b7","b3"] — مش نصوص.

النص نفسه بيتقرا من cv.yaml عندنا. يعني الموديل مش قادر يكتب خبرة مش
موجودة، لأنه أصلاً مش بيكتب نص. ده مش "ممنوع في الـ prompt" — ده
**مستحيل في التصميم**.

ولو رجّع معرّف مش موجود، بيتشال بصمت والباقي بيعدّي. الاختلاق هنا
مش حالة نتعامل معاها — هو حالة مالهاش مسار أصلاً.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import yaml
from google.genai import types

from .scoring import MODELS, _is_daily_quota, _retry_delay

MODEL_LIST = MODELS
TAILOR_VERSION = os.getenv("TAILOR_VERSION", "v1")
CV_PATH = os.getenv("CV_PATH", "cv.yaml")
MAX_BULLETS = int(os.getenv("TAILOR_MAX_BULLETS", "8"))
API_RETRIES = 4

SCHEMA = {
    "type": "object",
    "properties": {
        # القايمة المقفولة. الترتيب معنى: الأهم للوظيفة دي الأول.
        "bullet_ids": {"type": "array", "items": {"type": "string"}},
        "headline":   {"type": "string"},
        "note":       {"type": "string"},
    },
    "required": ["bullet_ids", "headline", "note"],
}

PROMPT = """Select which of the candidate's existing CV bullets to show for this job,
and in what order.

YOU MAY ONLY RETURN IDs FROM THIS LIST. Nothing else exists.
{catalogue}

RULES:
- Return between 4 and {max_bullets} ids, most relevant to THIS job first.
- Never invent an id. Never invent experience.
- Do not select a bullet just because it sounds impressive — select it because
  the job description asks for that thing.
- `headline`: a job title line for the CV, max 6 words, drawn from what the
  candidate actually does. Not a slogan.
- `note`: 2 sentences the candidate could send a recruiter. Reference only
  things covered by the bullets you selected. No claims beyond them.

JOB
Title: {title}
Company: {company}
Location: {location}

{description}
"""


@dataclass
class Tailored:
    bullet_ids: list[str]
    headline: str
    note: str
    dropped: list[str] = field(default_factory=list)   # معرّفات مخترعة اتشالت
    model: str = ""
    tokens: int = 0


# ── كتالوج النقط ────────────────────────────────────────────────────────

def load_catalogue(path: str | None = None) -> tuple[dict[str, dict], str]:
    """
    رجّع (المعرّف → النقطة، النص اللي بيتبعت للموديل).

    كل نقطة بتتبعت بمعرّفها ووسومها. الموديل بيشوف الكتالوج كله
    ويختار منه — ومش شايف أي طريقة تكتب حاجة من عنده.
    """
    with open(path or CV_PATH, encoding="utf-8") as f:
        cv = yaml.safe_load(f) or {}

    bullets: dict[str, dict] = {}
    lines: list[str] = []

    for block, label in (("experience", "EXPERIENCE"), ("projects", "PROJECTS")):
        entries = cv.get(block) or []
        if entries:
            lines.append(f"\n{label}")
        for entry in entries:
            head = entry.get("role") or entry.get("name") or ""
            lines.append(f"  [{head}]")
            for b in entry.get("bullets") or []:
                bid = b.get("id")
                if not bid:
                    continue
                bullets[bid] = {**b, "parent": head, "block": block}
                tags = ", ".join(b.get("tags") or [])
                lines.append(f"    {bid}: {b.get('text','')}"
                             + (f"   ({tags})" if tags else ""))

    return bullets, "\n".join(lines)


def context(path: str | None = None) -> dict:
    """المهارات والملف الشخصي — سياق للموديل، مش مادة للاختيار."""
    with open(path or CV_PATH, encoding="utf-8") as f:
        cv = yaml.safe_load(f) or {}
    return {"profile": cv.get("profile", {}), "skills": cv.get("skills", {}),
            "seeking": cv.get("seeking", {}), "education": cv.get("education", [])}


# ── الاختيار ────────────────────────────────────────────────────────────

def validate(raw_ids, known: dict[str, dict]) -> tuple[list[str], list[str]]:
    """
    الحاجز. أي معرّف مش في الكتالوج بيتشال.

    الاختبار على الدالة دي لازم مايفشلش أبدًا — ده test مش eval.
    لو عدّى معرّف مخترع، معناه إن فيه نص في الـ CV مالوش أصل.
    """
    kept, dropped, seen = [], [], set()
    for x in (raw_ids or []):
        bid = str(x).strip()
        if bid in known and bid not in seen:
            seen.add(bid)
            kept.append(bid)
        else:
            dropped.append(bid)
    return kept[:MAX_BULLETS], dropped


def tailor(client, job: dict, cv_path: str | None = None,
           models: list[str] | None = None) -> tuple[Tailored | None, str]:
    """رجّع (النتيجة، الخطأ)."""
    known, catalogue = load_catalogue(cv_path)
    if not known:
        return None, "cv.yaml مفيهوش نقط بمعرّفات"

    prompt = PROMPT.format(
        catalogue=catalogue, max_bullets=MAX_BULLETS,
        title=job.get("title", ""), company=job.get("company_name", ""),
        location=job.get("location") or "not stated",
        description=(job.get("description") or "")[:10_000],
    )
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=SCHEMA)

    import time
    last = ""
    for model in (models or MODEL_LIST):
        for attempt in range(API_RETRIES):
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt, config=cfg)
            except Exception as exc:
                msg = str(exc)
                last = f"{type(exc).__name__}: {msg[:120]}"
                if _is_daily_quota(msg):
                    break
                if not any(c in msg for c in ("429", "503", "500", "UNAVAILABLE")):
                    return None, last
                time.sleep((_retry_delay(msg) or 2 ** attempt) + 0.5)
                continue

            try:
                out = json.loads(r.text)
            except Exception as exc:
                return None, f"JSON باظ: {exc}"

            kept, dropped = validate(out.get("bullet_ids"), known)
            if len(kept) < 3:
                return None, f"اختار {len(kept)} نقط بس — قليل أوي"

            return Tailored(
                bullet_ids=kept,
                headline=re.sub(r"\s+", " ", out.get("headline", "")).strip()[:80],
                note=re.sub(r"\s+", " ", out.get("note", "")).strip()[:400],
                dropped=dropped,
                model=model,
                tokens=getattr(r.usage_metadata, "total_token_count", 0) or 0,
            ), ""

    return None, f"كل الموديلات فشلت — {last}"
