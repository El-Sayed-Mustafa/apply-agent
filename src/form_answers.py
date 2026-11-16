"""
إجابات أسئلة فورم التقديم — سؤال سؤال.

كل إجابة ليها مصدر معروف:
  profile   بياناتك من answers.yaml (الاسم، الإيميل، اللينكات…)
  policy    قاعدة مكتوبة (المرتب، التأشيرة، تاريخ البدء، EEO…)
  learned   إنت جاوبته قبل كده على تليجرام لنفس الوضع
  claude    سؤال مفتوح ("Why us?") — Sonnet يكتب من سيرتك، والفحص يقرر
  letter    الـcover letter نفسه
  ask       مش هنخمن — هيتسألك على تليجرام

قاعدة ثابتة: أي موافقة أو إقرار (consent / acknowledge / privacy / AI
evaluation) **عمره ما يتجاوب لوحده**. ده قرارك إنت، أول مرة على الأقل.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from . import answers, claude, cover, targeting

LEARNED = Path("state/learned_answers.json")

FIRST_PERSON = """You answer application-form questions for one candidate, in
his own voice. Output ONLY a JSON object {"<path>": "<answer>", ...}.

Rules for every answer:
- Use ONLY facts in CV FACTS and BULLETS. No new skills, numbers, employers,
  clients, titles or achievements. Numbers exactly as in the CV.
- Skills under skill_levels.developing/future and not_experienced_with must
  not be presented as experience. Never mention gaps or what he lacks.
- 40-110 words, plain first person, specific, no buzzwords ("passionate",
  "leverage", "excited", "perfect fit"), no em dashes, no bullet points.
- Answer the question asked. If it asks about the company, connect one CV
  fact to what the job description says the team does; do not praise them.
"""


# ── أدوات صغيرة ─────────────────────────────────────────────────────────

def norm(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (title or "").lower()).strip()[:160]


def pick(options: list[str], *patterns: str) -> str | None:
    """أول اختيار يطابق أول نمط ينفع — بالترتيب."""
    for pat in patterns:
        for o in options:
            if re.search(pat, o.strip(), re.I):
                return o
    return None


def yes_no(field: dict, yes: bool):
    if field["type"] == "Boolean":
        return yes
    if field["type"] in ("ValueSelect", "MultiValueSelect"):
        return pick(field.get("options") or [], r"^yes\b" if yes else r"^no\b")
    return "Yes" if yes else "No"


def ans(value, source: str, why: str = "") -> dict:
    return {"value": value, "source": source, "why": why}


def ask(why: str) -> dict:
    return {"value": None, "source": "ask", "why": why}


# ── الإجابات المتعلّمة ──────────────────────────────────────────────────

def load_learned() -> dict:
    try:
        return json.loads(LEARNED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def learn(title: str, scope: str, value) -> None:
    """إجابتك على سؤال بتتحفظ لنفس السؤال في نفس الوضع (ريموت/خليج/…)."""
    data = load_learned()
    data[f"{scope}|{norm(title)}"] = value
    LEARNED.parent.mkdir(parents=True, exist_ok=True)
    LEARNED.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ── القواعد ─────────────────────────────────────────────────────────────

CONSENT = re.compile(r"\b(consent|acknowledge|agree|privacy|terms|certify|attest|"
                     r"use of ai|artificial intelligence to|data processing|gdpr)\b", re.I)
EEO = re.compile(r"\b(gender|race|racial|ethnic|ethnicity|hispanic|latino|veteran|"
                 r"disabilit|pronoun|sexual orientation|transgender)\w*", re.I)
DECLINE = (r"prefer not|decline|don.?t wish|do not wish|not to (say|disclose|answer|"
           r"self)|rather not")
OPEN_Q = re.compile(r"^(why|what|how|tell|describe|share|walk|give|explain|which|"
                    r"in a few|please (describe|share|tell|explain))\b", re.I)


def _ctx(job: dict, policy: dict) -> dict:
    country, _ = targeting.detect_country(job.get("location"))
    remote = (job.get("remote_type") or "") == "remote"
    return {"country": country, "remote": remote,
            "scope": answers.situation(job, country)}


# ── "عندك خبرة في X؟" ─────────────────────────────────────────────────────
# 17 نوفمبر: في تجربة على فورم Lever، "Do you have LLM / AI / Machine
# Learning experience?" اتملت No (قيمة تجربة، ماتبعتتش). الإجابة الصح Yes:
# كلهم في skill_levels.verified في سيرتك. القاعدة: verified → Yes، وأي
# حاجة تانية (developing، future، not_experienced، MLOps…) بتتسألك —
# عمرها ما بتقول No لوحدها.
EXPERIENCE_Q = re.compile(
    r"\b(do|have) you (have|had|got)\b.*\bexperience\b|\bexperience (with|in|using|of)\b|"
    r"\b(are you|have you) (familiar|experienced|worked|used)\b", re.I)
# مش verified أو محتاج رأيك — يتسأل
NOT_SURE = re.compile(
    r"\b(ml ?ops|machine learning operations|deep learning|pytorch|tensorflow|"
    r"kubernetes|k8s|spark|hadoop|ios|swift|android|kotlin|java|c\+\+|golang|rust|"
    r"docker|aws|azure|gcp|cloud|langgraph|ci/?cd|terraform|n8n|zapier|"
    r"training (models?|llms?)|fine[- ]?tun|computer vision|management|managing|lead)\w*", re.I)
# من verified في سيرتك، بالأسامي اللي الفورمات بتكتبها
SURE = re.compile(
    r"\b(llms?|large language models?|ai|a\.i\.|artificial intelligence|generative ai|gen ?ai|"
    r"machine learning|ml|nlp|natural language processing|rag|retrieval[- ]augmented|"
    r"ai agents?|agentic|agents?|prompt engineering|prompting|python|fastapi|rest apis?|apis?|"
    r"sql|postgres(ql)?|supabase|playwright|selenium|web scraping|scraping|automation|"
    r"data pipelines?|pandas|scikit-learn|sklearn|lightgbm|ollama|whisper|webhooks?)\b", re.I)


def _verified() -> set[str]:
    try:
        from . import tailor
        return {s.lower() for s in (tailor.full().get("skill_levels") or {}).get("verified") or []}
    except Exception:
        return set()


def experience(field: dict) -> dict | None:
    """Yes لو الموضوع في سيرتك verified؛ None (يتسألك) لأي حاجة تانية."""
    t = field.get("title") or ""
    if field["type"] not in ("Boolean", "ValueSelect") or len(t) > 180 or not EXPERIENCE_Q.search(t):
        return None
    if field["type"] == "ValueSelect" and not pick(field.get("options") or [], r"^\s*yes\b"):
        return None                           # مش Yes/No (سنين، مستويات…) — سيبه للقواعد التانية
    if NOT_SURE.search(t):
        return None
    hit = SURE.search(t)
    if not hit and not any(re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", t.lower())
                           for v in _verified()):
        return None
    return ans(yes_no(field, True), "profile",
               f"في سيرتك verified: {hit.group(0) if hit else 'مهارة'}")


def rule(field: dict, job: dict, facts: dict | None, policy: dict,
         files: dict) -> dict | None:
    """إجابة بقاعدة، أو None لو القاعدة مش عارفة."""
    t = field["title"] or ""
    tl = t.lower()
    path, typ = field["path"], field["type"]
    opts = field.get("options") or []
    c = _ctx(job, policy)
    full = f"{policy.get('first_name', '')} {policy.get('last_name', '')}".strip()

    # ── حقول النظام ──
    # Ashby: _systemfield_name · Lever: name ("Full name")
    if path == "_systemfield_name" or (typ == "String" and
                                       re.fullmatch(r"(full |legal )?name", tl.strip())):
        return ans(full, "profile")
    if path == "_systemfield_email" or typ == "Email":
        return ans(policy.get("email"), "profile")
    # Ashby: _systemfield_resume · Greenhouse و Lever: resume
    if path in ("_systemfield_resume", "resume") or (
            typ == "File" and re.search(r"resume|\bcv\b", tl) and "cover" not in tl):
        return ans(files.get("cv"), "profile", "السيرة المتظبطة")
    if path == "_systemfield_location" or typ == "Location":
        return ans(f"{policy.get('city')}, {policy.get('country')}", "profile")
    if typ == "Phone" or re.search(r"\bphone|mobile\b", tl):
        return ans(policy.get("phone"), "profile")
    if typ == "File":
        if re.search(r"cover", tl) and files.get("letter_pdf"):
            return ans(files["letter_pdf"], "letter")
        return None

    # ── موافقات وإقرارات: إنت بس ──
    if CONSENT.search(tl):
        return None

    if EEO.search(tl):
        o = pick(opts, DECLINE)
        if o:
            return ans(o, "policy", "EEO: بفضّل ماقولش")
        return None if field["required"] else ans(None, "skip")

    # ── لينكات ──
    if typ in ("String", "LongText") and len(t) < 90:
        if re.search(r"linkedin", tl):
            return ans(policy.get("linkedin"), "profile")
        if re.search(r"github", tl):
            return ans(policy.get("github"), "profile")
        if re.search(r"portfolio|website|personal site|url", tl):
            return ans(policy.get("portfolio"), "profile")
        if re.search(r"preferred (first )?name|first name", tl):
            return ans(policy.get("first_name"), "profile")
        if re.search(r"last name|surname|family name", tl):
            return ans(policy.get("last_name"), "profile")
        if re.search(r"current (company|employer)", tl):
            return ans("BlueBug", "profile")
        if re.search(r"current (job )?(title|role|position)", tl):
            return ans("AI & Automation Engineer", "profile")
        if re.search(r"\b(city|country) of residence|where are you (based|located)", tl):
            return ans(f"{policy.get('city')}, {policy.get('country')}", "profile")

    # ── تصريح العمل والتأشيرة ──
    resides = re.search(r"currently resid|current(ly)? (location|live|based)|"
                        r"country (where|in which) you (currently )?(live|reside)", tl)
    # التأشيرة قبل التصريح: "require sponsorship … right to work" سؤال تأشيرة
    if re.search(r"sponsor", tl):
        if resides or c["country"] == "Egypt":
            return ans(yes_no(field, False), "policy", "مصري في مصر")
        if c["country"] and not c["remote"]:
            return ans(yes_no(field, True), "policy", "حضوري برّه مصر")
        return None
    if re.search(r"authori[sz]ed to work|right to work|eligible to work|work permit", tl):
        if resides or c["country"] == "Egypt":
            return ans(yes_no(field, True), "policy", "مصري في مصر")
        if c["country"] and not c["remote"]:
            return ans(yes_no(field, False), "policy", f"محتاج تأشيرة لـ{c['country']}")
        return None
    if re.search(r"relocat", tl):
        if typ in ("String", "LongText"):
            return ans(policy.get("relocation_note"), "policy")
        return ans(yes_no(field, True), "policy", "بتنقل مع تأشيرة")

    # ── المرتب ──
    if re.search(r"salary|compensation|pay expectation|rate expectation|desired pay", tl):
        if re.search(r"current", tl):
            v = answers.current_salary(field["required"], policy)
            return ans(v or None, "policy" if v else "skip")
        annual = bool(re.search(r"annual|year|yearly|per annum|p\.a", tl))
        local = answers.LOCAL_CURRENCY.get(c["country"]) if not c["remote"] else None
        text = answers.expected_text(job, facts, c["country"], policy, local, annual)
        if typ == "Number":
            return ans(re.sub(r"\D", "", text.split("/")[0]), "policy", text)
        if typ == "ValueSelect":
            return None
        return ans(text, "policy")

    # ── التوقيت ──
    if re.search(r"start date|earliest.*start|when can you start|available to start", tl):
        if typ == "Date":
            return ans((date.today() + timedelta(days=30)).isoformat(), "policy")
        return ans(policy.get("earliest_start_date"), "policy")
    if re.search(r"notice period", tl):
        return ans(policy.get("notice_period"), "policy")

    if re.search(r"years of (professional |relevant |work )?experience", tl) and \
            typ in ("Number", "String"):
        return ans(str(policy.get("years_of_experience", "")), "policy")

    # ── اللغات ──
    if re.search(r"english", tl) and re.search(r"proficien|level|fluen", tl):
        if typ == "Boolean":
            return ans(True, "policy")
        o = pick(opts, r"full professional|professional|fluent|advanced|c1|business")
        return ans(o, "policy") if o else None
    if re.search(r"arabic", tl) and re.search(r"proficien|level|fluen|native", tl):
        if typ == "Boolean":
            return ans(True, "policy")
        o = pick(opts, r"native|bilingual|fluent")
        return ans(o, "policy") if o else None
    if re.search(r"english and arabic", tl) and typ == "Boolean":
        return ans(True, "policy")

    # ── "عندك خبرة في X؟" Yes/No ──
    exp = experience(field)
    if exp is not None:
        return exp

    # ── عرفت منين ──
    if re.search(r"how did you (hear|find|learn)|where did you (hear|find|see)|"
                 r"referral source|source of application", tl):
        if typ in ("ValueSelect", "MultiValueSelect"):
            o = pick(opts, r"linkedin", r"job board|online|website|careers? page", r"other")
            return ans([o] if typ == "MultiValueSelect" else o, "policy") if o else None
        return ans("LinkedIn", "policy")

    if re.search(r"cover letter", tl) and typ in ("LongText", "String"):
        return ans(files.get("letter"), "letter") if files.get("letter") else None

    return None


def answer_all(fields: list[dict], job: dict, facts: dict | None, policy: dict,
               files: dict, cli=None) -> tuple[dict, float]:
    """
    رجّع ({path: إجابة}، تكلفة Sonnet). الترتيب: قاعدة → متعلّمة → Sonnet
    للأسئلة المفتوحة → اسأل.
    """
    out: dict[str, dict] = {}
    learned = load_learned()
    scope = _ctx(job, policy)["scope"]
    open_q: list[dict] = []
    for f in fields:
        a = rule(f, job, facts, policy, files)
        if a is None:
            key = f"{scope}|{norm(f['title'])}"
            if key in learned:
                a = ans(learned[key], "learned")
            elif f["type"] == "LongText" and not CONSENT.search(f["title"] or "") \
                    and (OPEN_Q.search(f["title"] or "") or "?" in (f["title"] or "")):
                open_q.append(f)
                continue
            elif not f["required"]:
                a = ans(None, "skip")
            elif f["type"] == "File":
                # ملف إجباري غير السيرة والخطاب (portfolio PDF…): مش سؤال
                # يتجاوب على تليجرام — بترفعه إنت وإنت بتراجع الفورم
                a = ans(None, "manual", "ارفعه بإيدك")
            else:
                a = ask("مش في القواعد")
        out[f["path"]] = a

    spent = 0.0
    if open_q:
        written, spent = write_open(open_q, job, cli)
        for f in open_q:
            text = written.get(f["path"])
            out[f["path"]] = (ans(text, "claude") if text
                              else ask("Sonnet ماكتبش إجابة سليمة") if f["required"]
                              else ans(None, "skip"))
    return out, spent


def write_open(fields: list[dict], job: dict, cli=None) -> tuple[dict, float]:
    """نداء واحد لكل الأسئلة المفتوحة في الفورم، وكل إجابة بتتفحص لوحدها."""
    cv = cover._cv_text()
    levels = cover._levels()
    system = FIRST_PERSON + "\n\nCV FACTS\n" + cv
    qs = "\n".join(f'- "{f["path"]}": {f["title"]}'
                   + (f" ({re.sub('<[^>]+>', ' ', f.get('description') or '')[:200]})"
                      if f.get("description") else "")
                   for f in fields)
    prompt = (f"JOB: {job.get('title')} at {job.get('company_name')}\n\n"
              f"{(job.get('description') or '')[:5000]}\n\nQUESTIONS\n{qs}\n\n"
              "Return the JSON now.")
    spent, good = 0.0, {}
    for _ in range(2):
        try:
            text, usage = claude.ask(system, prompt, max_tokens=3000, cli=cli)
            spent += claude.cost(usage)
            m = re.search(r"\{.*\}", text, re.S)
            raw = json.loads(m.group(0)) if m else {}
        except Exception:
            raw = {}
        bad = []
        for f in fields:
            v = raw.get(f["path"])
            if f["path"] in good or not isinstance(v, str) or not v.strip():
                continue
            probs = [p for p in cover.check(v, cv, levels) if "طويل" not in p]
            if len(v.split()) > 170:
                probs.append("طويل")
            if probs:
                bad.append(f'"{f["path"]}": ' + "; ".join(probs))
            else:
                good[f["path"]] = v.strip()
        if len(good) == len(fields):
            break
        prompt += "\n\nThese answers were rejected, rewrite them: " + " | ".join(bad)
    return good, spent


def pending(answers_map: dict) -> list[str]:
    return [p for p, a in answers_map.items() if a["source"] == "ask"]
