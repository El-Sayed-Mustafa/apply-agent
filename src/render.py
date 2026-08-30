"""
تركيب المستند.

مفيش أي توليد هنا. كل كلمة في الملف الناتج جاية من cv.yaml أو من
معرّفات اختارها الموديل — والمعرّفات اتفحصت قبل ما توصل هنا.

الشكل مقصود إنه ممل: مفيش جداول ولا أعمدة ولا مربعات نصية. أنظمة
الـ ATS بتقرا الملف كنص متسلسل، وأي تنسيق ذكي بيبوّظ القراءة —
وساعتها سيرتك بتتقيّم على نص مشوّه من غير ما تعرف.
"""
from __future__ import annotations

import re
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

ACCENT = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x55, 0x55, 0x55)


def _style(doc: Document) -> None:
    n = doc.styles["Normal"]
    n.font.name = "Calibri"
    n.font.size = Pt(10.5)
    p = n.paragraph_format
    p.space_after = Pt(4)
    p.line_spacing = 1.06


def _heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(11)
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(text.upper())
    r.bold = True
    r.font.size = Pt(9.5)
    r.font.color.rgb = MUTED


def _bullet(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    p.add_run(text)


def build(cv_ctx: dict, bullets: dict, chosen: list[str],
          headline: str = "") -> BytesIO:
    """
    ابنِ المستند.

    chosen = معرّفات، بالترتيب اللي الموديل شافه مناسب للوظيفة دي.
    الترتيب هو نص التظبيط: نفس النقط، أولوية مختلفة.
    """
    doc = Document()
    _style(doc)

    for s in doc.sections:
        s.top_margin = s.bottom_margin = Pt(38)
        s.left_margin = s.right_margin = Pt(46)

    profile = cv_ctx.get("profile") or {}

    # ── الترويسة ──
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    h.paragraph_format.space_after = Pt(1)
    r = h.add_run(profile.get("name") or "Elsayed Mustafa")
    r.bold = True
    r.font.size = Pt(17)
    r.font.color.rgb = ACCENT

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.paragraph_format.space_after = Pt(2)
    r = sub.add_run(headline or profile.get("title") or "")
    r.font.size = Pt(11)
    r.font.color.rgb = MUTED

    meta = " · ".join(filter(None, [
        profile.get("location"),
        f"{profile.get('years_experience')} yrs experience"
        if profile.get("years_experience") else None,
        ", ".join(profile.get("open_to") or []) or None,
    ]))
    if meta:
        m = doc.add_paragraph()
        m.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = m.add_run(meta)
        r.font.size = Pt(9)
        r.font.color.rgb = MUTED

    # ── الخبرة، مجمّعة بمكانها الأصلي ──
    # النقط اتاختارت مرتّبة بالأهمية، بس المستند لازم يفضل مقروء —
    # فبنجمّعها تحت الدور بتاعها، مع الحفاظ على ترتيب الأهمية جوّه كل دور.
    order = {bid: i for i, bid in enumerate(chosen)}
    groups: dict[str, list[str]] = {}
    for bid in chosen:
        b = bullets.get(bid)
        if b:
            groups.setdefault(b.get("parent") or "", []).append(bid)

    exp = {k: v for k, v in groups.items()
           if bullets[v[0]].get("block") == "experience"}
    proj = {k: v for k, v in groups.items()
            if bullets[v[0]].get("block") == "projects"}

    for title, block in (("Experience", exp), ("Selected Projects", proj)):
        if not block:
            continue
        _heading(doc, title)
        for parent in sorted(block, key=lambda k: min(order[b] for b in block[k])):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(parent)
            r.bold = True
            r.font.size = Pt(10.5)
            for bid in block[parent]:
                _bullet(doc, bullets[bid].get("text", ""))

    # ── المهارات ──
    skills = cv_ctx.get("skills") or {}
    if skills:
        _heading(doc, "Skills")
        for group, items in skills.items():
            if not items:
                continue
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(f"{group.replace('_', ' ').title()}:  ")
            r.bold = True
            p.add_run(", ".join(str(i) for i in items))

    # ── التعليم ──
    edu = cv_ctx.get("education") or []
    if edu:
        _heading(doc, "Education")
        for e in edu:
            p = doc.add_paragraph()
            r = p.add_run(e.get("degree", ""))
            r.bold = True
            if e.get("note"):
                p.add_run(f" — {e['note']}")

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
