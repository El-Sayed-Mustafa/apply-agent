"""
محوّلات المصادر.

كل شركة بتستخدم نظام توظيف (ATS) مختلف، وكل نظام بيرجّع الداتا بشكل مختلف.
الملف ده مهمته الوحيدة: يحوّل أي شكل منهم لشكل واحد موحّد اسمه Job.

كلهم روابط عامة، من غير مفاتيح ولا تسجيل دخول — دي الواجهات الرسمية
اللي الشركات نفسها بتستخدمها عشان تعرض وظايفها على موقعها.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

TIMEOUT = 20
HEADERS = {"User-Agent": "apply-agent/0.1 (personal job search tool)"}


# ---------------------------------------------------------------------------
# الشكل الموحّد
# ---------------------------------------------------------------------------

@dataclass
class Job:
    company_name: str
    ats: str
    external_id: str
    title: str
    location: str | None = None
    remote_type: str = "unknown"     # remote | hybrid | onsite | unknown
    description: str = ""
    url: str | None = None
    posted_at: str | None = None     # ISO-8601
    content_hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.content_hash = self._hash()

    def _hash(self) -> str:
        """
        البصمة. لو الشركة أعادت نشر نفس الوظيفة برقم جديد، البصمة هتفضل
        زي ما هي والوظيفة مش هتتسجل مرتين.

        بنطبّع النص الأول (حروف صغيرة، مسافات موحّدة) عشان اختلاف بسيط
        في التنسيق ما يعملش بصمة جديدة.

        الموقع داخل في البصمة عن قصد: نفس الوظيفة بالظبط في الرياض وفي
        القاهرة = فرصتين مختلفتين، ولازم الاتنين يوصلوا. التكلفة إن الشركة
        لو صلّحت كتابة اسم المدينة هتتسجل كأنها جديدة — وده أرخص بكتير من
        إننا نضيّع وظيفة.
        """
        raw = "|".join([
            _normalise(self.company_name),
            _normalise(self.title),
            _normalise(self.location),
            _normalise(self.description)[:4000],
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def as_row(self) -> dict:
        return {
            "company_name": self.company_name,
            "ats": self.ats,
            "external_id": str(self.external_id),
            "title": self.title,
            "location": self.location,
            "remote_type": self.remote_type,
            "description": self.description[:20000],
            "url": self.url,
            "posted_at": self.posted_at,
            "content_hash": self.content_hash,
        }


def _normalise(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    return BeautifulSoup(html.unescape(raw), "html.parser").get_text(" ", strip=True)


def _guess_remote(*parts: str | None) -> str:
    blob = " ".join(p or "" for p in parts).lower()
    if "hybrid" in blob:
        return "hybrid"
    if "remote" in blob:
        return "remote"
    if any(w in blob for w in ("on-site", "onsite", "in office", "in-office")):
        return "onsite"
    return "unknown"


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------------------
# المحوّلات
# ---------------------------------------------------------------------------

def fetch_greenhouse(name: str, token: str) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    payload = _get(url).json()
    jobs = []
    for j in payload.get("jobs", []):
        location = (j.get("location") or {}).get("name")
        description = _strip_html(j.get("content"))
        jobs.append(Job(
            company_name=name,
            ats="greenhouse",
            external_id=j.get("id"),
            title=j.get("title", "").strip(),
            location=location,
            remote_type=_guess_remote(location, j.get("title"), description[:600]),
            description=description,
            url=j.get("absolute_url"),
            posted_at=j.get("updated_at"),
        ))
    return jobs


def fetch_lever(name: str, token: str) -> list[Job]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    payload = _get(url).json()
    jobs = []
    for j in payload:
        cats = j.get("categories") or {}
        location = cats.get("location")
        description = j.get("descriptionPlain") or _strip_html(j.get("description"))
        posted = j.get("createdAt")
        posted_iso = (
            datetime.fromtimestamp(posted / 1000, tz=timezone.utc).isoformat()
            if isinstance(posted, (int, float)) else None
        )
        jobs.append(Job(
            company_name=name,
            ats="lever",
            external_id=j.get("id"),
            title=(j.get("text") or "").strip(),
            location=location,
            remote_type=_guess_remote(location, j.get("workplaceType"), cats.get("commitment")),
            description=description,
            url=j.get("hostedUrl") or j.get("applyUrl"),
            posted_at=posted_iso,
        ))
    return jobs


def fetch_ashby(name: str, token: str) -> list[Job]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    payload = _get(url).json()
    jobs = []
    for j in payload.get("jobs", []):
        location = j.get("location")
        description = j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml"))
        remote = "remote" if j.get("isRemote") else _guess_remote(location, j.get("employmentType"))
        jobs.append(Job(
            company_name=name,
            ats="ashby",
            external_id=j.get("id"),
            title=(j.get("title") or "").strip(),
            location=location,
            remote_type=remote,
            description=description,
            url=j.get("jobUrl") or j.get("applyUrl"),
            posted_at=j.get("publishedAt"),
        ))
    return jobs


def fetch_recruitee(name: str, token: str) -> list[Job]:
    url = f"https://{token}.recruitee.com/api/offers/"
    payload = _get(url).json()
    jobs = []
    for j in payload.get("offers", []):
        location = ", ".join(p for p in [j.get("city"), j.get("country")] if p) or j.get("location")
        description = _strip_html(j.get("description")) + " " + _strip_html(j.get("requirements"))
        jobs.append(Job(
            company_name=name,
            ats="recruitee",
            external_id=j.get("id"),
            title=(j.get("title") or "").strip(),
            location=location,
            remote_type="remote" if j.get("remote") else _guess_remote(location),
            description=description.strip(),
            url=j.get("careers_url"),
            posted_at=j.get("published_at"),
        ))
    return jobs


def fetch_workable(name: str, token: str) -> list[Job]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
    payload = _get(url).json()
    jobs = []
    for j in payload.get("jobs", []):
        location = ", ".join(p for p in [j.get("city"), j.get("country")] if p)
        description = " ".join(filter(None, [
            _strip_html(j.get("description")),
            _strip_html(j.get("requirements")),
        ])).strip()
        jobs.append(Job(
            company_name=name,
            ats="workable",
            external_id=j.get("shortcode") or j.get("code"),
            title=(j.get("title") or "").strip(),
            location=location or None,
            remote_type=("remote" if j.get("telecommuting")
                         else _guess_remote(location, j.get("employment_type"), description[:600])),
            description=description,
            url=j.get("url") or j.get("shortlink"),
            posted_at=j.get("published_on") or j.get("created_at"),
        ))
    return jobs


ADAPTERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "recruitee": fetch_recruitee,
    "workable": fetch_workable,
}


def fetch(company: dict) -> list[Job]:
    """company = {name, ats, token, tier}"""
    ats = company["ats"].lower()
    if ats not in ADAPTERS:
        raise ValueError(f"ATS غير مدعوم: {ats} (المدعوم: {', '.join(ADAPTERS)})")
    return ADAPTERS[ats](company["name"], company["token"])
