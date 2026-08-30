"""
المصادر التجميعية.

الفرق عن adapters.py: هناك بنسأل شركة واحدة عن وظايفها، وهنا بنسأل
سوق كامل. المصدر التجميعي بيديك حاجتين:

  1. وظايف ريموت من شركات حوالين العالم
  2. **أسماء شركات معرفهاش** — ودي الأهم، لأن كل اسم يتحل لـ token
     بيتحول لمصدر دائم في السجل

كلهم مجانيين ومن غير مفتاح. اتأكدت من أسماء الحقول بالنداء الفعلي،
مش من التوثيق.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests

from .adapters import Job, _strip_html, HEADERS, TIMEOUT


def _iso(v) -> str | None:
    """كل مصدر بيكتب التاريخ بطريقة. رجّع ISO أو None."""
    if v in (None, "", 0):
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
        except Exception:
            return None
    s = str(v).strip()
    return s or None


def _flat(v) -> str:
    if isinstance(v, dict):
        return " ".join(str(x) for x in v.values() if isinstance(x, (str, int)))
    if isinstance(v, list):
        return ", ".join(_flat(x) for x in v)
    return str(v or "")


def _remote(location: str, explicit: bool | None = None) -> str:
    """
    المصادر دي كلها بورد ريموت — بس "ريموت" عندهم مش دايمًا "من أي مكان".
    "Remote, Germany" يعني ريموت وإنت في ألمانيا. بنسجّلها remote عشان
    مانضيّعش حاجة، والتصنيف الدقيق شغل التقييم في الشريحة الجاية.
    """
    if explicit is False:
        return "onsite"
    return "remote"


def _get(url: str) -> dict | list:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ── المصادر ─────────────────────────────────────────────────────────────

def fetch_arbeitnow(*_) -> list[Job]:
    out = []
    for j in _get("https://www.arbeitnow.com/api/job-board-api").get("data", []):
        out.append(Job(
            company_name=(j.get("company_name") or "").strip(),
            ats="arbeitnow", external_id=j.get("slug"),
            title=(j.get("title") or "").strip(),
            location=j.get("location"),
            remote_type=_remote(j.get("location", ""), j.get("remote")),
            description=_strip_html(j.get("description")),
            url=j.get("url"), posted_at=_iso(j.get("created_at")),
        ))
    return out


def fetch_remotive(*_) -> list[Job]:
    out = []
    for j in _get("https://remotive.com/api/remote-jobs?limit=200").get("jobs", []):
        loc = j.get("candidate_required_location")
        out.append(Job(
            company_name=(j.get("company_name") or "").strip(),
            ats="remotive", external_id=j.get("id"),
            title=(j.get("title") or "").strip(),
            location=loc, remote_type=_remote(loc or ""),
            description=_strip_html(j.get("description")),
            url=j.get("url"), posted_at=_iso(j.get("publication_date")),
        ))
    return out


def fetch_remoteok(*_) -> list[Job]:
    payload = _get("https://remoteok.com/api")
    out = []
    for j in payload:
        # أول عنصر في الرد إشعار قانوني مش وظيفة
        if not isinstance(j, dict) or not j.get("position"):
            continue
        loc = j.get("location") or "Remote"
        out.append(Job(
            company_name=(j.get("company") or "").strip(),
            ats="remoteok", external_id=j.get("id") or j.get("slug"),
            title=j["position"].strip(),
            location=loc, remote_type=_remote(loc),
            description=_strip_html(j.get("description")),
            url=j.get("url") or j.get("apply_url"), posted_at=_iso(j.get("date")),
        ))
    return out


def fetch_himalayas(*_) -> list[Job]:
    out = []
    for j in _get("https://himalayas.app/jobs/api?limit=200").get("jobs", []):
        loc = _flat(j.get("locationRestrictions")) or "Worldwide"
        out.append(Job(
            company_name=(j.get("companyName") or "").strip(),
            ats="himalayas", external_id=j.get("guid"),
            title=(j.get("title") or "").strip(),
            location=loc, remote_type=_remote(loc),
            description=_strip_html(j.get("description") or j.get("excerpt")),
            url=j.get("applicationLink"), posted_at=_iso(j.get("pubDate")),
        ))
    return out


def fetch_jobicy(*_) -> list[Job]:
    out = []
    for j in _get("https://jobicy.com/api/v2/remote-jobs?count=100").get("jobs", []):
        loc = _flat(j.get("jobGeo")) or "Anywhere"
        out.append(Job(
            company_name=(j.get("companyName") or "").strip(),
            ats="jobicy", external_id=j.get("id"),
            title=(j.get("jobTitle") or "").strip(),
            location=loc, remote_type=_remote(loc),
            description=_strip_html(j.get("jobDescription") or j.get("jobExcerpt")),
            url=j.get("url"), posted_at=_iso(j.get("pubDate")),
        ))
    return out


def fetch_themuse(*_) -> list[Job]:
    out = []
    for page in (1, 2):
        try:
            payload = _get(f"https://www.themuse.com/api/public/jobs?page={page}")
        except Exception:
            break
        for j in payload.get("results", []):
            loc = _flat([l.get("name") for l in (j.get("locations") or [])])
            out.append(Job(
                company_name=((j.get("company") or {}).get("name") or "").strip(),
                ats="themuse", external_id=j.get("id"),
                title=(j.get("name") or "").strip(),
                location=loc or None,
                remote_type="remote" if re.search(r"flexible|remote", loc, re.I) else "onsite",
                description=_strip_html(j.get("contents")),
                url=(j.get("refs") or {}).get("landing_page"),
                posted_at=_iso(j.get("publication_date")),
            ))
    return out


AGGREGATORS = {
    "arbeitnow": fetch_arbeitnow,
    "remotive": fetch_remotive,
    "remoteok": fetch_remoteok,
    "himalayas": fetch_himalayas,
    "jobicy": fetch_jobicy,
    "themuse": fetch_themuse,
}


def fetch_all() -> tuple[list[Job], list[dict]]:
    """اسحب من كل المصادر. مصدر واقع مايوقّفش الباقي."""
    jobs, report = [], []
    for name, fn in AGGREGATORS.items():
        try:
            got = [j for j in fn() if j.title and j.company_name]
            jobs.extend(got)
            report.append({"company": f"agg:{name}",
                           "status": "ok" if got else "empty", "count": len(got)})
        except Exception as exc:
            report.append({"company": f"agg:{name}", "status": "failed",
                           "error": f"{type(exc).__name__}: {exc}"[:300]})
    return jobs, report
