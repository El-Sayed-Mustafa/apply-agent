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
MAX_BULLETS = int(os.getenv("TAILOR_MAX_BULLETS", "16"))
API_RETRIES = 4

# حقلين منفصلين مش قايمة واحدة: كده تركيبة السيرة مضمونة بالبنية
# نفسها — خبرة ومشاريع — مش متروكة لمزاج الموديل في كل نداء.
SCHEMA = {
    "type": "object",
    "properties": {
        "experience_ids": {"type": "array", "items": {"type": "string"}},
        "project_ids":    {"type": "array", "items": {"type": "string"}},
        "headline":       {"type": "string"},
        "note":           {"type": "string"},
    },
    "required": ["experience_ids", "project_ids", "headline", "note"],
}

PROMPT = """Select which of the candidate's existing CV bullets to show for this
job, and in what order. The CV must fit on ONE dense page.

YOU MAY ONLY RETURN IDs FROM THIS LIST. Nothing else exists.
{catalogue}

RETURN TWO SEPARATE LISTS:

`experience_ids` — 8 to 11 ids from the EXPERIENCE block, most relevant first.
`project_ids`    — 5 or 6 ids drawn from exactly 2 or 3 DIFFERENT projects,
                   strongest project first, and **2 to 3 ids per project** so
                   no project looks thinner than the others. Pick the projects
                   that best prove this job's requirements, not the biggest.

RULES:
- Never invent an id. Never invent experience.
- Order matters: the page is trimmed from the end, so the last ids you return
  are the ones most likely to be cut. Put the strongest first.
- Within a single employer, lead with the bullet carrying the largest concrete
  result, then the next largest. A reader scanning one company reads top-down
  and stops at the first number.
- Prefer bullets carrying concrete numbers — those are what a reader stops on.
- Select a bullet because the job description asks for that thing, not because
  it sounds impressive.
- `headline`: a job title line, max 6 words, drawn from what the candidate
  actually does. Not a slogan.
- `note`: 2 sentences the candidate could send a recruiter. Reference only
  things covered by the bullets you selected.

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
                bullets[bid] = {**b, "parent": head,
                                "parent_id": entry.get("id", ""), "block": block}
                tags = ", ".join(b.get("tags") or [])
                lines.append(f"    {bid}: {b.get('text','')}"
                             + (f"   ({tags})" if tags else ""))

    return bullets, "\n".join(lines)


def full(path: str | None = None) -> dict:
    """الملف كامل — للتركيب بس. فيه بيانات الاتصال."""
    with open(path or CV_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def context(path: str | None = None) -> dict:
    """
    اللي بيتبعت للموديل. **من غير contact** — تقليل بيانات:
    المقيّم مش هيقيّم أحسن لأنه عارف تليفونك.
    """
    cv = full(path)
    return {"profile": {k: v for k, v in (cv.get("profile") or {}).items()},
            "skills": cv.get("skills", {}),
            "not_experienced_with": cv.get("not_experienced_with", []),
            "seeking": cv.get("seeking", {})}


# ── الاختيار ────────────────────────────────────────────────────────────

def validate(raw_ids, known: dict[str, dict],
             block: str | None = None) -> tuple[list[str], list[str]]:
    """
    الحاجز. أي معرّف مش في الكتالوج بيتشال.

    الاختبار على الدالة دي لازم مايفشلش أبدًا — ده test مش eval.
    لو عدّى معرّف مخترع، معناه إن فيه نص في الـ CV مالوش أصل.

    block بيقيّد كمان على القسم: معرّف خبرة اترجع في قايمة المشاريع
    بيتشال — عشان تركيبة الصفحة تفضل زي ما اتصممت.
    """
    kept, dropped, seen = [], [], set()
    for x in (raw_ids or []):
        bid = str(x).strip()
        ok = bid in known and bid not in seen
        if ok and block and known[bid].get("block") != block:
            ok = False
        if ok:
            seen.add(bid)
            kept.append(bid)
        else:
            dropped.append(bid)
    return kept[:MAX_BULLETS], dropped


MAX_PER_PROJECT = 3
MIN_PER_PROJECT = 2


def balance_projects(ids: list[str], known: dict) -> list[str]:
    """
    وازن النقط بين المشاريع.

    الموديل كان بيدي 4 نقط لمشروع وواحدة للتاني — فالتاني بيبان
    ضعيف حتى لو هو أقوى. هنا بنسقّف كل مشروع عند 3 وبنشيل أي مشروع
    مالوش نقطتين على الأقل، عشان كل مشروع معروض يبان مكتمل.

    قاعدة في الكود مش رجاء في الـ prompt — الموديل بينسى، والكود لأ.
    """
    by_project: dict[str, list[str]] = {}
    for bid in ids:
        by_project.setdefault(known[bid].get("parent_id", ""), []).append(bid)

    keep = {pid: b[:MAX_PER_PROJECT] for pid, b in by_project.items()
            if len(b) >= MIN_PER_PROJECT}

    # لو كله اتشال (كل مشروع بنقطة واحدة)، سيب الأقوى بنقطته
    if not keep and by_project:
        first = next(iter(by_project))
        keep = {first: by_project[first]}

    return [b for b in ids if b in {x for v in keep.values() for x in v}]


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

            exp, d1 = validate(out.get("experience_ids"), known, block="experience")
            proj, d2 = validate(out.get("project_ids"), known, block="projects")
            proj = balance_projects(proj, known)
            kept, dropped = exp + proj, d1 + d2
            if len(exp) < 3 or len(proj) < 2:
                return None, f"اختار {len(exp)} خبرة و{len(proj)} مشاريع — قليل"

            return Tailored(
                bullet_ids=kept,
                headline=re.sub(r"\s+", " ", out.get("headline", "")).strip()[:80],
                note=re.sub(r"\s+", " ", out.get("note", "")).strip()[:400],
                dropped=dropped,
                model=model,
                tokens=getattr(r.usage_metadata, "total_token_count", 0) or 0,
            ), ""

    return None, f"كل الموديلات فشلت — {last}"
