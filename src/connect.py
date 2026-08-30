"""
دعوات LinkedIn.

  python -m src.connect --login      → سجّل دخولك مرة واحدة
  python -m src.connect              → معاينة: مين هيتبعتله (من غير إرسال)
  python -m src.connect --send       → ابعت فعلاً، جوّه الميزانية
  python -m src.connect --stats      → الاستهلاك والحالة

بيشتغل على جهازك مش على GitHub — محتاج جلسة LinkedIn بتاعتك، وحطّ
جلسة زي دي على سيرفر معناه إن اللي يوصل للسيرفر يوصل لحسابك.

ثلاث ضمانات، كل واحدة في طبقة مختلفة:

  الداتابيز   قيد unique على الرابط — مستحيل يتبعت لنفس الشخص مرتين
  الكود       ميزانية أسبوعية ويومية بتتحسب من التاريخ الفعلي
  المتصفح     أي علامة اعتراض من LinkedIn → وقف فوري وقفل الجلسة

والافتراضي معاينة مش إرسال. الدعوة فعل ما بيترجعش، فالتشغيل الأول
لازم تشوفه بعينك.
"""
from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from .linkedin import people, session
from .linkedin.session import Blocked
from .main import get_client

load_dotenv()

# سقف LinkedIn الأسبوعي للحسابات المجانية حوالي 100. بنشتغل تحته
# بهامش واضح — الاقتراب من السقف نفسه بيرفع احتمال المراجعة.
WEEKLY_BUDGET = int(os.getenv("CONNECT_WEEKLY", "60"))
DAILY_BUDGET = int(os.getenv("CONNECT_DAILY", "12"))
PER_RUN = int(os.getenv("CONNECT_PER_RUN", "6"))
PAUSE_EVERY = 4          # وقفة أطول كل كام دعوة


def _since(db, **kw) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()
    return len(db.table("contacts").select("id")
               .not_.is_("invited_at", "null")
               .gte("invited_at", cutoff).execute().data)


def budget_left(db) -> tuple[int, int, int]:
    """(المتاح دلوقتي، الأسبوعي المتبقي، اليومي المتبقي)"""
    week = WEEKLY_BUDGET - _since(db, days=7)
    day = DAILY_BUDGET - _since(db, days=1)
    return max(0, min(week, day, PER_RUN)), max(0, week), max(0, day)


def known_keys(db) -> set[str]:
    return {r["profile_key"] for r in
            db.table("contacts").select("profile_key").execute().data}


def target_companies(db, limit: int = 6) -> list[dict]:
    """
    الشركات اللي ليها سلاج LinkedIn، الأولوية للـ tier الأقل.

    السلاج بيتحل مرة واحدة ويتخزن. من غيره الشركة بتتخطى — البحث عن
    اسم شركة بيستهلك من سقف البحث، وده أغلى من إننا نستنى.
    """
    rows = db.table("companies").select("name,linkedin_slug,tier") \
        .eq("status", "active").not_.is_("linkedin_slug", "null") \
        .order("tier").limit(limit).execute().data
    return rows


def gather(page, db, companies: list[dict], need: int) -> list[dict]:
    """اسحب مرشحين جداد من صفحات الشركات، مفلترين ومرتبين بالأولوية."""
    seen = known_keys(db)
    out: list[dict] = []

    for c in companies:
        if len(out) >= need * 3:      # نجمع أكتر من اللازم عشان نختار الأحسن
            break
        try:
            found = people.company_people(page, c["linkedin_slug"], want=25)
        except Blocked:
            raise
        except Exception as exc:
            print(f"   (تخطّينا {c['name']} — {type(exc).__name__})")
            continue

        for p in found:
            if p["profile_key"] in seen:
                continue
            kind = people.classify(p["headline"])
            if not kind:
                continue
            seen.add(p["profile_key"])
            out.append(p | {"company": c["name"], "kind": kind,
                            "source": f"company:{c['linkedin_slug']}"})

        session.human_pause(4, 9)

    out.sort(key=lambda p: people.PRIORITY.get(p["kind"], 9))
    return out


def record(db, p: dict, status: str, note: str = "") -> None:
    row = {"profile_key": p["profile_key"], "profile_url": p["profile_url"],
           "name": p.get("name"), "headline": p.get("headline"),
           "company": p.get("company"), "source": p.get("source"),
           "status": status, "note": note[:300] or None}
    if status == "pending":
        row["invited_at"] = datetime.now(timezone.utc).isoformat()
    try:
        db.table("contacts").upsert(row, on_conflict="profile_key").execute()
    except Exception as exc:
        print(f"   (تسجيل {p.get('name')} فشل — {type(exc).__name__}: {exc})"[:130])


def show_stats(db) -> None:
    rows = db.table("contacts").select("status,kind:headline,invited_at").execute().data
    allowed, week, day = budget_left(db)
    print(f"\nجهات الاتصال: {len(rows)}")
    for st in ("pending", "accepted", "failed", "skipped"):
        n = sum(1 for r in rows if r["status"] == st)
        if n:
            print(f"   {st:<10}{n}")
    print(f"\nالميزانية:")
    print(f"   الأسبوع  {WEEKLY_BUDGET - week}/{WEEKLY_BUDGET} مستهلك · "
          f"{week} متبقي")
    print(f"   اليوم    {DAILY_BUDGET - day}/{DAILY_BUDGET} مستهلك · "
          f"{day} متبقي")
    print(f"   التشغيلة دي تقدر تبعت {allowed}")

    pend = [r for r in rows if r["status"] == "pending"]
    acc = [r for r in rows if r["status"] == "accepted"]
    if pend or acc:
        rate = len(acc) / max(len(pend) + len(acc), 1) * 100
        print(f"\n   نسبة القبول: {rate:.0f}%  ({len(acc)} من "
              f"{len(pend) + len(acc)})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="تسجيل الدخول مرة واحدة")
    ap.add_argument("--send", action="store_true", help="ابعت فعلاً")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--limit", type=int, default=PER_RUN)
    args = ap.parse_args()

    if args.login:
        return 0 if session.login_flow() else 1

    db = get_client()

    if args.stats:
        show_stats(db)
        return 0

    allowed, week, day = budget_left(db)
    allowed = min(allowed, args.limit)
    if allowed <= 0:
        print(f"الميزانية خلصت — الأسبوع {week} متبقي · اليوم {day} متبقي")
        return 0

    companies = target_companies(db)
    if not companies:
        print("مفيش شركات ليها سلاج LinkedIn.")
        print("ضيف linkedin_slug في جدول companies — الجزء اللي في")
        print("linkedin.com/company/<slug>/")
        return 0

    print(f"🔗 الميزانية: {allowed} دعوة · الأسبوع {week} · اليوم {day}")
    print(f"   الشركات: {', '.join(c['name'] for c in companies)}\n")

    started = datetime.now(timezone.utc)
    sent = failed = 0
    blocked = ""

    with session.browser(headless=False) as page:
        if not session.logged_in(page):
            print("❌ مفيش جلسة. شغّل: python -m src.connect --login")
            return 1

        try:
            candidates = gather(page, db, companies, allowed)
        except Blocked as b:
            print(f"\n🛑 {b}\n   وقفنا. ماتشغّلش تاني النهاردة.")
            return 1

        if not candidates:
            print("مفيش مرشحين جداد.")
            return 0

        print(f"👥 {len(candidates)} مرشح جديد\n")
        picks = candidates[:allowed]

        for i, p in enumerate(picks, 1):
            tag = {"recruiter": "🎯", "leader": "⭐", "peer": "👤"}[p["kind"]]
            label = f"{tag} {(p['name'] or '?')[:24]:<26}{(p['headline'] or '')[:42]}"

            if not args.send:
                print(f"   {label}")
                continue

            try:
                ok, why = people.invite(page, p)
            except Blocked as b:
                blocked = str(b)
                print(f"\n🛑 {b}")
                print("   وقفنا في النص. اللي اتبعت اتسجّل.")
                break

            if ok:
                sent += 1
                record(db, p, "pending")
                print(f"   ✅ {label}")
            else:
                failed += 1
                record(db, p, "skipped", why)
                print(f"   ·  {label}  ({why})")

            if i < len(picks):
                session.human_pause(25, 70)
                if i % PAUSE_EVERY == 0:
                    print("   (وقفة)")
                    session.long_pause()

    if not args.send:
        print(f"\n(معاينة — مفيش إرسال. ضيف --send لما تكون جاهز)")
        return 0

    print(f"\n📊 اتبعت {sent} · اتخطى {failed}")

    try:
        db.table("agent_runs").insert({
            "component": "connect",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed" if blocked else ("partial" if failed else "ok"),
            "items_seen": len(picks),
            "items_new": sent,
            "detail": {"sent": sent, "skipped": failed, "blocked": blocked,
                       "week_left": week - sent, "day_left": day - sent},
        }).execute()
    except Exception as exc:
        print(f"(تحذير: مقدرتش أسجّل التشغيلة — {exc})")

    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
