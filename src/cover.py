"""
الـcover letter — Sonnet بيكتب، والفحص بيقرر.

الموديل بيكتب نص هنا (مش بيختار معرّفات زي السيرة)، فالضمانة مش في
الـprompt — في الفحص بعده:
  · كل رقم في الخطاب لازم يكون موجود في سيرتك (80.7% · 10,000 · 6+)
  · ممنوع ذكر مهارة من developing / future / not_experienced_with كإنها
    خبرة — لو موجودة في الخطاب ومش في verified، الخطاب بيترفض
لو الفحص رفض، بنعيد مرة واحدة ومعاها سبب الرفض. لو رفض تاني، مفيش خطاب —
أحسن من خطاب فيه ادعاء غلط باسمك.

16 نوفمبر: اتطلب يبقى أقصر وبصوت إنسان — 70-110 كلمة، من غير العبارات
المحفوظة (passionate، leverage…) ولا em dash، والفحص بيمسكهم.

أول تجربة (Scale، 16 نوفمبر) كانت سليمة في الأرقام، بس قالت
"flagging blockers early is routine for me" — جملة عن أسلوب شغل مش في
السيرة. ده مش بيتمسك بالفحص الآلي، فالـprompt بيمنعه صراحةً.
"""
from __future__ import annotations

import re

import yaml

from . import claude, scoring, tailor

RULES = """You write a short cover letter in the candidate's own voice: an
engineer writing to another person, not a template.

HARD RULES — a letter that breaks any of these is rejected:
- Use ONLY facts in CV FACTS and BULLETS below. No new skills, numbers,
  employers, clients, titles, dates or achievements.
- Every number you write must appear in the CV exactly (80.7%, 10,000, 6+…).
- Skills under skill_levels.developing or future, and anything under
  not_experienced_with, must not be presented as experience.
- No claims about personality, work habits or soft skills that the CV does
  not state (for example "I flag blockers early", "evaluation is part of my
  routine").
- No flattery, no "passionate", "excited", "thrilled", "perfect fit",
  "I am writing to", "I would welcome the chance", "leverage", "robust",
  "seamless", "cutting-edge", "delve", "align", "proven track record".
- Do not mention skills or tools the candidate lacks, gaps, or what he
  would need to learn. Say what he has done; leave the rest out.
- No statements about availability, travel, relocation, start date or
  salary, except the exact relocation sentence if one is given below.
- No em dashes (—). No bullet points. No headings.

VOICE: plain and direct, like a message to a hiring manager you respect.
Short sentences mixed with longer ones. Contractions are fine (I've, it's).
Open with the one thing in the CV that answers the job's main need, not with
who you are. One concrete detail beats three general ones.

FORMAT: plain text, 70-110 words, two or three short paragraphs. Start with
the greeting given below. End with "Best,\nElsayed Mustafa".
Pick at most 2 CV facts, the ones closest to this job's stated needs.
"""

CLICHES = ["passionate", "excited to", "thrilled", "perfect fit", "i am writing to",
           "i would welcome", "leverage", "robust", "seamless", "cutting-edge",
           "delve", "proven track record", "results-driven", "dynamic team",
           "i am confident", "aligns with", "align with", "haven't worked with",
           "have not worked with", "learning those", "on the job", "no experience with"]
MAX_WORDS = 125

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?\+?%?")


def _cv_text() -> str:
    _, catalogue = tailor.load_catalogue()
    return scoring.load_cv() + "\n\nBULLETS\n" + catalogue


def _levels() -> dict:
    cv = tailor.full()
    lv = cv.get("skill_levels") or {}
    banned = list(lv.get("developing") or []) + list(lv.get("future") or [])
    for item in cv.get("not_experienced_with") or []:
        banned += [w.strip() for w in re.split(r"[/(),]", item) if len(w.strip()) > 2]
    return {"verified": {s.lower() for s in lv.get("verified") or []},
            "banned": [b for b in banned if b.lower() not in
                       {s.lower() for s in lv.get("verified") or []}]}


def check(letter: str, cv_text: str | None = None,
          levels: dict | None = None) -> list[str]:
    """أسباب الرفض. قايمة فاضية = الخطاب سليم."""
    cv_text = cv_text if cv_text is not None else _cv_text()
    levels = levels or _levels()
    flat = cv_text.replace(",", "")
    problems = []
    for n in _NUM.findall(letter):
        core = n.replace(",", "").rstrip("+%")
        if len(core) <= 1 and not n.endswith(("+", "%")):
            continue                       # "a 3-step" وكده — مش ادعاء
        if core not in flat:
            problems.append(f"رقم مش في السيرة: {n}")
    low = letter.lower()
    for c in CLICHES:
        if c in low:
            problems.append(f"عبارة محفوظة: {c}")
    if "—" in letter:
        problems.append("فيه em dash (—)")
    words = len(re.findall(r"[A-Za-z0-9'’.+%-]+", letter))
    if words > MAX_WORDS:
        problems.append(f"طويل: {words} كلمة")
    for skill in levels["banned"]:
        if re.search(r"(?<!\w)" + re.escape(skill.lower()) + r"(?!\w)", low):
            problems.append(f"مهارة مش خبرة عندك: {skill}")
    return problems


_ORG = re.compile(r"\b(inc|llc|ltd|gmbh|group|labs?|technologies|solutions|"
                  r"recruit\w*|talent|careers|hr|hiring|consult\w*)\b", re.I)


def _nice(name: str) -> str:
    """SMART VISIONS → Smart Visions. الاسم المكتوب كابيتال كله بيبان صريخ."""
    return name.title() if name.isupper() and len(name) > 4 else name


def greeting(job: dict) -> str:
    """
    منشور لينكدإن من شخص → "Hi Tamer,". شركة → "Hi Scale team,".
    مش واضح → "Hello,".

    17 نوفمبر: "Hi SMART," — المنشور كان فيه اسم الشركة (SMART VISIONS)،
    والقاعدة افتكرته اسم شخص وخدت أول كلمة. دلوقتي اللي نشر متسجّل في
    الوصف ("نشره على لينكدإن: …")، والاسم بيتعامل كشخص بس لو هو نفسه
    اللي نشر. الاسم الكابيتال كله عمره ما يبقى اسم شخص.
    """
    name = re.split(r"[,|(]", job.get("company_name") or "")[0].strip()
    if not name:
        return "Hello,"
    if job.get("ats") == "linkedin_post":
        m = re.search(r"نشره على لينكدإن:\s*(.+)", job.get("description") or "")
        poster = re.split(r"[,|(]", m.group(1))[0].strip() if m else ""
        person = (name.lower() == poster.lower()) if poster else (
            not _ORG.search(name) and not name.isupper()
            and name.split()[0].isalpha() and len(name.split()) <= 4)
        if person:
            return f"Hi {name.split()[0]},"
        if poster or name.isupper() or _ORG.search(name):
            return f"Hi {_nice(name)} team," if not _ORG.search(name) else "Hello,"
        return "Hello,"
    return f"Hi {_nice(name)} team,"


def write(job: dict, relocation_line: str = "", cli=None) -> tuple[str | None, list[str], float]:
    """
    رجّع (الخطاب، أسباب الرفض لو فشل، التكلفة بالدولار).
    السيرة والقواعد في system وعليها cache — النداء التاني أرخص بكتير.
    """
    cv = _cv_text()
    system = RULES + "\n\nCV FACTS\n" + cv
    prompt = (f"Job: {job.get('title')} at {job.get('company_name')} "
              f"({job.get('location') or 'location not stated'})\n\n"
              f"{(job.get('description') or '')[:6000]}\n\n"
              + (f"Add this sentence near the end, as written: {relocation_line}\n"
                 if relocation_line else "")
              + f"Greeting: {greeting(job)}\n"
              + "Write the letter now.")
    spent = 0.0
    problems: list[str] = []
    for _ in range(2):
        text, usage = claude.ask(system, prompt, max_tokens=2000, cli=cli)
        spent += claude.cost(usage)
        problems = check(text, cv)
        if not problems:
            return text.strip(), [], spent
        prompt += ("\n\nYour previous draft was rejected for: "
                   + "; ".join(problems) + ". Rewrite it without these.")
    return None, problems, spent
