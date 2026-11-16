"""
فورم التقديم على Greenhouse — قراية بس. الملء من إضافة كروم، والإرسال ضغطتك.

  · form(url, company)   الأسئلة من الـAPI العام نفسه اللي الصفحة بتقرا منه:
                         boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>?questions=true
                         (بيخدم بوردات eu كمان). None = الإعلان اتقفل.
  · application_url()    صفحة الـembed: بتشتغل لكل الشركات، حتى اللي بتحوّل
                         البورد بتاعها لموقعها (FanDuel → fanduel.careers).

الـpath هنا هو اسم الحقل في الـAPI، وهو نفسه الـid في صفحة الفورم
(first_name، question_18291910008، resume…) — الإضافة بتدوّر عليه بالـid.

اللينكات عندنا شكلين (17 نوفمبر):
  job-boards(.eu).greenhouse.io/<board>/jobs/<id>  و  boards.greenhouse.io/…
  موقع الشركة ?gh_jid=<id> — البورد هو company_name في جدول jobs
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import requests

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}"
EMBED = "https://job-boards.greenhouse.io/embed/job_app?for={board}&token={jid}"
TYPES = {"input_text": "String", "textarea": "LongText", "input_file": "File",
         "multi_value_single_select": "ValueSelect",
         "multi_value_multi_select": "MultiValueSelect"}
# بدايل الملف كنص — لو الملف اترفع مش محتاجينها
TEXT_ALTERNATIVES = {"resume_text", "cover_letter_text"}


def parse_url(url: str | None, company: str | None = None) -> tuple[str, str] | None:
    """(البورد، رقم الإعلان)."""
    url = url or ""
    m = re.search(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?!embed/)([^/?#]+)/jobs/(\d+)", url)
    if m:
        return m.group(1), m.group(2)
    q = parse_qs(urlparse(url).query)
    if "greenhouse.io/embed/job_app" in url and q.get("for") and q.get("token"):
        return q["for"][0], q["token"][0]
    if q.get("gh_jid") and company:
        board = re.sub(r"[^a-z0-9_-]", "", company.lower())
        return (board, q["gh_jid"][0]) if board else None
    return None


def application_url(url: str, company: str | None = None) -> str:
    board, jid = parse_url(url, company)
    return EMBED.format(board=board, jid=jid)


def _fields(q: dict) -> list[dict]:
    out = []
    for f in q.get("fields") or []:
        name, gtype = f.get("name"), f.get("type")
        if not name or gtype == "input_hidden" or name in TEXT_ALTERNATIVES:
            continue
        typ = TYPES.get(gtype, gtype)
        if name == "email":
            typ = "Email"
        elif name == "phone":
            typ = "Phone"
        out.append({"path": name, "type": typ,
                    "title": re.sub(r"\s+", " ", q.get("label") or name).strip(),
                    "required": bool(q.get("required")),
                    "options": [v.get("label") for v in f.get("values") or []],
                    "description": q.get("description") or ""})
    return out


def form(url: str, company: str | None = None, http=requests) -> list[dict] | None:
    p = parse_url(url, company)
    if not p:
        return None
    r = http.get(API.format(board=p[0], jid=p[1]), params={"questions": "true"}, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json()
    out = []
    for q in (d.get("questions") or []) + (d.get("location_questions") or []):
        out += _fields(q)
    for block in d.get("compliance") or []:          # EEOC — اختيارية، القاعدة بترفض بأدب
        for q in block.get("questions") or []:
            out += _fields(q)
    return out


SUPPORTED = {"String", "Email", "Phone", "LongText", "File", "ValueSelect", "MultiValueSelect"}


def unsupported(fields: list[dict]) -> list[dict]:
    return [f for f in fields if f["required"] and f["type"] not in SUPPORTED]
