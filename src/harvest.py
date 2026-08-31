"""
منشورات التوظيف على لينكدإن كمصدر وظايف.

  python -m src.harvest --dry-run   → دوّر واعرض من غير حفظ
  python -m src.harvest             → دوّر واحفظ الوظايف الجديدة

ليه الملف ده موجود:

كان في فجوة. مصادر الوظايف كلها APIs — Greenhouse و Lever و Ashby
والمجمّعات. والحاجة الوحيدة اللي بتقرا منشورات لينكدإن هي وحدة
الكومنتات، ووظيفتها تدوّر على منشور يستاهل تعليق — فبترمي أي منشور
توظيف لإنه مش هدف كومنت كويس.

يعني منشور فيه وظيفة كان بيتشاف وبيترمي. مفيش طريق أصلاً من
"منشور في لينكدإن" لـ"وظيفة في قاعدة البيانات".

وفي سبب تاني أهم: الـfeed بتاعك بيعكس شبكتك القديمة (Data Analyst).
فحتى لو الطريق كان موجود، اللي هيوصلك هو اللي الـfeed بيوريهولك.
عشان كده احنا **بندوّر** مش بنستنى الـfeed.

الحكم هنا للموديل مش لـregex: المنشور بيتقرا ويترد عليه "دي وظيفة
بالتفاصيل دي" أو "مش وظيفة". الـregex كان بيقرر بكلمات مفتاحية،
وده اللي خلى المنظومة تبان غبية.

الوظايف اللي بتطلع بتتحفظ في نفس جدول jobs، فبتمشي في نفس المسار
الموجود: الاستهداف → التقييم → تفصيل الـCV → تليجرام. مفيش مسار
تسليم جديد.
"""
from __future__ import annotations

import argparse
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv
from google.genai import types

from . import genai_pool, targeting
from .adapters import Job
from .linkedin import session
from .linkedin.session import Blocked
from .main import get_client, save
from .scoring import (API_RETRIES, MODELS, _is_daily_quota,
                      _retry_delay)

load_dotenv()

CFG = "targeting.yaml"

# كام منشور نقرا في التشغيلة. القراءة نداء موديل لكل منشور، والحصة
# المجانية محدودة بالدقيقة — 25 بتخلص من غير 429.
MAX_POSTS = int(os.getenv("HARVEST_MAX_POSTS", "25"))

# منشور التوظيف بيبقى طويل: مسمى وموقع ومتطلبات وطريقة تقديم.
# أي حاجة أقصر من كده مش هتطلّع وظيفة كاملة.
MIN_CHARS = 220

# ثانيتين بين النداءات: الحصة المجانية بتتقاس بالدقيقة
PACE = 2.0


# ── المنشورات ───────────────────────────────────────────────────────────

# مفيش data-urn في صفحة البحث (فيه في صفحات النشاط بس). الثابت
# الوحيد هو تسمية قارئ الشاشة اللي بتبدأ بيها كل بطاقة منشور.
#
# والنص بيتكرر: نفس المنشور بيتلفّ في تلات divs متداخلة بكلاسات
# مختلفة. بنمسك أول واحد لكل نص وبنرمي المتداخل.
JS_SEARCH = r"""() => {
  const isPost = t => /^(feed post|منشور)/i.test(t);
  const out = [], seen = new Set();
  document.querySelectorAll('div,li,article').forEach(e => {
    const t = (e.innerText || '').trim();
    if (t.length < 200 || t.length > 6000 || !isPost(t)) return;
    const k = t.slice(0, 150);
    if (seen.has(k)) return;
    seen.add(k);

    const who = e.querySelector('a[href*="/in/"]');
    const links = [...e.querySelectorAll('a[href]')]
      .map(a => a.getAttribute('href') || '')
      .filter(h => /^https?:/.test(h) && !/linkedin\.com\/(in|company)\//.test(h));

    out.push({
      text: t.slice(0, 4000),
      who_url: who ? (who.getAttribute('href') || '').split('?')[0] : '',
      links: [...new Set(links)].slice(0, 4)
    });
  });
  return out.slice(0, 30);
}"""

# سطور الواجهة اللي بتتلم مع النص
NOISE = re.compile(
    r"^(feed post|منشور|follow|following|متابعة|·|•|like|comment|repost|send|"
    r"\d+[hdwmy]|\d+\s*(?:comments?|reposts?|likes?)|premium|"
    r"\s*•\s*(?:1st|2nd|3rd\+?)|see more|…\s*more|show more)\s*$", re.I)


def clean(raw: str) -> tuple[str, str]:
    """رجّع (اسم الكاتب، نص المنشور) بعد شيل سطور الواجهة."""
    lines = [x.strip() for x in (raw or "").split("\n")]
    lines = [x for x in lines if x and not NOISE.match(x)]
    author = lines[0] if lines else ""
    body = " ".join(lines[1:])
    return author[:80], re.sub(r"\s+", " ", body)[:4000]


# فلتر رخيص قبل نداء الموديل. الـregex هنا **مش** بيقرر إذا كان
# المنشور وظيفة — ده شغل الموديل. هو بس بيقرر المنشور يستاهل نداء
# ولا لأ، والحصة اليومية هي السبب: 14 منشور × نداء = ربع الحصة
# على منشورات معظمها مش وظايف أصلاً.
#
# مضبوط على الاسترجاع مش الدقة: أي شبهة توظيف بتعدّي للموديل.
HIRING = re.compile(
    r"hiring|we(?:'| a)re looking for|join (?:our|the) team|now recruiting|"
    r"vacanc|open (?:role|position)|apply (?:now|here|through|via)|"
    r"send your (?:cv|resume)|فرصة وظيفية|وظيفة شاغرة|وظائف|مطلوب|"
    r"نبحث عن|التقديم|أرسل السيرة", re.I)

# منشور حد بيدوّر لنفسه على شغل — عكس اللي احنا وراه بالظبط
SEEKING = re.compile(
    r"open to work|looking for (?:a |new )?(?:job|role|opportunit)|"
    r"seeking (?:a |new )?(?:job|role|opportunit)|أبحث عن (?:عمل|وظيفة|فرصة)|"
    r"متاح للعمل", re.I)


def worth_asking(text: str) -> bool:
    """يستاهل ندفع فيه نداء موديل؟"""
    return bool(HIRING.search(text)) and not SEEKING.search(text)


def searches() -> list[str]:
    cfg = yaml.safe_load(open(CFG, encoding="utf-8")) or {}
    return (cfg.get("post_search") or {}).get("queries") or []


def collect(page, queries: list[str], want: int = MAX_POSTS) -> list[dict]:
    """دوّر في منشورات لينكدإن وارجع اللي شكله إعلان وظيفة."""
    found: dict[str, dict] = {}

    # حصة لكل استعلام بدل ما الأول ياخد كله. من غير ده، أول
    # استعلامين بيملوا العدد المطلوب والاستعلامات الخليجية
    # والعربية — اللي هي أهم حاجة — مابتشتغلش أصلاً.
    per_query = max(2, want // max(len(queries), 1))

    for q in queries:
        if len(found) >= want:
            break
        got = 0
        url = ("https://www.linkedin.com/search/results/content/?keywords="
               + urllib.parse.quote(q)
               + "&datePosted=%22past-week%22&sortBy=%22date_posted%22")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:
            print(f"   ⚠ {q}: {exc}")
            continue

        session.human_pause(6, 10)
        session.guard(page)

        for _ in range(2):
            try:
                raw = page.evaluate(JS_SEARCH)
            except Exception as exc:
                # الابتلاع الصامت هنا هو اللي ضيّع علينا تشخيص كامل قبل كده
                print(f"   ⚠ تعذّرت قراءة نتايج «{q}»: {exc}")
                raw = []

            for p in raw:
                if got >= per_query:
                    break
                author, body = clean(p["text"])
                if len(body) < MIN_CHARS:
                    continue
                key = body[:160].lower()
                if key in found:
                    continue
                got += 1
                found[key] = {
                    "author": author,
                    "author_url": p["who_url"],
                    "links": p["links"],
                    "text": body,
                    "query": q,
                }

            if got >= per_query or len(found) >= want:
                break
            page.mouse.wheel(0, 1600)
            session.human_pause(3, 6)
            session.guard(page)

    return list(found.values())[:want]


# ── الاستخراج ───────────────────────────────────────────────────────────

SCHEMA = {
    "type": "object",
    "properties": {
        "is_job": {
            "type": "boolean",
            "description": "منشور بيعلن عن وظيفة شاغرة محددة يقدر حد يقدّم عليها",
        },
        "title": {"type": "string", "description": "المسمى الوظيفي زي ما هو مكتوب"},
        "company": {"type": "string", "description": "اسم الشركة، أو '' لو مش مذكور"},
        "location": {"type": "string", "description": "المدينة والدولة، أو ''"},
        "remote_type": {"type": "string", "enum": ["remote", "hybrid", "onsite", "unknown"]},
        "apply": {
            "type": "string",
            "description": "رابط أو إيميل التقديم زي ما هو في المنشور، أو ''",
        },
        "summary": {
            "type": "string",
            "description": "المتطلبات والمهارات زي ما وردت. مترجمش ومتزوّدش من عندك.",
        },
    },
    "required": ["is_job", "title", "company", "location", "remote_type",
                 "apply", "summary"],
}

PROMPT = """اقرا منشور لينكدإن ده وقول هو إعلان وظيفة ولا لأ.

is_job = true بس لو المنشور بيعلن عن **وظيفة شاغرة محددة** ينفع حد
يقدّم عليها دلوقتي.

is_job = false لو المنشور:
- شخص بيدوّر على شغل لنفسه (Open to work)
- نصايح مهنية أو محتوى تقني أو رأي
- إعلان عن كورس أو ويبينار أو منتج
- تهنئة بوظيفة جديدة
- كلام عام عن سوق العمل أو "شركتنا بتكبر"
- **قايمة وظايف**: منشور بيسرد كذا وظيفة مع بعض ("10 AI roles
  hiring now"، "وظايف الأسبوع"). احنا عايزين وظيفة **واحدة
  محددة** بمسمى واحد — القايمة مالهاش مسمى ولا شركة ولا موقع

انقل الكلام زي ما هو من المنشور. متخترعش اسم شركة ولا موقع ولا
متطلبات مش مكتوبة — سيبها "" لو مش موجودة.

المنشور:
---
{text}
---"""


def extract(client, post: dict, models: list[str] | None = None) -> tuple[dict | None, str]:
    """رجّع (بيانات الوظيفة، الخطأ). None يعني مش وظيفة."""
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=SCHEMA)
    last = ""

    # نفس منطق التقييم: 429 على الدقيقة معناها استنى، و429 على اليوم
    # معناها الموديل ده مات — انط للي بعده. الفرق بينهم هو الفرق بين
    # تشغيلة بترجع 13 فشل وتشغيلة بترجع 13 وظيفة.
    for model in (models or MODELS):
        for attempt in range(API_RETRIES):
            try:
                r = client.models.generate_content(
                    model=model, contents=PROMPT.format(text=post["text"]),
                    config=cfg)
            except Exception as exc:
                msg = str(exc)
                last = f"{type(exc).__name__}: {msg[:90]}"
                if _is_daily_quota(msg):
                    break
                if not any(c in msg for c in ("429", "503", "500", "UNAVAILABLE")):
                    break
                time.sleep((_retry_delay(msg) or 2 ** attempt) + 0.5)
                continue

            try:
                import json
                data = json.loads(r.text)
            except Exception as exc:
                last = f"رد مش JSON: {exc}"
                break

            if not data.get("is_job"):
                return None, ""
            if not (data.get("title") or "").strip():
                return None, ""
            return data, ""

    return None, last or "كل الموديلات فشلت"


def to_job(post: dict, data: dict) -> Job:
    """
    حوّل الاستخراج لوظيفة.

    الشركة لما تكون ناقصة بناخد اسم الناشر: البصمة محتاجة حاجة ثابتة،
    و"مجهولة" لكل المنشورات هتخلي وظايف مختلفة تبان مكررة.
    """
    company = (data.get("company") or "").strip() or (post["author"] or "لينكدإن")
    apply_url = (data.get("apply") or "").strip()
    if not apply_url.startswith("http"):
        apply_url = next((l for l in post["links"] if l.startswith("http")),
                         post["author_url"] or "")

    body = data.get("summary") or post["text"]
    if data.get("apply") and not data["apply"].startswith("http"):
        # إيميل التقديم لازم يوصله — مش هيلاقيه في الرابط
        body = f"{body}\n\nطريقة التقديم: {data['apply']}"

    return Job(
        company_name=company[:120],
        ats="linkedin_post",
        external_id=post["text"][:120],
        title=(data.get("title") or "").strip()[:160],
        location=(data.get("location") or "").strip()[:120] or None,
        remote_type=data.get("remote_type") or "unknown",
        description=body[:6000],
        url=apply_url or None,
        posted_at=datetime.now(timezone.utc).isoformat(),
    )


def dedupe(jobs: list[Job]) -> list[Job]:
    """
    شيل المكرر جوّا التشغيلة.

    البصمة فيها اسم الشركة، ولما اتنين يعيدوا نشر نفس الإعلان
    الموديل بيقرا اسم الناشر كشركة — فنفس الوظيفة بتاخد بصمتين
    وبتوصلك مرتين. بنقارن على المسمى والموقع بس.
    """
    seen, out = set(), []
    for j in jobs:
        # أول جزء من الموقع بس: "Toronto, Ontario" و"Toronto,
        # Ontario, Canada" نفس المكان — والفرق ده لوحده كان بيمرّر
        # الإعلان مرتين.
        city = (j.location or "").split(",")[0]
        k = (re.sub(r"\W+", "", (j.title or "").lower()),
             re.sub(r"\W+", "", city.lower()))
        if k in seen:
            continue
        seen.add(k)
        out.append(j)
    return out


# ── التشغيل ─────────────────────────────────────────────────────────────

def run(dry: bool = False, limit: int = MAX_POSTS) -> dict:
    from google import genai

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {"error": "مفيش GEMINI_API_KEY"}

    queries = searches()
    if not queries:
        return {"error": f"مفيش post_search.queries في {CFG}"}

    print(f"🔎 {len(queries)} بحث\n")
    with session.browser(headless=False) as page:
        if not session.logged_in(page):
            return {"error": "مفيش جلسة LinkedIn"}
        try:
            posts = collect(page, queries, want=limit)
        except Blocked as b:
            return {"error": f"اعتراض: {b}"}

    print(f"📰 {len(posts)} منشور\n")
    client = genai_pool.client()
    jobs, skipped = [], 0

    asked = 0
    for p in posts:
        if not worth_asking(p["text"]):
            skipped += 1
            continue
        if asked:
            time.sleep(PACE)
        asked += 1
        data, err = extract(client, p)
        if not data:
            skipped += 1
            if err:
                print(f"   ⚠ {p['author'][:18]:<20}{err[:60]}")
            continue
        j = to_job(p, data)
        if not targeting.matches_role(j.title):
            skipped += 1
            print(f"   ↷ {j.title[:44]:<46}برّه تخصصك")
            continue
        jobs.append(j)
        print(f"   ✅ {j.title[:42]:<44}{(j.company_name or '')[:22]:<24}"
              f"{j.location or '—'}")

    jobs = dedupe(jobs)

    saved = []
    if jobs and not dry:
        saved = save(get_client(), jobs)

    print(f"\n📊 {len(posts)} منشور · {asked} اتسألوا · {len(jobs)} وظيفة"
          f" · {skipped} مستبعد · {len(saved)} جديدة")
    if dry:
        print("(--dry-run: مفيش حفظ)")
    return {"posts": len(posts), "jobs": len(jobs), "saved": len(saved)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="من غير حفظ")
    ap.add_argument("--limit", type=int, default=MAX_POSTS)
    a = ap.parse_args()

    r = run(dry=a.dry_run, limit=a.limit)
    if r.get("error"):
        print(f"❌ {r['error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
