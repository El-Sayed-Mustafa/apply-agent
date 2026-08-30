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

# مسافات حقيقية حوالين الفاصل. الـ padding بتاع الـ CSS بيختفي وقت
# استخراج النص، فالعناصر بتلتزق ببعض — "DeepLearning.AI·Advanced SQL".
# النقطة بمسافاتها بتفضل موجودة في النص المستخرج.
SEP = '<span class="sep">&nbsp;·&nbsp;</span>'

# أيقونات SVG — مرسومة مش حروف، فمبتظهرش خالص في استخراج النص.
# لو كانت رموز نصية (✉ 📞) كانت هتتلزق بالإيميل عند الـ ATS.
#
# stroke = خطوط مرسومة · fill = أشكال مصمتة (العلامات التجارية)
_STROKE = {
    "mail":  '<rect x="1.6" y="3.4" width="12.8" height="9.2" rx="1.4"/>'
             '<path d="M2 4.4l6 4.2 6-4.2"/>',
    "phone": '<path d="M3.6 2h2.6l1.3 3.2-1.7.9a8.5 8.5 0 004.1 4.1l.9-1.7'
             'L14 9.8v2.6a1.6 1.6 0 01-1.7 1.6A11.8 11.8 0 012 3.7'
             'A1.6 1.6 0 013.6 2z"/>',
    "pin":   '<path d="M8 14.2s4.8-4.3 4.8-7.7A4.8 4.8 0 003.2 6.5'
             'C3.2 9.9 8 14.2 8 14.2z"/><circle cx="8" cy="6.4" r="1.7"/>',
    "link":  '<path d="M6.9 9.1a2.9 2.9 0 004.2 0l1.9-1.9a2.9 2.9 0 00-4.2-4.2'
             'l-1 1"/><path d="M9.1 6.9a2.9 2.9 0 00-4.2 0L3 8.8'
             'a2.9 2.9 0 004.2 4.2l1-1"/>',
}

_FILL = {
    "shield": 'M8 .9L2.2 3v4.4c0 3.6 2.5 6.9 5.8 7.7 3.3-.8 5.8-4.1 5.8-7.7V3z'
              'm-.7 10.4L4.9 8.9l1.1-1.1 1.3 1.3 3.4-3.4 1.1 1.1z',
    "linkedin": 'M13.6 0H2.4A2.4 2.4 0 000 2.4v11.2A2.4 2.4 0 002.4 16h11.2'
                'a2.4 2.4 0 002.4-2.4V2.4A2.4 2.4 0 0013.6 0zM5 13.4H2.7V6.1H5z'
                'M3.8 5.1a1.34 1.34 0 110-2.7 1.34 1.34 0 010 2.7zm9.6 8.3h-2.3'
                'V9.8c0-.87-.02-2-1.22-2-1.22 0-1.4.95-1.4 1.94v3.66H6.2V6.1h2.2'
                'v1h.03c.31-.58 1.06-1.2 2.18-1.2 2.33 0 2.76 1.53 2.76 3.53z',
    "github": 'M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55'
              '-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48'
              '-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72'
              ' 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64'
              '-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21'
              ' 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82'
              ' 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87'
              ' 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21'
              '.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z',
    "upwork": 'M12.1 5.1c-1.6 0-2.8 1.05-3.3 2.7-.6-.95-1.1-2.1-1.45-3.05H5.5'
              'v3.8c0 .95-.65 1.6-1.5 1.6s-1.5-.65-1.5-1.6V4.75H0v3.8'
              'c0 1.15.45 2.2 1.2 2.95.75.75 1.8 1.15 3.05 1.15 2.4 0 4.1-1.8'
              ' 4.1-4.2v-.55c.3.65.65 1.3 1.05 1.9l-.95 4.5h1.9l.65-3.15'
              'c.55.35 1.15.55 1.8.55 2.1 0 3.7-1.7 3.7-3.9s-1.7-3.8-3.7-3.8z'
              'm0 5.6c-.55 0-1.05-.2-1.5-.55l.1-.65c.25-.95.75-1.8 1.5-1.8'
              '.75 0 1.4.65 1.4 1.5s-.65 1.5-1.5 1.5z',
}

# اسم الرابط → أيقونته. اللي مش في القايمة بياخد أيقونة رابط عامة.
LINK_ICONS = {"linkedin": "linkedin", "github": "github", "upwork": "upwork"}


def icon(name: str) -> str:
    if name in _FILL:
        return (f'<svg class="ic fill" viewBox="0 0 16 16" aria-hidden="true">'
                f'<path d="{_FILL[name]}"/></svg>')
    if name in _STROKE:
        return (f'<svg class="ic" viewBox="0 0 16 16" aria-hidden="true">'
                f'{_STROKE[name]}</svg>')
    return ""


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
    """
    النقط مرتّبة بـ rank من cv.yaml، مش بترتيب الموديل.

    فصل في المسؤولية: الموديل بيقرر **أنهي** نقط تخص الوظيفة، وإنت
    بتقرر **بأي ترتيب** تظهر. القارئ بيمسح شركة من فوق لتحت وبيقف
    عند أول رقم — فالترتيب قرار صاحب السيرة مش قرار الموديل.
    """
    chosen = [b for b in ids if b in bullets]
    chosen.sort(key=lambda b: bullets[b].get("rank", 99))
    items = "".join(f"<li>{emphasise(bullets[b]['text'])}</li>" for b in chosen)
    return f"<ul>{items}</ul>" if items else ""


# ── الأقسام ─────────────────────────────────────────────────────────────

def _header_meta(contact: dict, profile: dict) -> str:
    bits = []
    if contact.get("email"):
        bits.append(icon("mail")
                    + link(contact["email"], f"mailto:{contact['email']}"))
    if contact.get("phone"):
        bits.append(icon("phone")
                    + link(contact["phone"], f"tel:{contact['phone']}"))
    if contact.get("location"):
        bits.append(icon("pin") + esc(contact["location"]))
    if profile.get("notes") and profile.get("show_notes"):
        bits.append(icon("shield") + esc(profile["notes"]))
    for label, url in (contact.get("links") or {}).items():
        bits.append(icon(LINK_ICONS.get(label.lower(), "link"))
                    + link(label, url))
    return SEP.join(bits)


def _experience(cv: dict, picked: dict, order: dict, bullets: dict) -> str:
    rows = [e for e in (cv.get("experience") or []) if picked.get(e.get("id"))]
    if not rows:
        return ""
    rows.sort(key=lambda e: min(order[b] for b in picked[e["id"]]))
    out = []
    for e in rows:
        when = "  |  ".join(filter(None, [e.get("period"), e.get("mode")]))
        # article واحد فيه العنوان والنقط — مايتفصلوش لا بصريًا
        # ولا في ترتيب النص جوّه الملف
        out.append(
            '<article class="block"><div class="head">'
            f'<div><span class="what">{esc(e.get("role"))}</span>'
            f'<span class="where">, {esc(e.get("company"))}</span></div>'
            f'<div class="when">{esc(when)}</div></div>'
            + _bullets(picked[e["id"]], bullets) + "</article>")
    return "<section><h2>Experience</h2>" + "".join(out) + "</section>"


def _projects(cv: dict, picked: dict, order: dict, bullets: dict) -> str:
    rows = [p for p in (cv.get("projects") or []) if picked.get(p.get("id"))]
    if not rows:
        return ""
    rows.sort(key=lambda p: min(order[b] for b in picked[p["id"]]))
    out = []
    for p in rows:
        out.append(
            '<article class="block"><div class="head">'
            f'<div class="what">{link(p.get("name"), p.get("url"))}</div>'
            "</div>"
            + (f'<div class="stack">{esc(p.get("stack"))}</div>'
               if p.get("stack") else "")
            + _bullets(picked[p["id"]], bullets) + "</article>")
    return "<section><h2>Selected Projects</h2>" + "".join(out) + "</section>"


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
            '<article class="block"><div class="head">'
            f'<div><span class="what">{esc(e.get("degree"))}</span>'
            f'<span class="where">, {esc(e.get("school"))}</span></div>'
            f'<div class="when">{esc(e.get("period"))}</div></div></article>')
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
            # العنوان من cv.yaml دايمًا. الموديل كان بيغيّره كل مرة
            # ("Product AI Engineer") وده بيضيّق تصنيفك عند الـ recruiter
            # من غير داعي — والعنوان الثابت بيبني هوية واحدة.
            .replace("__ROLE__", esc(profile.get("title")))
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
