"""
البحث عن مرشّحين — خريجين جدد عندهم scraping و SQL، القاهرة والجيزة.

  python -m src.hiring --dry-run   → اعرض بس
  python -m src.hiring             → اعرض وابعت القايمة على تليجرام
  python -m src.hiring --stats     → اللي اتجمع

الاتجاه معكوس هنا: باقي المنظومة بتدوّر على وظايف ليه، ودي بتدوّر
على ناس ليه. نفس الجلسة ونفس حارس الأمان ونفس الوتيرة البطيئة.

**قراءة بس.** مفيش دعوة ولا رسالة ولا أي فعل على حساب حد. القايمة
بتوصل تليجرام وهو اللي يقرر مين يستاهل — زي الكومنتات بالظبط.

وسنة التخرج مش في نتايج البحث:

لينكدإن مافيهوش فلتر لسنة التخرج في البحث المجاني، والبطاقة
مابتقولش. فبنقراها من الملف الشخصي — وده أغلى فعل هنا، فبيتعمل
للي عدّى الفلترة بس وبسقف. الترتيب: فلترة رخيصة الأول، وفتح
الصفحات في الآخر وعلى أقل عدد ممكن.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from . import telegram
from .linkedin import session
from .linkedin.session import BASE, Blocked

load_dotenv()

STATE = Path("state/candidates.json")

YEARS = (2024, 2025, 2026)

# كام ملف شخصي نفتح في التشغيلة. ده أغلى فعل وأكتره لفتًا للنظر،
# فبيتعمل للي عدّى الفلترة الرخيصة بس.
MAX_PROFILES = 10

QUERIES = [
    # ── المهارتين مع بعض ──
    "web scraping SQL fresh graduate Cairo",
    "python scraping SQL Egypt graduate",
    "data analyst scraping SQL Cairo",
    "selenium beautifulsoup SQL Egypt",
    "scraping automation SQL junior Cairo",
    "data engineer fresh graduate scraping Egypt",
    "scrapy python SQL Cairo",
    "web scraping data entry SQL Giza",

    # ── الأدوات بالاسم: أدق من الكلمة العامة ──
    "beautifulsoup pandas SQL Cairo graduate",
    "playwright scraping python Egypt junior",
    "selenium automation SQL Cairo entry level",

    # ── توصيف الخريج الجديد ──
    "fresh graduate python SQL Cairo",
    "junior data analyst python scraping Egypt",
    "computer science graduate scraping SQL Cairo",
    "ITI graduate python SQL scraping",
    "DEPI data python SQL Cairo",
]

# كام صفحة نتايج لكل بحث. لينكدإن بيعرض عشرة في الصفحة، والصفحة
# التانية غالبًا فيها الخريجين الجدد — الأولى بتبقى للأسماء
# الأشهر والأكتر متابعين.
PAGES = 2


# ── الإشارات ────────────────────────────────────────────────────────────

SCRAPING = re.compile(
    r"\b(scrap\w*|crawl\w*|selenium|beautiful\s?soup|bs4|playwright|puppeteer|"
    r"scrapy|data\s+extraction|web\s+harvest\w*)\b|كشط|استخراج البيانات", re.I)

SQL = re.compile(
    r"\b(sql|postgres\w*|mysql|sqlite|bigquery|snowflake|t-sql|pl/?sql|"
    r"database\w*|queries)\b|قواعد بيانات", re.I)

FRESH = re.compile(
    r"\b(fresh\s+grad\w*|new\s+grad\w*|graduat\w*|junior|entry[\s-]level|"
    r"student|intern|class\s+of|'2[456]\b)\b|خريج\w*|حديث التخرج", re.I)

# مؤشرات إن ده مش خريج جديد
SENIOR = re.compile(
    r"\b(senior|lead|principal|staff|head\s+of|manager|director|"
    r"\d{2}\+?\s*years?|expert)\b", re.I)

CAIRO = re.compile(
    r"\b(cairo|giza|egypt)\b|القاهرة|الجيزة|مصر", re.I)

# سطر الاسم في البطاقة بينتهي بدرجة الاتصال
NAME_LINE = re.compile(r"^(.{2,60}?)\s*[•·]\s*(1st|2nd|3rd\+?)\s*$", re.I)


JS_PEOPLE = r"""() => {
  const out = [], seen = new Set();
  document.querySelectorAll('li, div').forEach(e => {
    const a = e.querySelector('a[href*="/in/"]');
    if (!a) return;
    const url = (a.getAttribute('href') || '').split('?')[0];
    if (seen.has(url)) return;
    const lines = (e.innerText || '').split('\n')
      .map(x => x.trim()).filter(Boolean);
    if (lines.length < 3 || lines.length > 12) return;
    seen.add(url);
    out.push({url: url, lines: lines.slice(0, 8)});
  });
  return out.slice(0, 30);
}"""

# من غير قص: قسم التعليم بيجي بعد الخبرة، وملف فيه خبرات كتير
# بيعدّي 9000 حرف قبل ما يوصله. القص كان بيخفي السنة فالمرشّح
# بيتشال بصمت.
JS_PROFILE = r"""() => {
  const m = document.querySelector('main');
  return m ? (m.innerText || '') : '';
}"""


def parse(row: dict) -> dict | None:
    """
    البطاقة → مرشّح.

    البطاقة اللي جوّه بطاقة تانية (سطر "مشترك معك") بتطلع من غير
    سطر اسم — والسطر ده هو اللي بيفرّق بين نتيجة حقيقية وقصاصة.
    """
    lines = row["lines"]
    name = ""
    rest = []
    for x in lines:
        m = NAME_LINE.match(x)
        if m and not name:
            name = m.group(1).strip()
            continue
        rest.append(x)
    if not name:
        return None

    headline = rest[0] if rest else ""
    location = next((x for x in rest[1:3] if CAIRO.search(x) or "," in x), "")
    blurb = " ".join(rest)

    return {
        "url": row["url"],
        "name": name[:60],
        "headline": headline[:140],
        "location": location[:80],
        "blurb": blurb[:600],
    }


def looks_right(c: dict) -> tuple[bool, str]:
    """فلترة رخيصة قبل ما نفتح أي ملف شخصي."""
    text = f"{c['headline']} {c['blurb']}"
    if not CAIRO.search(f"{c['location']} {text}"):
        return False, "برّه القاهرة"
    if not SCRAPING.search(text):
        return False, "مفيش scraping"
    if not SQL.search(text):
        return False, "مفيش SQL"
    if SENIOR.search(c["headline"]):
        return False, "مش خريج جديد"
    return True, ""


# صفحة التعليم المخصّصة: /in/<slug>/details/education/
#
# الملف الشخصي الكامل مابينفعش: فيه منشورات الشخص ونشاطه (1026 سطر
# لواحد منهم)، فأي `max` على سنين الصفحة بيرجّع السنة الحالية.
# الصفحة دي فيها التعليم بس — 91 سطر، نضيفة.
EDU_URL = "/details/education/"

# "Oct 2024 – Aug 2028" أو "2024 – 2028" أو "2024 - Present"
RANGE = re.compile(
    r"(?:[A-Za-z]{3,9}\s+)?(\d{4})\s*[–—-]\s*"
    r"(?:(?:[A-Za-z]{3,9}\s+)?(\d{4})|(Present|Current|حتى الآن))", re.I)

# اللي بيفرّق بين شهادة جامعية وكورس أو معسكر تدريبي
DEGREE = re.compile(
    r"\b(bachelor|b\.?sc|b\.?a\b|licence|master|m\.?sc|degree|"
    r"universit\w*|faculty|college|institute of)\b|"
    r"بكالوريوس|ليسانس|ماجستير|جامع\w*|كلية", re.I)


def education_entries(text: str) -> list[dict]:
    """
    قسّم صفحة التعليم لمدخلات.

    المدخل بيبدأ باسم الجهة وبيحتوي على مدى تاريخ. بنجمع السطور
    حوالين كل مدى — التقسيم الدقيق مش مهم، المهم إن كل مدى يفضل
    مع النص اللي حواليه.
    """
    lines = [x.strip() for x in (text or "").split("\n") if x.strip()]
    out = []
    for i, line in enumerate(lines):
        m = RANGE.search(line)
        if not m:
            continue
        around = " ".join(lines[max(0, i - 3):i + 2])
        end = int(m.group(2)) if m.group(2) else None
        out.append({
            "start": int(m.group(1)),
            "end": end,               # None = لسه مستمر
            "text": around,
            "degree": bool(DEGREE.search(around)),
        })
    return out


def grad_year(text: str) -> int | None:
    """
    سنة التخرج = نهاية آخر **شهادة جامعية**.

    مش أكبر سنة في الصفحة: Ahmed Tayel عنده بكالوريوس
    2024–2028 ومعسكر DEPI 2025–2026. الـ`max` كان هيقول 2026
    وهو لسه طالب لحد 2028.

    ولا أصغر سنة: الواحد ممكن يكون عامل ماجستير بعد البكالوريوس.

    الكورسات والمعسكرات بتتشال — دي مش تخرّج.
    """
    entries = [e for e in education_entries(text) if e["degree"]]
    if not entries:
        entries = education_entries(text)
    ends = [e["end"] for e in entries if e["end"]]
    return max(ends) if ends else None


def same_person(url: str) -> str:
    """
    نفس الملف بيظهر بلاحقة لغة (`/en/`) فبيتسجّل مرتين.
    """
    u = (url or "").split("?")[0].rstrip("/")
    return re.sub(r"/(?:en|ar|fr|de|es)$", "", u)


# ── التجميع ─────────────────────────────────────────────────────────────

def collect(page, queries: list[str], want: int = 40) -> list[dict]:
    found: dict[str, dict] = {}

    for q in queries:
        if len(found) >= want:
            break
        for pg in range(1, PAGES + 1):
            url = (f"{BASE}/search/results/people/?keywords="
                   + urllib.parse.quote(q) + (f"&page={pg}" if pg > 1 else ""))
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            except Exception as exc:
                print(f"   ⚠ {q}: {exc}")
                continue

            session.human_pause(6, 10)
            session.guard(page)
            try:
                rows = page.evaluate(JS_PEOPLE)
            except Exception as exc:
                print(f"   ⚠ تعذّرت القراءة: {exc}")
                rows = []

            for r in rows:
                c = parse(r)
                if not c:
                    continue
                key = same_person(c["url"])
                if key not in found:
                    c["query"] = q
                    c["url"] = key
                    found[key] = c

            page.mouse.wheel(0, 1500)
            session.human_pause(3, 5)
            session.guard(page)

    return list(found.values())


def enrich(page, cands: list[dict], cap: int = MAX_PROFILES) -> list[dict]:
    """افتح ملفات المرشّحين المرشّحين وهات سنة التخرج."""
    out = []
    for c in cands[:cap]:
        try:
            page.goto(c["url"].rstrip("/") + EDU_URL,
                      wait_until="domcontentloaded", timeout=45_000)
        except Exception:
            out.append({**c, "grad": None})
            continue
        session.human_pause(5, 9)
        session.guard(page)

        page.mouse.wheel(0, 900)
        page.wait_for_timeout(1400)

        try:
            text = page.evaluate(JS_PROFILE)
        except Exception:
            text = ""
        out.append({**c, "grad": grad_year(text)})
        print(f"   {c['name'][:22]:<24}{str(out[-1]['grad'] or '—'):<8}"
              f"{c['headline'][:52]}")
    return out


# ── التخزين والتسليم ────────────────────────────────────────────────────

def load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"   ⚠ ملف المرشّحين مقروش: {exc}")
    return {}


def store(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def message(cands: list[dict]) -> str:
    esc = telegram.esc
    head = f"👤 <b>{len(cands)} مرشّح</b> — scraping + SQL · القاهرة\n"
    parts = [head]
    for c in cands:
        parts.append(
            f"\n<b>{esc(c['name'])}</b>"
            f"{' · ' + str(c['grad']) if c.get('grad') else ''}\n"
            f"{esc(c['headline'])}\n"
            f"{esc(c['location'])}\n"
            f"{esc(c['url'])}\n")
    return "".join(parts)[:3900]


def run(dry: bool = False, cap: int = MAX_PROFILES) -> dict:
    state = load()
    print(f"🔎 {len(QUERIES)} بحث\n")

    with session.browser(headless=False) as page:
        if not session.logged_in(page):
            return {"error": "مفيش جلسة LinkedIn"}
        try:
            raw = collect(page, QUERIES)
            print(f"👥 {len(raw)} نتيجة\n")

            keep, why = [], {}
            for c in raw:
                ok, reason = looks_right(c)
                if ok:
                    keep.append(c)
                else:
                    why[reason] = why.get(reason, 0) + 1

            for r, n in sorted(why.items(), key=lambda x: -x[1]):
                print(f"   ↷ {n:>3}  {r}")
            print(f"\n📋 {len(keep)} عدّوا الفلترة — بنقرا ملفاتهم\n")

            fresh = [c for c in keep if c["url"] not in state]
            enriched = enrich(page, fresh, cap)
        except Blocked as b:
            return {"error": f"اعتراض: {b}"}

    final = [c for c in enriched if c.get("grad") in YEARS]
    old = [c for c in enriched if c.get("grad") and c["grad"] not in YEARS]

    print(f"\n📊 {len(enriched)} اتقرا · {len(final)} في سنين التخرج"
          f" · {len(old)} برّه السنين")

    for c in enriched:
        state[c["url"]] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "name": c["name"], "grad": c.get("grad"),
            "headline": c["headline"], "location": c["location"],
            "match": c.get("grad") in YEARS,
        }
    if not dry:
        store(state)

    if final and not dry:
        telegram.send(message(final))
        print("   ✅ اتبعتوا على تليجرام")
    elif dry:
        print("\n(--dry-run: مفيش حفظ ولا إرسال)")
        for c in final:
            print(f"   {c['name'][:24]:<26}{c['grad']}  {c['url']}")

    return {"seen": len(raw), "kept": len(enriched), "matched": len(final)}


def show_stats() -> None:
    state = load()
    match = [v for v in state.values() if v.get("match")]
    print(f"مرشّحين اتقروا: {len(state)} · في السنين: {len(match)}\n")
    for v in sorted(match, key=lambda x: -(x.get("grad") or 0)):
        print(f"   {v['name'][:24]:<26}{v.get('grad') or '—':<8}"
              f"{v['headline'][:46]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cap", type=int, default=MAX_PROFILES)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    if a.stats:
        show_stats()
        return 0

    r = run(dry=a.dry_run, cap=a.cap)
    if r.get("error"):
        print(f"❌ {r['error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
