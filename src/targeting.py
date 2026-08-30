"""
سياسة الاستهداف — هل الوظيفة دي تخصني أصلاً؟

مفيش AI هنا عن قصد. ده الـ baseline: تعبيرات نصية، مجانية وفورية وحتمية.
لما نوصل للتقييم بالـ LLM في الشريحة 3، هنقيس هل الموديل أحسن من الملف
ده فعلاً — ولو مش أحسن، نسيبه.

الترتيب مهم: الرفض بيتفحص قبل القبول، لأن جملة
"we do not offer visa sponsorship" فيها كلمة sponsorship برضه.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

POLICY_PATH = os.getenv("TARGETING_PATH", "targeting.yaml")

# قد إيه ناخد من الوصف. الشروط الحقيقية بتيجي في الآخر عادة
# ("Requirements", "Eligibility")، فبناخد النص كله لحد حد معقول.
MAX_TEXT = 20_000


@dataclass
class Verdict:
    eligible: bool
    reason: str
    eligibility: str          # open | local_only | unknown
    country: str | None
    tier: int | None          # 1..4، أو None لو مش في القايمة
    role_match: bool


@lru_cache(maxsize=1)
def _policy() -> dict:
    with open(POLICY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def _compiled() -> dict:
    p = _policy()
    el, ro = p.get("eligibility", {}), p.get("roles", {})
    c = lambda pats: [re.compile(x, re.I) for x in (pats or [])]
    return {
        "blocking": c(el.get("blocking")),
        "open": c(el.get("open")),
        "include": c(ro.get("include")),
        "exclude": c(ro.get("exclude")),
    }


@lru_cache(maxsize=1)
def _countries() -> list[tuple[str, int]]:
    """(اسم الدولة بحروف صغيرة، المستوى) — الأطول الأول عشان
    'United Arab Emirates' متتلغبطش مع 'United States'."""
    groups = _policy().get("countries", {})
    out = []
    for key, names in groups.items():
        tier = int(re.search(r"\d", key).group())
        out += [(n.lower(), tier) for n in (names or [])]
    return sorted(out, key=lambda x: -len(x[0]))


# ── التصنيف ─────────────────────────────────────────────────────────────

def classify_eligibility(text: str) -> tuple[str, str]:
    """رجّع (التصنيف، السبب)."""
    t = (text or "")[:MAX_TEXT]
    for pat in _compiled()["blocking"]:
        m = pat.search(t)
        if m:
            return "local_only", m.group(0).strip()[:80]
    for pat in _compiled()["open"]:
        m = pat.search(t)
        if m:
            return "open", m.group(0).strip()[:80]
    return "unknown", ""


def detect_country(location: str | None) -> tuple[str | None, int | None]:
    loc = (location or "").lower()
    if not loc:
        return None, None
    for name, tier in _countries():
        if name in loc:
            return name.title(), tier
    return None, None


def matches_role(title: str) -> bool:
    t = title or ""
    if any(p.search(t) for p in _compiled()["exclude"]):
        return False
    if _seniority().get("exclude_senior_in_title") and _SENIOR_TITLE.search(t):
        return False
    return any(p.search(t) for p in _compiled()["include"])


# ── الأقدمية ────────────────────────────────────────────────────────────

_SENIOR_TITLE = re.compile(r"\b(?:senior|sr\.?)\b", re.I)

# "5+ years experience" · "minimum of 7 years" · "at least 8 years"
# · "5-8 years of relevant experience"
_YEARS = re.compile(
    r"(?:(?:at\s+least|minimum\s+(?:of\s+)?|min\.?\s*)\s*)?"
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-\s*\d{1,2}\s*)?"
    r"(?:\+\s*)?years?"
    r"(?:\s+(?:of\s+)?(?:\w+\s+){0,3}?experience|\s+experience|\s*\+)",
    re.I,
)


@lru_cache(maxsize=1)
def _seniority() -> dict:
    return _policy().get("seniority", {}) or {}


def required_years(text: str) -> int | None:
    """
    أعلى عدد سنين مطلوب في الإعلان.

    بناخد الأعلى مش الأقل: إعلان بيقول "3 years in Python, 7 years in
    distributed systems" هو فعليًا وظيفة 7 سنين.
    """
    found = [int(m) for m in _YEARS.findall((text or "")[:MAX_TEXT])
             if 0 < int(m) <= 30]
    return max(found) if found else None


def is_too_senior(text: str) -> tuple[bool, str]:
    cap = _seniority().get("max_years_required")
    if not cap:
        return False, ""
    y = required_years(text)
    if y is not None and y >= cap:
        return True, f"بيطلب {y} سنين خبرة"
    return False, ""


def evaluate(job) -> Verdict:
    """
    القرار الكامل. الوظيفة بتعدي لو:
      · الدور مناسب،  و
      · (ريموت أو دولة في القايمة)،  و
      · مش مرفوضة صراحةً

    "unknown" بتعدّي عن قصد — أغلب الإعلانات مبتقولش حاجة عن التأشيرة،
    ورفضها معناه إننا نرمي أغلب السوق. تكلفة الخطأ هنا غير متماثلة:
    وظيفة زيادة تقراها = دقيقة ضايعة. وظيفة ضايعة = فرصة ضايعة.
    """
    role_ok = matches_role(job.title)
    country, tier = detect_country(job.location)
    is_remote = job.remote_type == "remote"
    elig, reason = classify_eligibility(
        f"{job.title}\n{job.location or ''}\n{job.description}"
    )

    def out(ok, why):
        return Verdict(ok, why, elig, country, tier, role_ok)

    if not role_ok:
        return out(False, "الدور مش مناسب")

    too_senior, why = is_too_senior(job.description)
    if too_senior:
        return out(False, why)

    if elig == "local_only":
        return out(False, f"محلي فقط: {reason}")
    if is_remote:
        return out(True, "ريموت")
    if tier is None:
        return out(False, f"دولة برّه القايمة: {job.location or '؟'}")
    if tier == 4:
        return out(False, f"{country} — حضوري صعب، ريموت بس")
    return out(True, f"{country} · المستوى {tier}")
