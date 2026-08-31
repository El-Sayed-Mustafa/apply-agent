"""
متابعة الشركات والناشرين + تنبيهات البحث.

  python -m src.engage            → اعرض اللي هيتعمل (مفيش أي فعل)
  python -m src.engage --send     → نفّذ
  python -m src.engage --stats    → اللي اتعمل

الفكرة: لما وظيفة تعدّي حد التسليم، مش بس تتبعتلك — إحنا كمان
بنقرّبك من مصدرها. متابعة الشركة بتخلّي إعلاناتها الجاية تظهر
في الـfeed بتاعك، ومتابعة الناشر بتخلّي اسمك مألوف قبل ما تقدّم.

**الحد هو التقييم، مش الحماس.** مابنتابعش شركة وظيفتها جابت 40.
الفلترة هنا هي اللي بتفرق بين "اهتمام" و"سلوك آلي".

لينكدإن نفسه هو مرجع الحالة:

بنقرا الزرار الأول. لو مكتوب "Following" بنعدّي. الملف المحلي
كاش عشان نوفّر فتح صفحات — مش مصدر حقيقة. الفرق ده معناه إن
الملف لو اتمسح أو بقى قديم، أسوأ حاجة هتحصل إننا نفتح صفحة زيادة
ونلاقي إننا متابعين — مش إننا نتابع مرتين.

المتابعة فعل عام: بتظهر لصاحب الحساب، وأحيانًا لشبكته. عشان كده
`--send` مطلوبة صراحةً، وفي سقف يومي.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .linkedin import session
from .linkedin.session import BASE, Blocked
from .main import get_client

load_dotenv()

STATE = Path("state/engage.json")

# الحد اللي بيخلّي الوظيفة "حلوة": نفس حد التسليم على تليجرام.
# لو الوظيفة ماتستاهلش تشوفها، الشركة ماتستاهلش متابعة.
MIN_SCORE = int(os.getenv("ENGAGE_MIN_SCORE", "70"))

# سقوف يومية. المتابعة أخف من الدعوة بكتير، بس عشرين متابعة
# في الساعة سلوك بوت مهما كان الحد.
DAILY_COMPANIES = 8
DAILY_PEOPLE = 5
DAILY_ALERTS = 3

FOLLOW_BTN = ('button[aria-label^="Follow"]',
              'button[aria-label^="متابعة"]')

# الزرار بيتغير نصه لما تكون متابع بالفعل
ALREADY = re.compile(r"^(following|متابَع|إلغاء المتابعة|unfollow)", re.I)


# ── الحالة المحلية ──────────────────────────────────────────────────────

def load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"   ⚠ ملف الحالة مقروش: {exc}")
    return {"companies": {}, "people": {}, "alerts": {}}


def store(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def done_today(state: dict, kind: str) -> int:
    return sum(1 for v in state.get(kind, {}).values()
               if (v or "").startswith(_today()))


# ── اللي يستاهل ─────────────────────────────────────────────────────────

def targets(db) -> list[dict]:
    """
    الوظايف اللي عدّت الحد ووصلتك — دي بس اللي بنتحرّك ناحيتها.
    """
    scores = (db.table("scores").select("job_id,score_final")
              .gte("score_final", MIN_SCORE).execute().data)
    ids = [s["job_id"] for s in scores]
    if not ids:
        return []

    best = {}
    for s in scores:
        j = s["job_id"]
        if s["score_final"] > best.get(j, -1):
            best[j] = s["score_final"]

    out = []
    for i in range(0, len(ids), 100):
        rows = (db.table("jobs")
                .select("id,ats,company_name,title,url")
                .in_("id", ids[i:i + 100]).execute().data)
        for r in rows:
            r["score"] = best.get(r["id"], 0)
            out.append(r)

    out.sort(key=lambda r: -r["score"])
    return out


JS_COMPANY = r"""() => {
  const a = document.querySelector('main a[href*="/company/"]')
         || document.querySelector('a[href*="/company/"]');
  return a ? (a.getAttribute('href') || '') : '';
}"""


def company_slug(page, job_url: str) -> str:
    """افتح الإعلان وهات معرّف الشركة."""
    try:
        page.goto(job_url, wait_until="domcontentloaded", timeout=45_000)
    except Exception:
        return ""
    session.human_pause(4, 7)
    session.guard(page)
    try:
        href = page.evaluate(JS_COMPANY)
    except Exception:
        return ""
    m = re.search(r"/company/([^/?]+)", href or "")
    return m.group(1) if m else ""


# ── الأفعال ─────────────────────────────────────────────────────────────

def _follow_here(page) -> tuple[bool, str]:
    """
    اضغط متابعة على الصفحة المفتوحة.

    بنقرا الزرار الأول: لو مكتوب "Following" يبقى خلاص. الكشف
    ده هو اللي بيمنع إننا نضغط "إلغاء المتابعة" ونفك متابعة
    قديمة بالغلط.
    """
    for sel in FOLLOW_BTN:
        try:
            btn = page.query_selector(sel)
        except Exception:
            continue
        if not btn or not btn.is_visible():
            continue

        label = ((btn.get_attribute("aria-label") or "")
                 + " " + (btn.inner_text() or "")).strip()
        if ALREADY.search(label.strip()):
            return False, "متابع بالفعل"

        btn.click()
        session.human_pause(2, 4)
        session.guard(page)
        return True, ""

    return False, "مفيش زرار متابعة"


def follow_company(page, slug: str) -> tuple[bool, str]:
    try:
        page.goto(f"{BASE}/company/{slug}/", wait_until="domcontentloaded",
                  timeout=45_000)
    except Exception as exc:
        return False, str(exc)[:60]
    session.human_pause(4, 8)
    session.guard(page)
    return _follow_here(page)


def follow_person(page, profile_url: str) -> tuple[bool, str]:
    try:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=45_000)
    except Exception as exc:
        return False, str(exc)[:60]
    session.human_pause(4, 8)
    session.guard(page)
    return _follow_here(page)


def set_alert(page, keyword: str, location: str) -> tuple[bool, str]:
    """
    التنبيه في لينكدإن = حفظ البحث. الزرار اسمه "Save".
    """
    import urllib.parse
    url = (f"{BASE}/jobs/search/?keywords={urllib.parse.quote(keyword)}"
           f"&location={urllib.parse.quote(location)}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except Exception as exc:
        return False, str(exc)[:60]
    session.human_pause(5, 9)
    session.guard(page)

    for sel in ('button[aria-label*="alert" i]',
                'button[aria-label*="تنبيه"]',
                'button:has-text("Save")'):
        try:
            btn = page.query_selector(sel)
        except Exception:
            continue
        if not btn or not btn.is_visible():
            continue
        label = ((btn.get_attribute("aria-label") or "")
                 + " " + (btn.inner_text() or ""))
        if re.search(r"saved|محفوظ|إيقاف", label, re.I):
            return False, "التنبيه موجود"
        btn.click()
        session.human_pause(2, 4)
        session.guard(page)
        return True, ""

    return False, "مفيش زرار تنبيه"


# ── التشغيل ─────────────────────────────────────────────────────────────

def run(send: bool = False) -> dict:
    db = get_client()
    state = load()

    jobs = targets(db)
    if not jobs:
        return {"error": f"مفيش وظايف فوق {MIN_SCORE}"}

    room_c = DAILY_COMPANIES - done_today(state, "companies")
    room_p = DAILY_PEOPLE - done_today(state, "people")
    print(f"🎯 {len(jobs)} وظيفة فوق {MIN_SCORE}"
          f" · متاح النهاردة: {room_c} شركة، {room_p} شخص\n")

    # الشركة الواحدة مرة واحدة. من غير `picked`، شركة عندها تلات
    # وظايف عالية بتاخد تلات خانات من الثمانية — وبتتابع تلات مرات.
    plan, picked = [], set()
    for j in jobs:
        if len(plan) >= max(room_c, 0):
            break
        key = (j["company_name"] or "").strip().lower()
        if not key or key in state["companies"] or key in picked:
            continue
        picked.add(key)
        plan.append(j)

    for j in plan:
        print(f"   {j['score']:>3}  {(j['company_name'] or '—')[:26]:<28}"
              f"{j['title'][:44]}")

    if not send:
        print(f"\n(معاينة: {len(plan)} شركة. للتنفيذ: --send)")
        return {"planned": len(plan), "sent": 0}

    done = 0
    with session.browser(headless=False) as page:
        if not session.logged_in(page):
            return {"error": "مفيش جلسة LinkedIn"}
        try:
            for j in plan:
                slug = company_slug(page, j["url"]) if j.get("url") else ""
                if not slug:
                    print(f"   ✗ {j['company_name'][:24]:<26}مالقيتش صفحة الشركة")
                    continue
                ok, why = follow_company(page, slug)
                key = (j["company_name"] or "").strip().lower()
                state["companies"][key] = datetime.now(timezone.utc).isoformat()
                store(state)
                done += 1 if ok else 0
                print(f"   {'✅' if ok else '•'} {j['company_name'][:24]:<26}"
                      f"{slug[:24]:<26}{why}")
                session.human_pause(6, 12)
        except Blocked as b:
            store(state)
            return {"error": f"اعتراض: {b}", "sent": done}

    store(state)
    print(f"\n📊 اتابع {done} شركة")
    return {"planned": len(plan), "sent": done}


def show_stats() -> None:
    state = load()
    print(f"شركات متابَعة: {len(state.get('companies', {}))}")
    print(f"أشخاص متابَعين: {len(state.get('people', {}))}")
    print(f"تنبيهات: {len(state.get('alerts', {}))}")
    print(f"النهاردة: {done_today(state, 'companies')} شركة، "
          f"{done_today(state, 'people')} شخص")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="نفّذ فعلاً")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    if a.stats:
        show_stats()
        return 0

    r = run(send=a.send)
    if r.get("error"):
        print(f"❌ {r['error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
