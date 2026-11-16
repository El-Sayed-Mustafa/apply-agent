"""
تظبيط السيرة على وظيفة بعينها — بيحصل لما تدوس "✅ قدّم" بس.

Sonnet بيقترح، والفحص هنا بيقرر. كل حاجة اترفضت بترجع لأصلها من
cv.yaml، فأسوأ حالة = سيرتك الأصلية، مش سيرة فيها ادعاء غلط.

اللي بيتغيّر:
  · العنوان تحت اسمك    → قريب من عنوان الوظيفة، من غير درجة أعلى منك
                            (Senior/Lead…) ومن غير مهارة مش خبرة عندك
  · الملخص               → مكتوب للوظيفة، وكل رقم فيه من سيرتك
  · صياغة النقط          → بلغة الإعلان؛ نفس الأرقام بالظبط، ومفيش أداة
                            أو تقنية جديدة مش مذكورة في نفس الجهة
  · ترتيب النقط والمشاريع ومجموعات المهارات
اللي مش بيتغيّر: الجهات، التواريخ، التعليم، الشهادات، قايمة المهارات نفسها.
"""
from __future__ import annotations

import copy
import json
import re

from . import claude, cover, tailor

SENIORITY = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|head|chief|director|manager|vp|"
    r"vice|president|architect|founder|expert|ii|iii|iv)\b", re.I)
ROLE_WORD = re.compile(
    r"\b(ai|automation|llm|ml|machine learning|python|backend|back-end|genai|"
    r"generative|applied|data|integrations?|nlp|agents?|software|solutions?|"
    r"forward deployed|engineer|developer)\b", re.I)
_NUM = re.compile(r"\d[\d,.]*\+?%?")

RULES = """You tailor an existing CV to one job. You rewrite wording; you never
add facts. Output ONLY a JSON object, no prose, no code fences:

{
 "title":   "<CV headline under the name>",
 "summary": "<2-3 sentences>",
 "bullets": {"<bullet id>": "<rewritten bullet>", ...},
 "bullet_order": ["<bullet ids, most relevant first>"],
 "projects": ["<project ids, most relevant first>"],
 "skill_groups": ["<skill group names, most relevant first>"]
}

title: as close to the job's own title as is TRUE for this candidate. Drop
  seniority words (Senior, Lead, Principal, Staff, Head, Manager, II/III).
  Max 6 words. If the job title names a skill he lacks, use the nearest true
  title (e.g. "AI Engineer" instead of "MLOps Engineer").
summary: written for this job, using the job's vocabulary where the CV
  supports it. 45-75 words. Only facts in the CV. Numbers only as written in
  the CV. Plain, specific, no buzzwords ("passionate", "results-driven",
  "proven track record", "leverage", "cutting-edge").
bullets: rewrite only bullets that benefit (usually 3-7). Lead with what this
  job cares about, mirror its terms when they describe the SAME work. Keep
  every number exactly as in the original, add no new number, tool, client,
  or scope. About the same length as the original. Omit bullets you keep.
bullet_order / projects / skill_groups: ids and names exactly as given.

Never present these as experience: {banned}
"""


_WORDS = re.compile(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
                    r"twelve|dozens?|hundreds?|thousands?|millions?|several|multiple)\b", re.I)


def _nums(text: str) -> set[str]:
    """الأرقام وكلمات العدد ("three"، "dozens") — الاتنين ادعاء."""
    return ({n.replace(",", "").rstrip(".") for n in _NUM.findall(text or "")}
            | {w.lower() for w in _WORDS.findall(text or "")})


def vocabulary(cv: dict) -> set[str]:
    """كل أسامي الأدوات والمهارات اللي في السيرة — عشان نعرف لو نقطة زادت أداة."""
    out: set[str] = set()
    for items in (cv.get("skills") or {}).values():
        out |= {str(x) for x in items}
    lv = cv.get("skill_levels") or {}
    for k in ("verified", "developing", "future"):
        out |= {str(x) for x in lv.get(k) or []}
    for k, syns in (cv.get("skill_synonyms") or {}).items():
        out |= {k, *map(str, syns)}
    for p in (cv.get("projects") or []) + (cv.get("experience") or []):
        out |= {s.strip() for s in re.split(r"[,/]", p.get("stack") or "") if s.strip()}
    out |= {"AWS", "Docker", "Kubernetes", "LangChain", "LlamaIndex", "Azure",
            "GCP", "React", "TypeScript", "Node.js", "Spark", "PyTorch",
            "TensorFlow", "n8n", "Zapier", "Airflow", "Kafka", "MLflow"}
    return {v for v in out if len(v) > 1}


def _has(term: str, text: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)",
                          text.lower()))


# كلمات العنوان المسموح نقلها من الإعلان كما هي — كلها وصف لشغل بتعمله
TITLE_OK = {"ai", "ml", "llm", "nlp", "genai", "gen", "generative", "applied",
            "automation", "machine", "learning", "forward", "deployed", "software",
            "solutions", "solution", "engineer", "developer", "backend", "back-end",
            "python", "data", "integration", "integrations", "agent", "agents",
            "agentic", "platform", "product", "full-stack", "fullstack", "ai/ml",
            "intelligence", "artificial", "process", "workflow", "and", "&", "/"}
ACRONYM = {"ai", "ml", "llm", "nlp", "genai", "ai/ml"}


def job_title(raw: str) -> str:
    """
    عنوان الوظيفة نفسه للسيرة: من غير درجة (Senior/Lead…) ولا اسم الفريق
    (", Agentic Platform" · " - North America" · "(m/f/d)"). "" لو فيه كلمة
    مش من شغلك (MLOps، iOS…) — ساعتها Sonnet يختار أقرب عنوان صادق.
    """
    t = re.sub(r"\(.*?\)", " ", raw or "")
    t = re.split(r"\s[-–|]\s|,|:", t)[0]
    t = SENIORITY.sub(" ", t)
    words = [w for w in re.split(r"\s+", t.replace(".", " ")) if w]
    if not words or any(w.lower() not in TITLE_OK for w in words):
        return ""
    return " ".join(w.upper() if w.lower() in ACRONYM else
                    (w if w[:1].isupper() and not w.isupper() else w.capitalize())
                    for w in words)


def check_title(title: str, levels: dict) -> list[str]:
    t = (title or "").strip()
    probs = []
    if not t or len(t) > 60 or len(t.split()) > 6:
        probs.append("العنوان طويل أو فاضي")
    if SENIORITY.search(t):
        probs.append(f"درجة أعلى منك في العنوان: {SENIORITY.search(t).group(0)}")
    if not ROLE_WORD.search(t):
        probs.append("العنوان مش وصف لشغلك")
    probs += [p for p in cover.check(t, "", levels) if "مهارة" in p]
    return probs


def check_bullet(new: str, original: str, context: str, vocab: set[str],
                 levels: dict) -> list[str]:
    """
    النقطة الجديدة لازم: نفس الأرقام بالظبط، ومفيش أداة مش مذكورة في
    النقطة الأصلية أو في نفس الجهة (context)، ومفيش مهارة مش خبرة، وطول
    قريب من الأصل (عشان الصفحتين).
    """
    probs = []
    if _nums(new) != _nums(original):
        probs.append(f"الأرقام اتغيّرت: {sorted(_nums(original))} → {sorted(_nums(new))}")
    for term in vocab:
        if _has(term, new) and not _has(term, original) and not _has(term, context):
            probs.append(f"أداة جديدة: {term}")
    for skill in levels["banned"]:
        if _has(skill, new) and not _has(skill, original):
            probs.append(f"مهارة مش خبرة عندك: {skill}")
    if len(new) > len(original) * 1.4 + 30:      # الصفحتين محميين في render.build
        probs.append("أطول من الأصل بكتير")
    return probs


def _contexts(cv: dict) -> dict[str, str]:
    """لكل نقطة: نص الجهة بتاعتها كله (الاسم، الـstack، النقط التانية)."""
    out = {}
    for block in ("experience", "projects"):
        for e in cv.get(block) or []:
            text = " ".join(str(e.get(k) or "") for k in ("role", "company", "name", "stack"))
            text += " " + " ".join(b.get("text", "") + " " + " ".join(b.get("tags") or [])
                                   for b in e.get("bullets") or [])
            for b in e.get("bullets") or []:
                out[b.get("id")] = text
    return out


def validate(plan: dict, cv: dict, levels: dict | None = None) -> tuple[dict, list[str]]:
    """
    رجّع (الخطة بعد الفحص، اللي اترفض). كل حاجة اترفضت بتتشال من الخطة
    وترجع لأصلها.
    """
    levels = levels or cover._levels()
    bullets, _ = tailor.load_catalogue()
    vocab = vocabulary(cv)
    ctx = _contexts(cv)
    rejected: list[str] = []
    out: dict = {}

    title = re.sub(r"\s+", " ", str(plan.get("title") or "")).strip()
    probs = check_title(title, levels)
    if title and not probs:
        out["title"] = title
    elif title:
        rejected.append(f"العنوان «{title}»: " + "؛ ".join(probs))

    summary = re.sub(r"\s+", " ", str(plan.get("summary") or "")).strip()
    if summary:
        flat = json.dumps(cv, ensure_ascii=False)
        probs = cover.check(summary, flat, levels)
        if not 150 <= len(summary) <= 600:
            probs.append("طول الملخص")
        if probs:
            rejected.append("الملخص: " + "؛ ".join(probs))
        else:
            out["summary"] = summary

    texts = {}
    for bid, new in (plan.get("bullets") or {}).items():
        if bid not in bullets or not isinstance(new, str):
            continue
        new = re.sub(r"\s+", " ", new).strip()
        orig = bullets[bid].get("text", "")
        if not new or new == orig:
            continue
        probs = check_bullet(new, orig, ctx.get(bid, ""), vocab, levels)
        if probs:
            rejected.append(f"{bid}: " + "؛ ".join(probs))
        else:
            texts[bid] = new
    out["bullets"] = texts

    out["bullet_order"] = [b for b in dict.fromkeys(plan.get("bullet_order") or [])
                           if b in bullets]
    active = {p.get("id") for p in cv.get("projects") or [] if p.get("active") is not False}
    out["projects"] = [p for p in dict.fromkeys(plan.get("projects") or []) if p in active]
    groups = set((cv.get("skills") or {}).keys())
    out["skill_groups"] = [g for g in dict.fromkeys(plan.get("skill_groups") or [])
                           if g in groups]
    return out, rejected


def _job_terms(description: str) -> str:
    return (description or "").lower()


def apply(cv: dict, plan: dict, description: str = "") -> dict:
    """
    نسخة من السيرة بالخطة متطبقة. المهارات جوّه كل مجموعة بتترتّب: اللي
    مذكور في الإعلان الأول. مفيش مهارة بتتضاف ولا بتتشال.
    """
    cv = copy.deepcopy(cv)
    order = {b: i for i, b in enumerate(plan.get("bullet_order") or [])}
    texts = plan.get("bullets") or {}
    for block in ("experience", "projects"):
        for e in cv.get(block) or []:
            bs = e.get("bullets") or []
            for b in bs:
                if b.get("id") in texts:
                    b["text"] = texts[b["id"]]
            # المختارة بترتيب الموديل، والباقي بترتيب rank الأصلي بعدها
            ranked = sorted(bs, key=lambda b: (order.get(b.get("id"), 999),
                                               b.get("rank", 99)))
            for i, b in enumerate(ranked, 1):
                b["rank"] = i
    if plan.get("title"):
        cv.setdefault("profile", {})["title"] = plan["title"]
    if plan.get("summary"):
        cv.setdefault("profile", {})["summary"] = plan["summary"]

    job = _job_terms(description)
    skills = cv.get("skills") or {}
    names = [g for g in plan.get("skill_groups") or [] if g in skills]
    names += [g for g in skills if g not in names]
    cv["skills"] = {g: sorted(skills[g], key=lambda s: (not _has(str(s), job),))
                    for g in names}
    return cv


def chosen_ids(cv: dict, plan: dict) -> list[str]:
    """ترتيب المشاريع بصيغة render.build (أول نقطة من كل مشروع)."""
    by_id = {p.get("id"): p for p in cv.get("projects") or []}
    out = []
    for pid in plan.get("projects") or []:
        bs = (by_id.get(pid) or {}).get("bullets") or []
        if bs:
            out.append(bs[0]["id"])
    return out


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("مفيش JSON في الرد")
    return json.loads(m.group(0))


def plan_for(job: dict, cli=None) -> tuple[dict, list[str], float]:
    """
    رجّع (الخطة بعد الفحص، اللي اترفض، التكلفة). لو النداء نفسه فشل،
    خطة فاضية = السيرة الأصلية.
    """
    cv = tailor.full()
    levels = cover._levels()
    _, catalogue = tailor.load_catalogue()
    projects = "\n".join(f"  {p['id']}: {p.get('name')}" for p in cv.get("projects") or []
                         if p.get("active") is not False)
    system = (RULES.replace("{banned}", ", ".join(levels["banned"]))
              + "\n\nCV\n" + json.dumps(
                  {"title": (cv.get("profile") or {}).get("title"),
                   "summary": (cv.get("profile") or {}).get("summary"),
                   "skills": cv.get("skills"),
                   "not_experienced_with": cv.get("not_experienced_with")},
                  ensure_ascii=False, indent=1)
              + "\n\nBULLETS (id: text)\n" + catalogue
              + "\n\nPROJECT IDS\n" + projects)
    prompt = (f"JOB TITLE: {job.get('title')}\n"
              f"LOCATION: {job.get('location') or 'not stated'}\n\n"
              f"{(job.get('description') or '')[:7000]}\n\nReturn the JSON now.")
    spent = 0.0
    try:
        text, usage = claude.ask(system, prompt, max_tokens=3000, cli=cli)
        spent += claude.cost(usage)
        raw = _parse(text)
    except Exception as exc:
        return {}, [f"النداء فشل: {type(exc).__name__}: {exc}"[:200]], spent
    plan, rejected = validate(raw, cv, levels)
    same = job_title(job.get("title") or "")
    if same and not check_title(same, levels):
        plan["title"] = same              # عنوان الوظيفة نفسه، لو صادق عليك
    return plan, rejected, spent


def changes_text(cv: dict, plan: dict, rejected: list[str]) -> str:
    """ملخص اللي اتغيّر — بيتبعتلك مع السيرة عشان تراجعه."""
    from . import telegram
    lines = ["✏️ <b>اللي اتغيّر في السيرة</b>"]
    old_title = (cv.get("profile") or {}).get("title")
    if plan.get("title") and plan["title"] != old_title:
        lines.append(f"• العنوان: {telegram.esc(old_title)} ← <b>{telegram.esc(plan['title'])}</b>")
    if plan.get("summary"):
        lines.append("• الملخص اتكتب للوظيفة دي")
    if plan.get("bullets"):
        lines.append(f"• اتعادت صياغة {len(plan['bullets'])} نقط بلغة الإعلان (نفس الأرقام)")
    if plan.get("projects"):
        names = {p.get("id"): p.get("name") for p in cv.get("projects") or []}
        lines.append("• أول مشروع: " + telegram.esc(names.get(plan["projects"][0], "")))
    if rejected:
        lines.append(f"• اترفض {len(rejected)} اقتراح ورجع لأصله:")
        lines += [f"   – {telegram.esc(r[:140])}" for r in rejected[:5]]
    if len(lines) == 1:
        lines.append("• مفيش — السيرة الأصلية")
    return "\n".join(lines)
