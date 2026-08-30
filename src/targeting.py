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
    return any(p.search(t) for p in _compiled()["include"])


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
    if elig == "local_only":
        return out(False, f"محلي فقط: {reason}")
    if is_remote:
        return out(True, "ريموت")
    if tier is None:
        return out(False, f"دولة برّه القايمة: {job.location or '؟'}")
    if tier == 4:
        return out(False, f"{country} — حضوري صعب، ريموت بس")
    return out(True, f"{country} · المستوى {tier}")
