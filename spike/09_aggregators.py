"""
أنهي مصدر تجميعي شغال فعلاً — ومين محتاج مفتاح؟

مش بنفترض حاجة من التوثيق. بننادي كل واحد ونشوف:
  · بيرد ولا لأ
  · بيرجّع كام وظيفة
  · فيه أسماء شركات (ده اللي يهمنا — منه بنكتشف شركات جديدة)
  · فيه أي حاجة في الخليج
"""
from __future__ import annotations

import io
import json
import re
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (compatible; apply-agent/0.1)"}
GULF = re.compile(r"saudi|riyadh|jeddah|uae|dubai|abu dhabi|kuwait|qatar|"
                  r"doha|bahrain|oman|middle east|mena|egypt|cairo", re.I)

# (الاسم، اللينك، مسار قايمة الوظايف، حقل الشركة، حقل العنوان، حقل المكان)
SOURCES = [
    ("Arbeitnow",  "https://www.arbeitnow.com/api/job-board-api",
     "data", "company_name", "title", "location"),
    ("Remotive",   "https://remotive.com/api/remote-jobs?limit=100",
     "jobs", "company_name", "title", "candidate_required_location"),
    ("RemoteOK",   "https://remoteok.com/api",
     None, "company", "position", "location"),
    ("Himalayas",  "https://himalayas.app/jobs/api?limit=100",
     "jobs", "companyName", "title", "locationRestrictions"),
    ("Jobicy",     "https://jobicy.com/api/v2/remote-jobs?count=50",
     "jobs", "companyName", "jobTitle", "jobGeo"),
    ("The Muse",   "https://www.themuse.com/api/public/jobs?page=1",
     "results", "company", "name", "locations"),
    ("WeWorkRemotely", "https://weworkremotely.com/categories/remote-programming-jobs.rss",
     None, None, None, None),
]

# دول محتاجين مفتاح — بنجرّبهم من غير مفتاح عشان نتأكد ونعرف الشكل
NEEDS_KEY = [
    ("Adzuna", "https://api.adzuna.com/v1/api/jobs/gb/search/1?results_per_page=5",
     "https://developer.adzuna.com/signup"),
    ("Jooble", "https://jooble.org/api/", "https://jooble.org/api/about"),
    ("Findwork", "https://findwork.dev/api/jobs/", "https://findwork.dev/developers/"),
]


def flat(v) -> str:
    if isinstance(v, dict):
        return " ".join(str(x) for x in v.values())
    if isinstance(v, list):
        return " ".join(flat(x) for x in v)
    return str(v or "")


def probe(name, url, path, cf, tf, lf):
    t = time.time()
    try:
        r = requests.get(url, headers=UA, timeout=25)
    except Exception as e:
        return f"❌ {name:<16} {type(e).__name__}"
    if r.status_code != 200:
        return f"❌ {name:<16} HTTP {r.status_code}"

    if url.endswith(".rss"):
        n = r.text.count("<item>")
        return f"✅ {name:<16} {n:>4} وظيفة · RSS (مفيش JSON)"

    try:
        p = r.json()
    except Exception:
        return f"⚠️  {name:<16} رد مش JSON"

    items = p if path is None else p.get(path, [])
    if not isinstance(items, list):
        return f"⚠️  {name:<16} شكل غير متوقع: {list(p)[:4]}"
    items = [i for i in items if isinstance(i, dict)]
    if not items:
        return f"⚠️  {name:<16} صفر وظيفة"

    companies = {flat(i.get(cf)).strip() for i in items if i.get(cf)}
    gulf = [i for i in items if GULF.search(flat(i.get(lf)) + " " + flat(i.get(tf)))]
    ms = (time.time() - t) * 1000
    return (f"✅ {name:<16} {len(items):>4} وظيفة · {len(companies):>3} شركة · "
            f"خليج {len(gulf):>3} · {ms:>5.0f}ms")


if __name__ == "__main__":
    print("── من غير مفتاح ─────────────────────────────────────────────")
    for s in SOURCES:
        print("  " + probe(*s))
        time.sleep(0.5)

    print("\n── محتاجين مفتاح ────────────────────────────────────────────")
    for name, url, signup in NEEDS_KEY:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            state = f"HTTP {r.status_code}"
        except Exception as e:
            state = type(e).__name__
        print(f"  🔑 {name:<10} {state:<12} تسجيل: {signup}")
        time.sleep(0.5)
