"""
تركيب السيرة — HTML + CSS، وبعدين PDF بـ Chromium.

ليه HTML مش DOCX:
  · تحكم كامل في التنسيق (grid، هوامش بالمليمتر، تحكم في الصفحة)
  · نفس الشكل بالظبط على أي جهاز — الخط متضمّن جوّه الملف
  · الـ PDF هو اللي أنظمة التوظيف عايزاه أصلاً
  · نقدر نضبط الكثافة عشان تتلم في صفحة واحدة

مفيش أي توليد هنا. كل كلمة جاية من cv.yaml أو من معرّفات اختارها
الموديل واتفحصت قبل ما توصل. الفرق الوحيد إن الأرقام بتتعلّم بخط
أعرض — تمييز بصري، مش كلام جديد.
"""
from __future__ import annotations

import base64
import html
import re
import tempfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "cv_template.html"
FONTS = ROOT / "assets" / "fonts" / "TTF"

SEP = '<span class="sep">·</span>'


# ── الخطوط ──────────────────────────────────────────────────────────────

def _font(name: str) -> str:
    """الخط بيتضمّن في الملف — عشان الـ PDF يطلع واحد في أي مكان."""
    p = FONTS / name
    return base64.b64encode(p.read_bytes()).decode() if p.exists() else ""


def _template() -> str:
    t = TEMPLATE.read_text(encoding="utf-8")
    for key, f in (("__REG__", "SourceSans3-Regular.ttf"),
                   ("__SEMI__", "SourceSans3-Semibold.ttf"),
                   ("__BOLD__", "SourceSans3-Bold.ttf"),
                   ("__ITAL__", "SourceSans3-It.ttf")):
        t = t.replace(key, _font(f))
    return t


# ── أدوات ───────────────────────────────────────────────────────────────

def esc(x) -> str:
    return html.escape(str(x or ""), quote=True)


def emphasise(text: str) -> str:
    """
    الأرقام بتتعلّم بخط أعرض.

    تمييز بصري بس — النص زي ما هو حرف بحرف. القارئ بيمسح السيرة في
    ثواني، والأرقام هي اللي بتوقّف عينه.
    """
    # الوحدة بتتضم للرقم بس لما تكون ملزوقة بيه (0.84s · 80.7% · 1.1M).
    # المسافة بعد الرقم بتفضل بره التعليم — "5 seconds" مش "5 s".
    return re.sub(
        r"(\b\d[\d,]*(?:\.\d+)?\+?(?:\s?(?:%|(?:GB|MB|TB|[skMK])\b))?)",
        r"<b>\1</b>", esc(text))


def link(text, url: str | None, cls: str = "") -> str:
    t = esc(text)
    if not url:
        return t
    c = f' class="{cls}"' if cls else ""
    return f'<a href="{esc(url)}"{c}>{t}</a>'


def _bullets(ids: list[str], bullets: dict) -> str:
    items = "".join(f"<li>{emphasise(bullets[b]['text'])}</li>"
                    for b in ids if b in bullets)
    return f"<ul>{items}</ul>" if items else ""


# ── الأقسام ─────────────────────────────────────────────────────────────

def _header_meta(contact: dict, profile: dict) -> str:
    bits = []
    if contact.get("email"):
        bits.append(link(contact["email"], f"mailto:{contact['email']}"))
    if contact.get("phone"):
        bits.append(link(contact["phone"], f"tel:{contact['phone']}"))
    if contact.get("location"):
        bits.append(esc(contact["location"]))
    if profile.get("notes"):
        bits.append(esc(profile["notes"]))
    for label, url in (contact.get("links") or {}).items():
        bits.append(link(label, url))
    return SEP.join(bits)


def _experience(cv: dict, picked: dict, order: dict, bullets: dict) -> str:
    rows = [e for e in (cv.get("experience") or []) if picked.get(e.get("id"))]
    if not rows:
        return ""
    rows.sort(key=lambda e: min(order[b] for b in picked[e["id"]]))
    out = []
    for e in rows:
        when = "  |  ".join(filter(None, [e.get("period"), e.get("mode")]))
        out.append(
            '<div class="entry">'
            f'<div><span class="what">{esc(e.get("role"))}</span>'
            f'<span class="where">, {esc(e.get("company"))}</span></div>'
            f'<div class="when">{esc(when)}</div></div>'
            + _bullets(picked[e["id"]], bullets))
    return "<section><h2>Experience</h2>" + "".join(out) + "</section>"


def _projects(cv: dict, picked: dict, order: dict, bullets: dict) -> str:
    rows = [p for p in (cv.get("projects") or []) if picked.get(p.get("id"))]
    if not rows:
        return ""
    rows.sort(key=lambda p: min(order[b] for b in picked[p["id"]]))
    out = []
    for p in rows:
        out.append(
            '<div class="entry">'
            f'<div class="what">{link(p.get("name"), p.get("url"))}</div>'
            "</div>"
            + (f'<div class="stack">{esc(p.get("stack"))}</div>'
               if p.get("stack") else "")
            + _bullets(picked[p["id"]], bullets))
    return "<section><h2>Projects</h2>" + "".join(out) + "</section>"


def _skills(cv: dict) -> str:
    """
    عمود واحد، واللابل جوّه نفس تدفق النص.

    مرّينا على شكلين وقعوا في نفس الفخ:
      · grid من عمودين  → الاستخراج بيلحم اليمين بالشمال سطر بسطر
      · لابل في عمود جنبه → اللابل نفسه بيتلف ("Automation &" /
        "Scraping") فيتلحم بالقيم

    الحل: كل مجموعة فقرة واحدة، اللابل أول الكلام. الاستخراج بيطلع
    سطر نضيف مهما كان الطول.
    """
    skills = {k: v for k, v in (cv.get("skills") or {}).items() if v}
    if not skills:
        return ""
    rows = "".join(
        f'<div class="srow"><b class="slabel">{esc(k)}</b>&nbsp;&nbsp;'
        f'{esc(", ".join(str(x) for x in v))}</div>'
        for k, v in skills.items())
    return f'<section><h2>Skills</h2><div class="skills">{rows}</div></section>'


def _education(cv: dict) -> str:
    rows = []
    for e in (cv.get("education") or []):
        rows.append(
            '<div class="entry">'
            f'<div><span class="what">{esc(e.get("degree"))}</span>'
            f'<span class="where">, {esc(e.get("school"))}</span></div>'
            f'<div class="when">{esc(e.get("period"))}</div></div>')
        tail = " · ".join(filter(None, [e.get("department"),
                                        e.get("project_short")]))
        if tail:
            rows.append(f'<div class="inline">{emphasise(tail)}</div>')
    return ("<section><h2>Education</h2>" + "".join(rows) + "</section>"
            if rows else "")


def _certificates(cv: dict) -> str:
    """
    كلهم في سطر واحد مفصولين بنقطة.

    قايمة نقط بتاخد 4 أسطر مقابل صفر معلومة زيادة — والمساحة دي
    الإنجازات أولى بيها.
    """
    items = []
    for c in (cv.get("certificates") or []):
        if isinstance(c, str):
            items.append(esc(c))
            continue
        items.append(link(c.get("name"), c.get("url"))
                     + (f'<span class="by"> — {esc(c["issuer"])}</span>'
                        if c.get("issuer") else ""))
    if not items:
        return ""
    body = SEP.join(items)
    return f'<section><h2>Certificates</h2><div class="inline">{body}</div></section>'


def _languages(cv: dict) -> str:
    langs = (cv.get("profile") or {}).get("languages") or []
    if not langs:
        return ""
    body = SEP.join(esc(x) for x in langs)
    return f'<section><h2>Languages</h2><div class="inline">{body}</div></section>'


# ── البناء ──────────────────────────────────────────────────────────────

def build_html(cv: dict, bullets: dict, chosen: list[str],
               headline: str = "", summary: str = "") -> str:
    contact = cv.get("contact") or {}
    profile = cv.get("profile") or {}

    order = {b: i for i, b in enumerate(chosen)}
    picked: dict[str, list[str]] = {}
    for b in chosen:
        meta = bullets.get(b)
        if meta:
            picked.setdefault(meta.get("parent_id", ""), []).append(b)

    body = ""
    text = summary or profile.get("summary_short") or profile.get("summary", "")
    if text:
        clean = re.sub(r"\s+", " ", text).strip()
        body += ('<section><h2>Summary</h2>'
                 f'<div class="summary">{emphasise(clean)}</div></section>')
    body += _experience(cv, picked, order, bullets)
    body += _projects(cv, picked, order, bullets)
    body += _skills(cv)
    body += _education(cv)
    body += _certificates(cv)
    body += _languages(cv)

    return (_template()
            .replace("__NAME__", esc(contact.get("name")))
            .replace("__ROLE__", esc(headline or profile.get("title")))
            .replace("__META__", _header_meta(contact, profile))
            .replace("__BODY__", body))


PDF_OPTS = dict(format="A4", print_background=True,
                margin={"top": "9mm", "bottom": "9mm",
                        "left": "10mm", "right": "10mm"})


def _page_count(pdf: bytes) -> int:
    """عدّ الصفحات من غير مكتبة — /Type /Page في بنية الملف."""
    return max(pdf.count(b"/Type /Page\n") + pdf.count(b"/Type/Page\n"), 1)


def build(cv: dict, bullets: dict, chosen: list[str],
          headline: str = "", summary: str = "") -> BytesIO:
    """
    رجّع PDF من صفحة واحدة، مليانة.

    المستند بيضبّط نفسه: بيبدأ بكل النقط المختارة، ولو طلع صفحتين
    بيشيل الأضعف (آخر واحدة في ترتيب الأهمية) ويعيد. بيقف أول ما
    يتلم في صفحة.

    كده الصفحة بتطلع مليانة دايمًا مهما كان طول النقط — من غير ما
    نظبّط عدد ثابت بيبقى قليل مرة وكتير مرة.
    """
    from playwright.sync_api import sync_playwright

    ids = list(chosen)
    pdf = b""

    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "cv.html"
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            try:
                while ids:
                    f.write_text(build_html(cv, bullets, ids, headline, summary),
                                 encoding="utf-8")
                    page.goto(f.as_uri())
                    page.emulate_media(media="print")
                    pdf = page.pdf(**PDF_OPTS)
                    if _page_count(pdf) <= 1 or len(ids) <= 4:
                        break
                    ids.pop()          # شيل الأضعف وحاول تاني
            finally:
                browser.close()

    return BytesIO(pdf)


def filename(job: dict) -> str:
    parts = [job.get("company_name") or "", job.get("title") or ""]
    slug = re.sub(r"[^\w\s-]", "", " ".join(parts))
    slug = re.sub(r"\s+", "-", slug.strip())[:60].strip("-")
    return f"Elsayed-Mustafa-{slug or 'CV'}.pdf"
