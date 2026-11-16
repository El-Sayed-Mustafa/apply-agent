"""
فورم التقديم على Lever — قراية بس. الملء من إضافة كروم، والإرسال ضغطتك.

Lever مالوش API للأسئلة؛ صفحة /apply نفسها HTML جاهز، وكل سؤال في
li.application-question بالعنوان والخانة. الـpath هو name الخانة
(name، email، urls[LinkedIn]، cards[<uuid>][field0]…) — الإضافة بتدوّر
عليه بالـname.

ملاحظات من صفحة حقيقية (Laminar، 17 نوفمبر):
  · الموقع: خانة نص بقايمة اقتراحات "Cairo, EGY" (مش Egypt)، والاختيار
    بيملا selectedLocation المخفي
  · الصفحة فيها hCaptcha — مش شغلنا؛ الإرسال ضغطتك في متصفحك
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

SKIP_NAMES = {"selectedLocation", "resumeStorageId", "h-captcha-response",
              "g-recaptcha-response", "accountId", "linkedInData", "origin", "referer",
              "timezone", "socialReferralKey", "socialSource", "source"}
SUPPORTED = {"String", "Email", "Phone", "LongText", "File", "ValueSelect",
             "MultiValueSelect", "Location", "Boolean"}


def parse_url(url: str | None, company: str | None = None) -> tuple[str, str, str] | None:
    """(eu أو ""، الشركة، رقم الإعلان)."""
    m = re.search(r"jobs\.(eu\.)?lever\.co/([^/?#]+)/([0-9a-f-]{36})", url or "")
    return ("eu" if m.group(1) else "", m.group(2), m.group(3)) if m else None


def application_url(url: str, company: str | None = None) -> str:
    eu, org, jid = parse_url(url)
    return f"https://jobs.{'eu.' if eu else ''}lever.co/{org}/{jid}/apply"


def _label(li) -> str:
    lab = li.select_one(".application-label .text") or li.select_one(".application-label")
    text = lab.get_text(" ", strip=True) if lab else ""
    return re.sub(r"\s*✱\s*$", "", text).strip()


def parse(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for li in soup.select("li.application-question"):
        els = [e for e in li.find_all(["input", "textarea", "select"])
               if e.get("name") and e.get("type") != "hidden" and e.get("name") not in SKIP_NAMES]
        if not els:
            continue
        name = els[0]["name"]
        wrap = els[0].find_parent("label")          # checkbox الموافقات: النص جنبها
        title = _label(li) or (wrap.get_text(" ", strip=True) if wrap else "") or name
        required = bool(li.select_one(".required")) or any(e.has_attr("required") for e in els)
        e0 = els[0]
        kind = e0.name
        typ, options = "String", []
        if kind == "select":
            typ = "ValueSelect"
            options = [o.get_text(strip=True) for o in e0.find_all("option") if o.get("value")]
        elif kind == "textarea":
            typ = "LongText"
        elif e0.get("type") == "file":
            typ = "File"
        elif e0.get("type") == "radio":
            typ = "ValueSelect"
            options = [e.get("value") for e in els if e.get("name") == name]
        elif e0.get("type") == "checkbox":
            same = [e for e in els if e.get("name") == name]
            if len(same) > 1:
                typ, options = "MultiValueSelect", [e.get("value") for e in same]
            else:
                typ = "Boolean"
        elif name == "email" or e0.get("type") == "email":
            typ = "Email"
        elif name == "phone":
            typ = "Phone"
        elif name == "location":
            typ = "Location"
        out.append({"path": name, "type": typ, "title": title, "required": required,
                    "options": options, "description": ""})
    return out


def form(url: str, company: str | None = None, http=requests) -> list[dict] | None:
    if not parse_url(url):
        return None
    r = http.get(application_url(url), timeout=30,
                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    fields = parse(r.text)
    return fields or None


def unsupported(fields: list[dict]) -> list[dict]:
    return [f for f in fields if f["required"] and f["type"] not in SUPPORTED]
