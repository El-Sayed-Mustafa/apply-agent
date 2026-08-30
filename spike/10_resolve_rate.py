"""
القياس اللي بيقرر المعمارية.

خد أسماء شركات من المصادر التجميعية، وحاول توصل للـ ATS token بتاعها.
النسبة اللي تنجح هي اللي بتحدد هل حلقة الاكتشاف تستاهل ولا لأ.
"""
from __future__ import annotations

import io
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (compatible; apply-agent/0.1)"}

EP = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
    "lever":      "https://api.lever.co/v0/postings/{t}?mode=json",
    "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{t}",
    "workable":   "https://apply.workable.com/api/v1/widget/accounts/{t}",
    "recruitee":  "https://{t}.recruitee.com/api/offers/",
}


def count(ats, p) -> int:
    if ats == "lever":
        return len(p) if isinstance(p, list) else 0
    if ats == "recruitee":
        return len(p.get("offers", []))
    return len(p.get("jobs", []))


def slugs(name: str) -> list[str]:
    b = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    b = re.sub(r"\b(inc|llc|ltd|gmbh|corp|the)\b", "", b).strip()
    out = [b.replace(" ", ""), b.replace(" ", "-")]
    return [s for i, s in enumerate(out) if s and s not in out[:i]]


def try_one(args):
    ats, tok = args
    try:
        r = requests.get(EP[ats].format(t=tok), headers=UA, timeout=8)
        if r.status_code == 200:
            n = count(ats, r.json())
            if n:
                return ats, tok, n
    except Exception:
        pass
    return None


def resolve(name: str):
    combos = [(a, s) for s in slugs(name) for a in EP]
    with ThreadPoolExecutor(max_workers=10) as pool:
        for hit in pool.map(try_one, combos):
            if hit:
                return hit
    return None


def sample_companies(limit=40) -> list[str]:
    names = []
    try:
        d = requests.get("https://www.arbeitnow.com/api/job-board-api",
                         headers=UA, timeout=25).json()["data"]
        names += [j["company_name"] for j in d if j.get("company_name")]
    except Exception:
        pass
    try:
        d = requests.get("https://remoteok.com/api", headers=UA, timeout=25).json()
        names += [j["company"] for j in d if isinstance(j, dict) and j.get("company")]
    except Exception:
        pass
    seen, uniq = set(), []
    for n in names:
        k = n.strip().lower()
        if k and k not in seen:
            seen.add(k)
            uniq.append(n.strip())
    return uniq[:limit]


if __name__ == "__main__":
    names = sample_companies(40)
    print(f"بجرّب {len(names)} شركة من المصادر التجميعية\n")

    hits, t0 = [], time.time()
    for i, n in enumerate(names, 1):
        r = resolve(n)
        if r:
            ats, tok, cnt = r
            hits.append((n, ats, tok, cnt))
            print(f"  ✅ {n[:26]:<28} {ats:<11} {tok:<20} {cnt:>4} وظيفة")
        else:
            print(f"  ·  {n[:26]:<28} ملقتش")

    rate = len(hits) / max(len(names), 1) * 100
    total_jobs = sum(h[3] for h in hits)
    print(f"\n{'=' * 68}")
    print(f"نجحت:      {len(hits)}/{len(names)}  =  {rate:.0f}%")
    print(f"وظايف مفتوحة من الشركات دي: {total_jobs}")
    print(f"الزمن: {time.time() - t0:.0f}ث  ({(time.time() - t0) / len(names):.1f}ث للشركة)")
