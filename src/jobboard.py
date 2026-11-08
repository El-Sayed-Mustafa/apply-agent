"""
لوحة وظايف لينكدإن — الخليج ومصر.

  python -m src.jobboard --dry-run   → دوّر واعرض من غير حفظ
  python -m src.jobboard             → دوّر واحفظ الجديد

ليه المصدر ده موجود:

القياس على 10,707 وظيفة قال إن منشورات لينكدإن أعلى مصدر عائدًا
(23.5% مؤهلة) مقابل 5.5% لـGreenhouse. السبب مش إن لينكدإن أذكى —
السبب إن **وظايف الخليج ومصر بتتنشر هنا مش على ATS أمريكاني**.
كنا بنشرب من الحنفية الغلط.

واللوحة أوضح من المنشورات: الكارت نفسه فيه المسمى والشركة والموقع
منظّمين. يعني **صفر توكنز** — مفيش موديل بيقرا حاجة هنا. الاستخراج
من الـDOM مباشرة، والتوكنز بتفضل كلها للتقييم.

عن المخاطرة، بصراحة:

اللوحة أكتر سطح مراقب في لينكدإن. إحنا بالفعل بنشغّل الجلسة
المسجّلة (دعوات، منشورات، بحث)، فالخط ده متعدّي قبل كده — بس
التركيز بيزيد. عشان كده:

  · عدد صغير لكل بحث، ووقفات بشرية بين كل حاجة
  · حارس الأمان بيتنده بعد كل تنقّل — أي تحذير بيوقف كل حاجة
  · قراءة بس. مفيش تقديم ولا ضغط على "Easy Apply" أبدًا
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from . import runlog, targeting
from .adapters import Job
from .linkedin import session
from .linkedin.session import Blocked
from .main import get_client, reachable, save

load_dotenv()

CFG = "targeting.yaml"
BASE = "https://www.linkedin.com"

# كام كارت نقرا من كل (كلمة × مكان). قراءة الكروت مبتفتحش أي صفحة —
# الكروت كلها في صفحة البحث نفسها — فالعدد هنا مش هو اللي بيكلّف
# الحساب؛ اللي بيكلّف هو فتح صفحات الوصف، وده محكوم بـ MAX_DESCRIBE.
#
# كان 6، وده كان أكبر سبب إن وظايف مناسبة مبتوصلش: "AI Engineer" في
# السعودية في أسبوع = 34 نتيجة، وإحنا كنا بناخد أول 6.
# 25 = الصفحة الأولى كاملة.
PER_SEARCH = 25

# سقف الأوصاف في التشغيلة الواحدة. فتح صفحة وصف هو أغلى فعل
# وأكتره لفتًا للنظر — مش بنزوّده. الزيادة بتستنى في الطابور.
MAX_DESCRIBE = 12

# الكروت المناسبة اللي ملحقناش نفتح وصفها. من غير الطابور كانت
# بتضيع: بكرة شريحة أبحاث تانية، والبحث ده مبيرجعش غير بعد كام يوم
# وساعتها تكون نزلت من أول الصفحة. بتتشال بعد أسبوع (نفس مدى البحث).
QUEUE = Path("state/jobboard_queue.json")
QUEUE_DAYS = 7

# كام بحث في التشغيلة الواحدة. 5 كلمات × 5 أماكن = 25 بحث كل
# يوم، وده لوحده — قبل الأوصاف — نشاط أكبر من أي بني آدم.
#
# بنلف على الشبكة بدل ما نمشيها كلها: كل يوم بياخد شريحة
# مختلفة، فالتغطية بتكتمل على مدار الأسبوع والتشغيلة الواحدة
# تفضل صغيرة.
SEARCHES_PER_RUN = 8

# الأسبوع الأخير بس — إعلان عمره شهر الأغلب اتقفل
RECENT = "r604800"


# ── الكروت ──────────────────────────────────────────────────────────────

# الكلاسات مشفّرة، بس `data-occludable-job-id` ثابت — ده اللي
# لينكدإن بيستخدمه هو نفسه عشان يعرف أنهي كارت ظاهر.
JS_CARDS = r"""() => {
  const out = [];
  document.querySelectorAll('[data-occludable-job-id]').forEach(e => {
    const a = e.querySelector('a[href*="/jobs/view/"]');
    if (!a) return;
    const lines = (e.innerText || '').split('\n')
      .map(x => x.trim()).filter(Boolean);
    out.push({
      id: e.getAttribute('data-occludable-job-id'),
      href: (a.getAttribute('href') || '').split('?')[0],
      lines: lines.slice(0, 8)
    });
  });
  return out;
}"""

JS_DESC = r"""() => {
  const m = document.querySelector('main');
  return m ? (m.innerText || '').trim() : '';
}"""

# لينكدإن بيرسم الكروت اللي قدام العين بس — الباقي بيبقى غلاف فاضي
# لحد ما يتشاف. فبنعدّي على كل كارت عشان يترسم قبل ما نقراه.
# دي تمريرة في صفحة مفتوحة، مش فتح صفحات.
JS_RENDER = r"""async () => {
  const els = [...document.querySelectorAll('[data-occludable-job-id]')];
  for (const e of els) {
    e.scrollIntoView({block: 'center'});
    await new Promise(r => setTimeout(r, 250 + Math.random() * 350));
  }
  return els.length;
}"""

# سطور بتتكرر في كل كارت ومالهاش معنى
CARD_NOISE = re.compile(
    r"^(viewed|easy apply|promoted|actively (?:hiring|reviewing)|"
    r"be an early applicant|\d+\s*(?:hours?|days?|weeks?|months?)\s*ago|"
    r"within the past.*|جديد|تم العرض|التقديم السهل|تمت المشاهدة)$", re.I)

# الموقع بينتهي بنوع العمل بين قوسين
WORK_TYPE = re.compile(r"\((remote|hybrid|on-?site|عن بعد|هجين|في الموقع)\)", re.I)


def parse_card(card: dict) -> dict | None:
    """
    الكارت → مسمى وشركة وموقع.

    الشكل: المسمى بيتكرر مرتين (التانية للقارئ الصوتي)، وبعديها
    الشركة، وبعديها الموقع ونوع العمل بين قوسين.
    """
    lines = [x for x in card["lines"] if not CARD_NOISE.match(x)]
    if len(lines) < 2:
        return None

    title = lines[0]
    rest = [x for x in lines[1:] if x != title and not x.startswith(title)]
    if not rest:
        return None

    # الموقع هو أول سطر فيه نوع عمل أو فاصلة؛ اللي قبله الشركة
    loc_i = next((i for i, x in enumerate(rest)
                  if WORK_TYPE.search(x) or "," in x), None)
    if loc_i is None:
        company, location = rest[0], ""
    elif loc_i == 0:
        # مفيش شركة مكتوبة — بيحصل في إعلانات المجمّعات
        company, location = "", rest[0]
    else:
        company, location = rest[loc_i - 1], rest[loc_i]

    m = WORK_TYPE.search(location)
    remote = "unknown"
    if m:
        w = m.group(1).lower()
        remote = ("remote" if w in ("remote", "عن بعد") else
                  "hybrid" if w in ("hybrid", "هجين") else "onsite")
        location = WORK_TYPE.sub("", location).strip()

    return {
        "id": card["id"],
        "url": f"{BASE}/jobs/view/{card['id']}/",
        "title": title[:160],
        "company": company[:120],
        "location": location[:120],
        "remote_type": remote,
    }


# ── الوصف ───────────────────────────────────────────────────────────────

# اللي بعد دول توصيات ووظايف شبيهة، مش الإعلان
TAIL = re.compile(
    r"(people also viewed|similar jobs|more jobs|explore collaborative|"
    r"set alert|وظائف مشابهة|أشخاص شاهدوا أيضًا)", re.I)


def clean_desc(raw: str, title: str) -> str:
    """
    قصّ نص الصفحة على الإعلان.

    الكلاسات مشفّرة فمافيش عنصر نقدر نمسك الوصف منه مباشرة.
    بناخد نص `main` وبنقصّه: من أول ما المسمى يظهر، لحد أول
    قسم توصيات.
    """
    text = re.sub(r"\n{3,}", "\n\n", raw or "").strip()

    i = text.find(title)
    if i > 0:
        text = text[i:]

    m = TAIL.search(text)
    if m and m.start() > 400:
        text = text[:m.start()]

    return re.sub(r"[ \t]+", " ", text).strip()[:8000]


# ── البحث ───────────────────────────────────────────────────────────────

def config() -> tuple[list[str], list[str]]:
    cfg = (yaml.safe_load(open(CFG, encoding="utf-8")) or {}).get("job_board") or {}
    return cfg.get("keywords") or [], cfg.get("locations") or []


def search(page, keyword: str, location: str, want: int = PER_SEARCH) -> list[dict]:
    """كروت بحث واحد."""
    import urllib.parse
    url = (f"{BASE}/jobs/search/?keywords={urllib.parse.quote(keyword)}"
           f"&location={urllib.parse.quote(location)}&f_TPR={RECENT}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except Exception as exc:
        print(f"   ⚠ {keyword} / {location}: {exc}")
        return []

    session.human_pause(6, 10)
    session.guard(page)

    try:
        page.evaluate(JS_RENDER)
        session.human_pause(1.5, 3)
        session.guard(page)
        cards = page.evaluate(JS_CARDS)
    except Blocked:
        raise
    except Exception as exc:
        print(f"   ⚠ تعذّرت قراءة الكروت: {exc}")
        cards = []

    out = []
    for c in cards:
        p = parse_card(c)
        if p and not any(x["id"] == p["id"] for x in out):
            out.append(p)
    return out[:want]


def priority(card: dict) -> int:
    """الأقرب للهدف الأول: ريموت والمستوى الأول، وبعدين 2 و3."""
    if card.get("remote_type") == "remote":
        return 0
    _, tier = targeting.detect_country(card.get("location"))
    return {1: 0, 2: 1, 3: 2}.get(tier, 3)


def load_queue() -> dict[str, dict]:
    """الطابور من غير اللي عدّى عليه أسبوع."""
    try:
        q = json.loads(QUEUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cutoff = datetime.now(timezone.utc).timestamp() - QUEUE_DAYS * 86400
    return {k: v for k, v in q.items()
            if datetime.fromisoformat(v["queued_at"]).timestamp() >= cutoff}


def save_queue(q: dict[str, dict]) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=1),
                     encoding="utf-8")


def pick(cards: dict[str, dict], queue: dict[str, dict], known: set[str],
         limit: int = MAX_DESCRIBE) -> tuple[list[dict], dict[str, dict]]:
    """
    أنهي كروت نفتح وصفها النهاردة، وإيه اللي يفضل في الطابور.

    الطابور والجديد في كومة واحدة، مترتبين بالأولوية — وجوّا نفس
    الأولوية الأقدم في الطابور الأول، عشان محدش يستنى للأبد.
    """
    now = datetime.now(timezone.utc).isoformat()
    pool = {k: v for k, v in queue.items() if k not in known}
    for k, c in cards.items():
        if k not in known and k not in pool:
            pool[k] = {**c, "queued_at": now}
    order = sorted(pool.values(), key=lambda c: (priority(c), c["queued_at"]))
    todo = order[:limit]
    rest = {c["id"]: c for c in order[limit:]}
    return todo, rest


def describe(page, card: dict) -> str:
    """افتح صفحة الوظيفة وهات الوصف."""
    try:
        page.goto(card["url"], wait_until="domcontentloaded", timeout=45_000)
    except Exception:
        return ""
    session.human_pause(4, 8)
    session.guard(page)
    try:
        return clean_desc(page.evaluate(JS_DESC), card["title"])
    except Exception:
        return ""


def to_job(card: dict, desc: str) -> Job:
    return Job(
        company_name=card["company"] or "لينكدإن",
        ats="linkedin_job",
        external_id=card["id"],
        title=card["title"],
        location=card["location"] or None,
        remote_type=card["remote_type"],
        description=desc,
        url=card["url"],
    )


# ── التشغيل ─────────────────────────────────────────────────────────────

def run(dry: bool = False, per_search: int = PER_SEARCH) -> dict:
    keywords, locations = config()
    if not keywords or not locations:
        return {"error": f"مفيش job_board.keywords/locations في {CFG}"}

    pairs = [(k, l) for l in locations for k in keywords]
    total = len(pairs)

    # الشريحة بتتحدد باليوم: نفس اليوم = نفس الشريحة، فإعادة
    # التشغيل مابتزوّدش النشاط. ويوم بعده = شريحة بعدها، فالتغطية
    # بتكتمل على مدار الأسبوع من غير ما التشغيلة الواحدة تكبر.
    day = datetime.now(timezone.utc).toordinal()
    start = (day * SEARCHES_PER_RUN) % max(total, 1)
    pairs = (pairs + pairs)[start:start + SEARCHES_PER_RUN]

    print(f"🔎 {len(pairs)} بحث من {total} (شريحة النهاردة)\n")

    down = reachable()
    if down:
        return {"error": f"{down} — ما فتحناش لينكدإن"}

    cards: dict[str, dict] = {}
    jobs: list[Job] = []

    with session.browser(headless=False) as page:
        if not session.logged_in(page):
            return {"error": "مفيش جلسة LinkedIn"}

        try:
            for kw, loc in pairs:
                got = search(page, kw, loc, per_search)
                fresh = [c for c in got if c["id"] not in cards]
                for c in fresh:
                    cards[c["id"]] = c
                print(f"   {loc:<16}{kw[:26]:<28}{len(got):>3} كارت"
                      f" · {len(fresh)} جديد")

            # الفلترة **قبل** فتح أي صفحة وصف: الدور، وريموت أو دولة في
            # القايمة. نفس الشرط اللازم اللي المقيّم بيطبّقه بعدين — فاللي
            # بيقع هنا كان هيترفض برضه، بس بعد ما فتحنا صفحته على الحساب.
            #
            # بحث لينكدإن فضفاض: "AI Engineer" في السعودية بيرجّع
            # "Junior Game Designer" و"German speaking Customer
            # support". اتقاس: 73% من اللي دخل مش مطابق للدور.
            off = [c for c in cards.values()
                   if not targeting.could_pass(c["title"], c["location"],
                                               c["remote_type"])]
            for c in off:
                del cards[c["id"]]
            if off:
                print(f"\n   ({len(off)} برّه تخصصك أو مكانك — مافتحناش صفحاتهم)")

            known = seen_ids(get_client())
            queue = load_queue()
            todo, rest = pick(cards, queue, known)
            skipped = sum(1 for k in cards if k in known)
            if skipped:
                print(f"   ({skipped} متسجّلة قبل كده — بنعدّيها)")
            if rest:
                print(f"   ({len(rest)} مستنية في الطابور للتشغيلة الجاية)")
            # اللي هنفتحه النهاردة بيفضل في الطابور لحد ما يتحفظ فعلًا —
            # لو التشغيلة وقعت في النص، مايضيعش.
            if not dry:
                save_queue({**rest, **{c["id"]: c for c in todo}})
            print(f"\n📄 {len(todo)} وظيفة — بنقرا الأوصاف\n")

            for c in todo:
                desc = describe(page, c)
                jobs.append(to_job(c, desc))
                print(f"   {c['title'][:40]:<42}{c['company'][:20]:<22}"
                      f"{c['location'][:22]:<24}{len(desc):>5} حرف")
        except Blocked as b:
            return {"error": f"اعتراض: {b}"}

    saved = []
    if not dry:
        if jobs:
            saved = save(get_client(), jobs)
        save_queue(rest)

    print(f"\n📊 {len(cards)} كارت · {len(jobs)} اتقرا · {len(saved)} جديدة")
    if dry:
        print("(--dry-run: مفيش حفظ)")
    return {"cards": len(cards), "read": len(jobs), "saved": len(saved)}


def seen_ids(db) -> set[str]:
    """
    أرقام الوظايف المسجّلة قبل كده.

    فتح صفحة وصف هو أغلى حاجة في التشغيلة وأكترها لفتًا للنظر.
    وظيفة شفناها امبارح مالهاش لازمة تتفتح تاني.
    """
    out, off = set(), 0
    while True:
        rows = (db.table("jobs").select("external_id")
                .eq("ats", "linkedin_job").range(off, off + 999).execute().data)
        out |= {r["external_id"] for r in rows}
        if len(rows) < 1000:
            return out
        off += 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="من غير حفظ")
    ap.add_argument("--per-search", type=int, default=PER_SEARCH)
    a = ap.parse_args()

    started = datetime.now(timezone.utc)
    r = run(dry=a.dry_run, per_search=a.per_search)
    if not a.dry_run:
        runlog.log("jobboard", started, r, r.get("cards"), r.get("saved"))
    if r.get("error"):
        print(f"❌ {r['error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
