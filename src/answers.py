"""
بنك الإجابات وسياسة المرتب.

answers.yaml ملف خاص (في .gitignore) — فيه المرتب وتصريح العمل. الملف ده
بيقراه ويحسب منه، ومفيش فيه أي موديل: المرتب رقم بيتحسب من قواعد إنت
كتبتها، مش تخمين بيتغيّر من نداء للتاني.

اتفقنا عليه 16 نوفمبر (في الشهر):

    الوضع                 أقل حاجة      الافتراضي     السقف
    مصر حضوري/هايبرد      700$          800$          1,200$
    ريموت مع شركة برّه    1,200$        1,800$        3,000$
    انتقال للخليج         8,000 ريال    9,000 ريال    17,000 ريال
    انتقال لأي مكان تاني  4,000$        4,000$        9,000$

الإعلان كاتب مرتب؟ بنطلب نص المدى بتاعهم، محصور بين الأقل والسقف.
ولو أقل رقم في الإعلان أعلى من السقف، بنطلب أقل رقم في الإعلان.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

PATH = Path("answers.yaml")

GULF = {"Saudi Arabia", "United Arab Emirates", "Qatar", "Kuwait",
        "Bahrain", "Oman"}

# الفورم بيتوقع عملة البلد. وظيفة في الكويت بـ"SAR 9,000" شكلها غلط.
LOCAL_CURRENCY = {"Saudi Arabia": "SAR", "United Arab Emirates": "AED",
                  "Qatar": "QAR", "Kuwait": "KWD", "Bahrain": "BHD",
                  "Oman": "OMR"}

# الوظيفة دي جونيور؟ الطلب بيقل 15%، ومحصور في الأرضية برضه
JUNIOR = re.compile(r"\b(junior|jr\.?|entry[\s-]level|associate)\b", re.I)
JUNIOR_FACTOR = 0.85

# "120,000 - 150,000 USD per year" · "SAR 15k/month" · "$40/hour"
_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?")
_CUR = {"$": "USD", "usd": "USD", "sar": "SAR", "aed": "AED", "qar": "QAR",
        "kwd": "KWD", "bhd": "BHD", "omr": "OMR", "egp": "EGP", "€": "EUR",
        "eur": "EUR", "£": "GBP", "gbp": "GBP"}


def load(path: Path | None = None) -> dict:
    try:
        return yaml.safe_load((path or PATH).read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def situation(job: dict, country: str | None) -> str:
    if (job.get("remote_type") or "") == "remote":
        return "remote"
    if country == "Egypt":
        return "egypt_local"
    if country in GULF:
        return "gulf_relocation"
    return "other_relocation"


def _rate(currency: str, policy: dict) -> float:
    if currency == "USD":
        return 1.0
    return float(((policy.get("salary") or {}).get("per_usd") or {})
                 .get(currency) or 0)


def band(job: dict, country: str | None, policy: dict) -> dict:
    """حدود الوضع ده بالدولار، ومعاها العملة الأصلية بتاعته."""
    b = ((policy.get("salary") or {}).get("bands") or {}).get(
        situation(job, country)) or {}
    cur = b.get("currency", "USD")
    r = _rate(cur, policy) or 1.0
    return {"currency": cur if _rate(cur, policy) else "USD",
            **{k: float(b.get(k, 0)) / r for k in ("floor", "default", "ceiling")}}


def parse_salary(text: str, per_usd: dict) -> tuple[float, float] | None:
    """
    المرتب المكتوب في الإعلان → (أقل، أكتر) بالدولار في الشهر.
    لو مش واضح العملة أو الأرقام، None — ومنخمنش.
    """
    t = (text or "").lower()
    if not t.strip():
        return None
    cur = next((c for k, c in _CUR.items() if k in t), None)
    if not cur:
        return None
    nums = [float(n.replace(",", "")) * (1000 if k else 1)
            for n, k in _NUM.findall(t)]
    nums = [n for n in nums if n >= 1]
    if not nums:
        return None
    if re.search(r"\b(year|annual|annum|yr|p\.a\.)\b", t):
        per_month = 1 / 12
    elif re.search(r"\b(hour|hr|hourly)\b", t):
        per_month = 160
    elif re.search(r"\b(week|weekly)\b", t):
        per_month = 4.33
    else:
        per_month = 1
    rate = 1.0 if cur == "USD" else float(per_usd.get(cur) or 0)
    if not rate:
        return None
    usd = [n * per_month / rate for n in nums[:2]]
    return min(usd), max(usd)


def expected_salary(job: dict, facts: dict | None, country: str | None,
                    policy: dict) -> float:
    """
    الرقم اللي هيتكتب في "Expected salary" — بالدولار في الشهر، من غير
    تقريب (التقريب بيحصل في العرض بعملة الفورم، عشان 8,000 ريال تفضل
    8,000 ريال).
    """
    b = band(job, country, policy)
    posted = parse_salary((facts or {}).get("salary", ""),
                          (policy.get("salary") or {}).get("per_usd") or {})
    if posted:
        # الشركة كاتبة مرتب أعلى من سقفك كله؟ اطلب أقل رقم هي كتبته —
        # 3,000$ قصاد إعلان بـ11,000$ بتبان ضعف مش تواضع (قرارك، 16 نوفمبر)
        if posted[0] > b["ceiling"]:
            return posted[0]
        target = (posted[0] + posted[1]) / 2
    else:
        target = b["default"]
        if JUNIOR.search(job.get("title") or "") or (
                (facts or {}).get("min_years") is not None
                and facts["min_years"] <= 1):
            target *= JUNIOR_FACTOR
    return min(max(target, b["floor"]), b["ceiling"])


def minimum_acceptable(job: dict, country: str | None, policy: dict) -> float:
    """"أقل مرتب تقبله" = أرضية الوضع ده، مش رقم واحد لكل الدنيا."""
    return band(job, country, policy)["floor"]


def in_currency(usd_per_month: float, currency: str, policy: dict,
                annual: bool = False) -> str:
    """نفس الرقم بالعملة اللي الفورم طالبها، شهري أو سنوي."""
    rate = _rate(currency, policy)
    if not rate:
        currency, rate = "USD", 1.0
    amount = usd_per_month * rate * (12 if annual else 1)
    # الدينار الكويتي والبحريني أرقامهم صغيرة — 737 مش 750
    step = 100 if amount >= 5000 else 50 if amount >= 1500 else 10
    amount = int(round(amount / step) * step)
    return f"{currency} {amount:,} / {'year' if annual else 'month'}"


def expected_text(job: dict, facts: dict | None, country: str | None,
                  policy: dict, currency: str | None = None,
                  annual: bool = False) -> str:
    """بعملة الفورم لو محددة، وإلا بعملة الوضع (ريال للخليج، دولار للباقي)."""
    usd = expected_salary(job, facts, country, policy)
    return in_currency(usd, currency or band(job, country, policy)["currency"],
                       policy, annual)


def current_salary(required: bool, policy: dict) -> str:
    """رقم المرتب الحالي بيشد العرض لتحت — بيتكتب بس لو السؤال إجباري."""
    s = policy.get("salary") or {}
    if s.get("current_only_if_required", True) and not required:
        return ""
    return in_currency(float(s.get("current", 0)), "USD", policy)


def work_authorization(country: str | None, remote: bool, policy: dict) -> str:
    wa = policy.get("work_authorization") or {}
    if remote:
        return wa.get("remote", "")
    return wa.get(country or "", wa.get("other", ""))
