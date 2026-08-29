"""
استخرج الـ ATS token من صفحة التوظيف نفسها.

بيجرب نطاقات ومسارات معروفة، وبيدوّر في الـ HTML على لينك أي نظام توظيف.
ده اللي بتعمله بإيدك بـ F12 → Network — بس آلي.
"""
from __future__ import annotations

import io
import re
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36"}

# الأنماط اللي بندوّر عليها في الـ HTML
PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards|boards-api)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)"),
    ("greenhouse", r"greenhouse\.io/v1/boards/([a-z0-9_-]+)"),
    ("lever",      r"jobs\.(?:eu\.)?lever\.co/([a-z0-9_-]+)"),
    ("lever",      r"api\.lever\.co/v0/postings/([a-z0-9_-]+)"),
    ("ashby",      r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)"),
    ("ashby",      r"ashbyhq\.com/posting-api/job-board/([a-z0-9_.-]+)"),
    ("recruitee",  r"([a-z0-9-]+)\.recruitee\.com"),
    ("workable",   r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([a-z0-9-]+)"),
    ("smartrecruiters", r"careers\.smartrecruiters\.com/([A-Za-z0-9]+)"),
    ("workday",    r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com"),
    ("bamboohr",   r"([a-z0-9-]+)\.bamboohr\.com"),
    ("teamtailor", r"([a-z0-9-]+)\.teamtailor\.com"),
]

NOISE = {"embed", "www", "api", "job", "jobs", "boards", "share", "static", "assets"}

PATHS = ["/careers", "/careers/", "/jobs", "/en/careers", "/company/careers",
         "/about/careers", "/careers/jobs", ""]


def scan(url: str) -> list[tuple[str, str]]:
    try:
        r = requests.get(url, headers=UA, timeout=15, allow_redirects=True)
    except Exception:
        return []
    if r.status_code != 200 or not r.text:
        return []
    hits = []
    for ats, pat in PATTERNS:
        for m in re.finditer(pat, r.text, re.I):
            tok = m.group(1)
            if tok.lower() not in NOISE and len(tok) > 1:
                hits.append((ats, tok))
    seen, uniq = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq


COMPANIES = {
    "Tabby":        ["tabby.ai", "tabby.com"],
    "Qashio":       ["qashio.com"],
    "SiFi":         ["sifi.com", "sifi.sa"],
    "Foodics":      ["foodics.com"],
    "Rasan":        ["rasan.sa", "rasan.com"],
    "Bayzat":       ["bayzat.com"],
    "Riyadh Air":   ["riyadhair.com"],
    "Master Works": ["mworks.sa", "masterworks.sa"],
    "HappyRobot":   ["happyrobot.ai"],
    "Xebia":        ["xebia.com"],
    "Nana":         ["nana.sa"],
    "Salla":        ["salla.com", "salla.sa"],
    "Zid":          ["zid.sa"],
    "Lean Tech":    ["leantech.me"],
    "Unifonic":     ["unifonic.com"],
    "Mozn":         ["mozn.sa"],
}

if __name__ == "__main__":
    print(f"بمسح {len(COMPANIES)} شركة\n")
    results = {}
    for name, domains in COMPANIES.items():
        found = []
        for d in domains:
            for path in PATHS:
                for scheme in ("https://",):
                    hits = scan(f"{scheme}{d}{path}")
                    time.sleep(0.3)
                    if hits:
                        found.extend(hits)
                        break
                if found:
                    break
            if found:
                break
        seen, uniq = set(), []
        for h in found:
            if h not in seen:
                seen.add(h); uniq.append(h)
        results[name] = uniq
        if uniq:
            print(f"  ✅ {name:<14} " + " · ".join(f"{a}/{t}" for a, t in uniq[:3]))
        else:
            print(f"  ❌ {name:<14} ملقتش لينك في الـ HTML")

    print(f"\n{'=' * 60}")
    hits = {k: v for k, v in results.items() if v}
    print(f"{len(hits)} شركة فيها لينك — لازم تتأكد بـ --verify")
