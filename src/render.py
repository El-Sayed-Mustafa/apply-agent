"""
تركيب المستند — نسخة طبق الأصل من شكل FlowCV.

مفيش أي توليد هنا. كل كلمة جاية من cv.yaml أو من معرّفات اختارها
الموديل واتفحصت قبل ما توصل.

مطابق للـ PDF الأصلي في:
    الخط     Source Sans (نفس عيلة SourceSansPro اللي في الـ PDF)
    الصفحة   A4
    الترتيب  ترويسة · Summary · Experience · Education · Skills
             · Projects · Certificates · Languages
    اللينكات مخفية تحت النص — الإيميل والتليفون والحسابات،
             وكل مشروع تحت اسمه، وكل شهادة تحت اسمها

python-docx مفيهاش دالة لعمل لينك، فالـ XML متكتوب بالإيد تحت.
"""
from __future__ import annotations

import re
from io import BytesIO

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Inches, Pt, RGBColor

FONT = "Source Sans 3"          # نفس عيلة SourceSansPro في الـ PDF الأصلي
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x5A, 0x5A, 0x5A)
LINK = RGBColor(0x2B, 0x2B, 0x2B)   # FlowCV بيخلي اللينكات بلون النص
RULE = "C8C8C8"

MARGIN = 0.5
CONTENT_W = 8.27 - 2 * MARGIN       # A4 ناقص الهوامش


# ── XML بالإيد ──────────────────────────────────────────────────────────

def _hyperlink(par, text: str, url: str, size=8.5,
               color=LINK, bold=False, underline=False):
    """
    لينك حقيقي: النص بيتعرض والرابط مخفي تحته.

    python-basedocx مفيهاش API للينكات — لازم نضيف علاقة في ملف
    العلاقات ونلف الـ run في عنصر w:hyperlink.
    """
    rid = par.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)

    run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")

    fonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        fonts.set(qn(attr), FONT)
    rPr.append(fonts)

    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(size * 2)))     # نصف نقطة
    rPr.append(sz)

    col = OxmlElement("w:color")
    col.set(qn("w:val"), str(color))     # RGBColor بيطبع hex من غير #
    rPr.append(col)

    if bold:
        rPr.append(OxmlElement("w:b"))
    if underline:
        u = OxmlElement("w:u")
        u.set(qn("w:val"), "single")
        rPr.append(u)

    run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    par._p.append(link)


def _bottom_border(par) -> None:
    """الخط الرفيع تحت عنوان القسم — علامة FlowCV المميزة."""
    pPr = par._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), RULE)
    bdr.append(bottom)
    pPr.append(bdr)


def _no_borders(table) -> None:
    bdr = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "none")
        bdr.append(e)
    table._tbl.tblPr.append(bdr)


# ── أدوات ───────────────────────────────────────────────────────────────

def _p(container, before=0, after=2):
    par = container.add_paragraph()
    f = par.paragraph_format
    f.space_before = Pt(before)
    f.space_after = Pt(after)
    return par


def _run(par, text, size=10, bold=False, color=INK, italic=False):
    r = par.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.color.rgb = color
    return r


def _section(doc, title: str) -> None:
    par = _p(doc, before=8, after=3)
    _run(par, title, size=12, bold=True)
    _bottom_border(par)


def _bullet(container, text: str, size=9.5) -> None:
    par = container.add_paragraph(style="List Bullet")
    par.paragraph_format.space_after = Pt(1)
    par.paragraph_format.left_indent = Inches(0.18)
    _run(par, text, size=size)


def _entry(doc, title: str, rest: str, right: str, url: str | None = None):
    """سطر عنوان مع التاريخ على اليمين. لو فيه url، العنوان بيبقى لينك."""
    par = _p(doc, before=5, after=1)
    par.paragraph_format.tab_stops.add_tab_stop(
        Inches(CONTENT_W), WD_TAB_ALIGNMENT.RIGHT)
    if url:
        _hyperlink(par, title, url, size=10.5, bold=True, color=INK)
    else:
        _run(par, title, size=10.5, bold=True)
    if rest:
        _run(par, rest, size=10.5)
    if right:
        _run(par, "\t" + right, size=9, color=MUTED)
    return par


# ── المستند ─────────────────────────────────────────────────────────────

def build(cv: dict, bullets: dict, chosen: list[str],
          headline: str = "", summary: str = "") -> BytesIO:
    doc = Document()

    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    st.paragraph_format.space_after = Pt(2)
    st.paragraph_format.line_spacing = 1.05

    for s in doc.sections:
        s.page_width, s.page_height = Inches(8.27), Inches(11.69)   # A4
        s.top_margin = s.bottom_margin = Inches(0.45)
        s.left_margin = s.right_margin = Inches(MARGIN)

    contact = cv.get("contact") or {}
    profile = cv.get("profile") or {}

    # ── الترويسة ──
    h = _p(doc, after=0)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(h, contact.get("name", ""), size=19, bold=True)

    t = _p(doc, after=3)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(t, headline or profile.get("title", ""), size=11.5, color=MUTED)

    # سطر الاتصال — الإيميل والتليفون لينكات مخفية
    c = _p(doc, after=1)
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    first = True
    if contact.get("email"):
        _hyperlink(c, contact["email"], f"mailto:{contact['email']}", color=MUTED)
        first = False
    if contact.get("phone"):
        if not first:
            _run(c, "  ·  ", size=8.5, color=MUTED)
        _hyperlink(c, contact["phone"], f"tel:{contact['phone']}", color=MUTED)
        first = False
    for extra in (contact.get("location"), profile.get("notes")):
        if extra:
            if not first:
                _run(c, "  ·  ", size=8.5, color=MUTED)
            _run(c, extra, size=8.5, color=MUTED)
            first = False

    # سطر الحسابات — الاسم ظاهر والرابط مخفي
    links = contact.get("links") or {}
    if links:
        l = _p(doc, after=2)
        l.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for i, (label, url) in enumerate(links.items()):
            if i:
                _run(l, "  ·  ", size=8.5, color=MUTED)
            _hyperlink(l, label, url, color=MUTED, underline=True)

    # ── Summary ──
    text = summary or profile.get("summary", "")
    if text:
        _section(doc, "Summary")
        _run(_p(doc, after=2), re.sub(r"\s+", " ", text).strip(), size=9.5)

    # ── ترتيب النقط حسب أهميتها للوظيفة ──
    order = {bid: i for i, bid in enumerate(chosen)}
    picked: dict[str, list[str]] = {}
    for bid in chosen:
        b = bullets.get(bid)
        if b:
            picked.setdefault(b.get("parent_id", ""), []).append(bid)

    # ── Experience ──
    exp = [e for e in (cv.get("experience") or []) if picked.get(e.get("id"))]
    exp.sort(key=lambda e: min(order[b] for b in picked[e["id"]]))
    if exp:
        _section(doc, "Experience")
        for e in exp:
            _entry(doc, e.get("role", ""),
                   f", {e['company']}" if e.get("company") else "",
                   "  |  ".join(filter(None, [e.get("period"), e.get("mode")])))
            for bid in picked[e["id"]]:
                _bullet(doc, bullets[bid]["text"])

    # ── Education ──
    for e in (cv.get("education") or []):
        _section(doc, "Education")
        _entry(doc, e.get("degree", ""),
               f", {e['school']}" if e.get("school") else "", e.get("period", ""))
        if e.get("department"):
            _run(_p(doc, after=1), e["department"], size=9, color=MUTED)
        if e.get("project"):
            _run(_p(doc, after=2), e["project"], size=9.5)
        break

    # ── Skills — عمودين، زي FlowCV ──
    skills = {k: v for k, v in (cv.get("skills") or {}).items() if v}
    if skills:
        _section(doc, "Skills")
        names = list(skills)
        rows = (len(names) + 1) // 2
        table = doc.add_table(rows=rows, cols=2)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.autofit = False
        _no_borders(table)
        for i, name in enumerate(names):
            cell = table.cell(i % rows, i // rows)
            cell.width = Inches(CONTENT_W / 2)
            head = cell.paragraphs[0]
            head.paragraph_format.space_after = Pt(0)
            _run(head, name.replace("_", " ").title(), size=9.5, bold=True)
            _bullet(cell, ", ".join(str(x) for x in skills[name]), size=9)

    # ── Projects — اسم المشروع لينك للريبو ──
    proj = [p for p in (cv.get("projects") or []) if picked.get(p.get("id"))]
    proj.sort(key=lambda p: min(order[b] for b in picked[p["id"]]))
    if proj:
        _section(doc, "Projects")
        for pr in proj:
            _entry(doc, pr.get("name", ""), "", "", url=pr.get("url"))
            if pr.get("stack"):
                _run(_p(doc, after=1), pr["stack"], size=8.5,
                     color=MUTED, italic=True)
            for bid in picked[pr["id"]]:
                _bullet(doc, bullets[bid]["text"])

    # ── Certificates — كل واحدة لينك للتحقق ──
    certs = cv.get("certificates") or []
    if certs:
        _section(doc, "Certificates")
        for c in certs:
            if isinstance(c, str):
                _bullet(doc, c)
                continue
            par = doc.add_paragraph(style="List Bullet")
            par.paragraph_format.space_after = Pt(1)
            par.paragraph_format.left_indent = Inches(0.18)
            if c.get("url"):
                _hyperlink(par, c.get("name", ""), c["url"], size=9.5,
                           color=INK, underline=True)
            else:
                _run(par, c.get("name", ""), size=9.5)
            if c.get("issuer"):
                _run(par, f"  —  {c['issuer']}", size=9.5, color=MUTED)

    # ── Languages ──
    langs = profile.get("languages") or []
    if langs:
        _section(doc, "Languages")
        _run(_p(doc, after=2), "   ·   ".join(str(x) for x in langs), size=9.5)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def filename(job: dict) -> str:
    """اسم ملف نضيف — الشركة والوظيفة، عشان تعرفه من التليجرام."""
    parts = [job.get("company_name") or "", job.get("title") or ""]
    slug = re.sub(r"[^\w\s-]", "", " ".join(parts))
    slug = re.sub(r"\s+", "-", slug.strip())[:60].strip("-")
    return f"Elsayed-Mustafa-{slug or 'CV'}.docx"
