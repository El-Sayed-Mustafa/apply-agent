"""
اكتشاف الـ ATS token لأي شركة — بالتجريب، من غير AI.

بيولّد صيغ محتملة للاسم، وبيجرّبها على كل نظام توظيف.
اللي يرجّع وظايف = ده الـ token الصح.
"""
from __future__ import annotations

import io
import re
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

TIMEOUT = 12
UA = {"User-Agent": "Mozilla/5.0 (compatible; job-registry-check/1.0)"}

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true",
    "lever":      "https://api.lever.co/v0/postings/{t}?mode=json",
    "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{t}",
    "recruitee":  "https://{t}.recruitee.com/api/offers/",
    "workable":   "https://apply.workable.com/api/v1/widget/accounts/{t}?details=true",
}


def count_jobs(ats: str, payload) -> int:
    """كل نظام بيلف الوظايف بشكل مختلف."""
    try:
        if ats == "greenhouse":
            return len(payload.get("jobs", []))
        if ats == "lever":
            return len(payload) if isinstance(payload, list) else 0
        if ats == "ashby":
            return len(payload.get("jobs", []))
        if ats == "recruitee":
            return len(payload.get("offers", []))
        if ats == "workable":
            return len(payload.get("jobs", []))
    except Exception:
        pass
    return 0


def variants(name: str) -> list[str]:
    base = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    flat = base.replace(" ", "")
    dash = base.replace(" ", "-")
    out = [flat, dash, flat + "ai", dash + "-ai", flat + "inc", flat + "hq",
           flat + "tech", flat + "technologies", "the" + flat]
    if " " in base:                       # أول كلمة لوحدها
        out.insert(2, base.split()[0])
    seen, uniq = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def probe(ats: str, token: str) -> int | None:
    """رجّع عدد الوظايف، أو None لو مش موجود."""
    try:
        r = requests.get(ENDPOINTS[ats].format(t=token), headers=UA, timeout=TIMEOUT)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        return count_jobs(ats, r.json())
    except Exception:
        return None


def find(name: str, hint: str | None = None) -> tuple[str, str, int] | None:
    order = [hint] + [a for a in ENDPOINTS if a != hint] if hint else list(ENDPOINTS)
    for token in variants(name):
        for ats in order:
            n = probe(ats, token)
            time.sleep(0.25)
            if n:
                return ats, token, n
    return None


TARGETS = [
    # (الاسم، النظام اللي مكتوب في السجل حاليًا)
    ("Cohere",       "lever"),
    ("Tabby",        "lever"),
    ("Qashio",       "greenhouse"),
    # المستهدفين من التحليل
    ("SiFi",         None),
    ("Master Works", None),
    ("Riyadh Air",   None),
    ("Xebia",        None),
    ("Fuse Energy",  None),
    ("HappyRobot",   None),
    ("Elios AI",     None),
    ("Rasan",        None),
    ("Foodics",      None),
    ("Tamara",       None),
    ("Careem",       None),
    ("Bayzat",       None),
]

if __name__ == "__main__":
    print(f"بجرّب {len(TARGETS)} شركة على {len(ENDPOINTS)} أنظمة\n")
    found, missing = [], []
    for name, hint in TARGETS:
        hit = find(name, hint)
        if hit:
            ats, token, n = hit
            found.append((name, ats, token, n))
            print(f"  ✅ {name:<16} {ats:<11} {token:<22} {n:>4} وظيفة")
        else:
            missing.append(name)
            print(f"  ❌ {name:<16} ملقتش")

    print(f"\n{'=' * 62}\n{len(found)} لقيتها · {len(missing)} لأ\n")
    if found:
        print("الصق ده في companies.yaml:\n")
        for name, ats, token, n in found:
            print(f"  - name: {name}\n    ats: {ats}\n    token: {token}\n    tier: 1\n")
    if missing:
        print(f"محتاجة بحث يدوي: {', '.join(missing)}")
