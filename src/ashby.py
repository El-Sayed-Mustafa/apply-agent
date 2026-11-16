"""
فورم التقديم على Ashby — قراية، ملء، وإرسال بعد موافقتك.

  · form(url)     تعريف الفورم من نفس الـAPI اللي الصفحة بتقرا منه.
                  None = الإعلان اتقفل (نص الوظايف القديمة بتبقى كده).
  · fill(page…)   بيملا كل حقل في الـcontainer بتاعه
                  (.ashby-application-form-field-entry[data-field-path=…])
  · preview()     متصفح مخفي، يملا ويصوّر — **من غير إرسال**
  · submit()      بيتنادى بس لما طلب الموافقة يبقى approved (ضغطة "📤 ابعت")

الفورم فيه reCAPTCHA. مفيش أي محاولة لتجاوزه: الإرسال بيحصل في متصفح
عادي ظاهر، ولو الصفحة رفضت أو طلبت تحقق، الوظيفة بتتحوّل "قدّم بنفسك"
والملف جاهز معاك.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests

GQL = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting"
QUERY = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
    id title
    applicationForm { id sections { title fieldEntries { ... on FormFieldEntry {
      id field isRequired descriptionHtml } } } }
  }
}"""
SUPPORTED = {"String", "Email", "Phone", "LongText", "Number", "Date", "Boolean",
             "ValueSelect", "MultiValueSelect", "Location", "File"}
PROFILE = Path(os.getenv("ASHBY_PROFILE_DIR",
                         Path.home() / ".apply-agent" / "ashby-profile"))
# أسئلة الاختيار (radio) بتيجي في div[data-field-path] من غير الكلاس ده
# (Cohere، 16 نوفمبر) — فالـselector على الـattribute بس
ENTRY = '[data-field-path="{}"]'
SUCCESS = re.compile(r"thank you|application (was )?(submitted|received)|"
                     r"successfully submitted|we.ve received your application", re.I)
BLOCKED = re.compile(r"recaptcha|captcha|spam|suspicious|verify you are human|"
                     r"couldn.t submit|could not submit|try again", re.I)


def parse_url(url: str | None) -> tuple[str, str] | None:
    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url or "")
    return (m.group(1), m.group(2)) if m else None


def application_url(url: str) -> str:
    org, jid = parse_url(url)
    return f"https://jobs.ashbyhq.com/{org}/{jid}/application"


def _field(entry: dict) -> dict | None:
    f = entry.get("field") or {}
    if not f.get("path") or f.get("isDeactivated"):
        return None
    return {"path": f["path"], "type": f.get("type"), "title": (f.get("title") or "").strip(),
            "required": bool(entry.get("isRequired")),
            "options": [v.get("label") for v in f.get("selectableValues") or []
                        if not v.get("isArchived")],
            "description": entry.get("descriptionHtml") or ""}


def form(url: str, http=requests) -> list[dict] | None:
    """الحقول، أو None لو الإعلان اتقفل/مش Ashby."""
    p = parse_url(url)
    if not p:
        return None
    r = http.post(GQL, json={"operationName": "ApiJobPosting", "query": QUERY,
                             "variables": {"organizationHostedJobsPageName": p[0],
                                           "jobPostingId": p[1]}}, timeout=30)
    r.raise_for_status()
    jp = (r.json().get("data") or {}).get("jobPosting")
    if not jp or not jp.get("applicationForm"):
        return None
    out = []
    for s in jp["applicationForm"].get("sections") or []:
        for e in s.get("fieldEntries") or []:
            f = _field(e)
            if f:
                out.append(f)
    return out


def unsupported(fields: list[dict]) -> list[dict]:
    """حقول إجبارية مش هنعرف نملاها: نوع غريب، أو ملف غير السيرة."""
    return [f for f in fields if f["required"] and (
        f["type"] not in SUPPORTED
        or (f["type"] == "File" and f["path"] != "_systemfield_resume"))]


# ── الملء ───────────────────────────────────────────────────────────────

def _fill_one(page, f: dict, value) -> None:
    box = page.locator(ENTRY.format(f["path"])).first
    typ = f["type"]
    if typ == "File":
        box.locator('input[type="file"]').first.set_input_files(str(value))
        page.wait_for_timeout(2500)                 # الرفع بياخد ثواني
    elif typ == "Boolean":
        box.locator(f'button[data-option="{"yes" if value else "no"}"]').first.click()
    elif typ == "Location":
        inp = box.locator('input[role="combobox"]').first
        inp.fill(str(value).split(",")[0])
        opt = page.locator('[role="option"]').filter(has_text=re.compile("Egypt", re.I))
        opt.first.wait_for(timeout=8000)
        opt.first.click()
    elif typ in ("ValueSelect", "MultiValueSelect"):
        values = value if isinstance(value, list) else [value]
        for v in values:
            radio = box.get_by_label(v.strip(), exact=True)
            if radio.count():
                # الضغط على الـlabel زي ما الإنسان بيعمل — الـinput نفسه
                # React بيتحكم فيه
                box.locator("label").filter(
                    has_text=re.compile(rf"^\s*{re.escape(v.strip())}\s*$")).first.click()
                if not radio.first.is_checked():
                    radio.first.check(force=True)
                continue
            combo = box.locator('input[role="combobox"]')
            if combo.count():
                combo.first.fill(v.strip())
                page.locator('[role="option"]').filter(has_text=v.strip()).first.click()
                continue
            box.get_by_text(v.strip(), exact=True).first.click()
    else:
        inp = box.locator("textarea, input:not([type=file]):not([type=checkbox])").first
        inp.fill(str(value))
        if typ == "Date":
            inp.press("Escape")


def fill(page, fields: list[dict], answers: dict) -> list[str]:
    """املا الفورم. رجّع الحقول اللي ماتملتش (فاضية لو كله تمام)."""
    problems = []
    for f in fields:
        a = answers.get(f["path"]) or {}
        v = a.get("value")
        if v in (None, "", []):
            if f["required"]:
                problems.append(f"{f['title'][:60]}: مفيش إجابة")
            continue
        try:
            _fill_one(page, f, v)
        except Exception as exc:
            problems.append(f"{f['title'][:60]}: {type(exc).__name__}")
    return problems


def _open(page, url: str) -> None:
    page.goto(application_url(url), wait_until="networkidle", timeout=60000)
    page.locator(".ashby-application-form-field-entry").first.wait_for(timeout=20000)


def preview(url: str, fields: list[dict], answers: dict, shot: Path) -> list[str]:
    """متصفح مخفي: املا وصوّر الصفحة كلها. **مفيش ضغط على Submit هنا.**"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1100, "height": 1000}, locale="en-US")
        try:
            _open(page, url)
            problems = fill(page, fields, answers)
            page.wait_for_timeout(1000)
            # الهيدر الثابت بيغطي جزء من الصورة الطويلة
            page.add_style_tag(content="[style*=sticky],header,nav{position:static !important}")
            page.screenshot(path=str(shot), full_page=True)
        finally:
            b.close()
    return problems


def submit(url: str, fields: list[dict], answers: dict, shot: Path,
           headless: bool = False) -> tuple[bool, str]:
    """
    املا من جديد واضغط Submit — في متصفح ظاهر بملف تعريف خاص بـAshby.
    رجّع (اتبعت؟، السبب). الصورة بعد الإرسال = الدليل.
    """
    from playwright.sync_api import sync_playwright
    PROFILE.mkdir(parents=True, exist_ok=True)
    # رد السيرفر على الإرسال نفسه — هو الحَكَم، مش نص الصفحة بس.
    # Cohere (16 نوفمبر): الصفحة فضلت زي ما هي 45 ثانية ومعرفناش إذا
    # الطلب وصل ولا لأ. من دلوقتي الرد بيتسجّل جنب الصورة.
    sent: list = []
    log = Path(shot).with_suffix(".json")

    def _watch(resp):
        u = resp.url.lower()
        if "graphql" in u and "submit" in u:
            sent.append(resp)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE), headless=headless, viewport={"width": 1100, "height": 1000},
            locale="en-US")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", _watch)
        try:
            _open(page, url)
            problems = fill(page, fields, answers)
            if problems:
                page.screenshot(path=str(shot), full_page=True)
                return False, "الملء ماكملش: " + "؛ ".join(problems[:3])
            page.get_by_role("button", name=re.compile(r"submit application", re.I)).click()
            deadline = time.time() + 45
            server = ""
            while time.time() < deadline:
                if sent and not server:
                    try:
                        server = f"{sent[-1].status} {sent[-1].text()[:3000]}"
                    except Exception as exc:
                        server = f"{sent[-1].status} (body: {type(exc).__name__})"
                    log.write_text(server, encoding="utf-8")
                body = page.locator("body").inner_text(timeout=5000)
                if SUCCESS.search(body):
                    page.screenshot(path=str(shot), full_page=True)
                    return True, "اتبعت"
                # كل الرسايل الظاهرة، مش أول واحدة بس — الأولى غالبًا
                # container مخفي لحقل ومفيهوش حاجة
                errs = page.locator('[class*="error"], [role="alert"]')
                for i in range(min(errs.count(), 20)):
                    e = errs.nth(i)
                    msg = e.inner_text().strip()[:200] if e.is_visible() else ""
                    if msg:
                        page.screenshot(path=str(shot), full_page=True)
                        return False, ("الصفحة طلبت تحقق: " if BLOCKED.search(msg)
                                       else "الصفحة رفضت: ") + msg
                if server and BLOCKED.search(server):
                    page.screenshot(path=str(shot), full_page=True)
                    return False, "السيرفر رفض: " + server[:200]
                page.wait_for_timeout(1500)
            page.screenshot(path=str(shot), full_page=True)
            if not sent:
                return False, ("زرار الإرسال ماطلعش أي طلب للسيرفر — "
                               "الطلب ماوصلش (غالبًا reCAPTCHA وقفه)")
            return False, ("السيرفر رد بس الصفحة ماأكدتش — ممكن يكون وصل، "
                           "بُص على إيميلك قبل ما تقدّم تاني. الرد: " + server[:150])
        finally:
            ctx.close()
