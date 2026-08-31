"""
كومنتات LinkedIn.

  python -m src.comment              → اجمع منشورات واقترح كومنتات
  python -m src.comment --dry-run    → اعرض المقترحات من غير ما تبعتها
  python -m src.comment --post       → انشر اللي وافقت عليه
  python -m src.comment --stats      → معدل قبولك

الدورة:

    اجمع  →  اكتب  →  القواعد ترفض أو تعدّي  →  تليجرام  →  ضغطتك  →  انشر
                                                              ↓
                                                    بعد 6 ساعات: انتهت

الصلاحية مش تفصيلة: كومنت على منشور عمره يومين شكله آلي وواضح.
لو مردّيتش في الوقت، المقترح بيموت — أرخص من كومنت متأخر.

بيشتغل على جهازك: الجمع والنشر محتاجين جلسة LinkedIn.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from . import commenting, genai_pool, telegram
from .linkedin import feed, session
from .linkedin.session import Blocked
from .main import get_client

load_dotenv()

PER_RUN = int(os.getenv("COMMENT_PER_RUN", "4"))
DAILY = int(os.getenv("COMMENT_DAILY", "8"))
PACE = 1.5


# كام صفحة نشاط نفتح في المرة. كل صفحة ≈ 10 منشورات، والفلترة
# بتاكل معظمهم — 6 صفحات بتطلّع مقترحات كفاية من غير تصفّح مبالغ فيه.
SOURCES = 6


def sources(db) -> list[dict]:
    """
    مين نقرا منشوراتهم.

    الناس اللي بعتنالهم دعوة الأول: التعليق على منشور لواحد لسه
    ضايفينه سلوك طبيعي — والعكس (تعليق على غريب تمامًا) هو اللي
    شكله آلي.
    """
    rows = (db.table("contacts").select("profile_url,name,status,invited_at")
            .not_.is_("profile_url", "null")
            .order("invited_at", desc=True).limit(60).execute().data)

    rank = {"accepted": 0, "sent": 1}
    rows.sort(key=lambda r: rank.get(r.get("status"), 2))
    seen, out = set(), []
    for r in rows:
        u = (r["profile_url"] or "").split("?")[0].rstrip("/")
        if u and u not in seen:
            seen.add(u)
            out.append({"url": u, "name": r.get("name") or ""})
    return out[:SOURCES]



def _since(db, table: str, column: str, **kw) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()
    return len(db.table(table).select("id").not_.is_(column, "null")
               .gte(column, cutoff).execute().data)


def expire(db) -> int:
    """اللي عدت صلاحيته من غير قرار بيتقفل."""
    now = datetime.now(timezone.utc).isoformat()
    rows = db.table("comments").select("id") \
        .in_("status", ["proposed", "approved"]).lt("expires_at", now) \
        .execute().data
    for r in rows:
        try:
            db.table("comments").update({"status": "expired"}) \
                .eq("id", r["id"]).execute()
        except Exception:
            pass
    return len(rows)


def known_keys(db) -> set[str]:
    return {r["post_key"] for r in
            db.table("comments").select("post_key").execute().data}


# ── الاقتراح ────────────────────────────────────────────────────────────

def propose(db, limit: int) -> dict:
    from google import genai

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {"error": "مفيش GEMINI_API_KEY"}

    posted_today = _since(db, "comments", "posted_at", days=1)
    room = DAILY - posted_today
    if room <= 0:
        return {"error": f"الميزانية اليومية خلصت ({DAILY})"}

    seen = known_keys(db)
    client = genai_pool.client()
    made = rejected = 0
    out = []

    with session.browser(headless=False) as page:
        if not session.logged_in(page):
            return {"error": "مفيش جلسة LinkedIn"}
        try:
            posts = feed.collect(page, want=25, people=sources(db))
        except Blocked as b:
            return {"error": f"اعتراض: {b}"}

    fresh = [p for p in posts if p["post_key"] not in seen]
    print(f"📰 {len(posts)} منشور · {len(fresh)} جديد\n")

    for p in fresh:
        if made >= min(limit, room):
            break
        body, model, why = commenting.write(client, p)
        if not body:
            rejected += 1
            print(f"   ✗ {p['author'][:18]:<20}{why[:62]}")
            continue

        row = {
            "post_key": p["post_key"], "post_url": p["post_url"],
            "author": p["author"], "author_url": p["author_url"],
            "post_excerpt": p["text"][:400],
            "kind": p["kind"], "lang": p["lang"],
            "body": body, "words": commenting.word_count(body),
            "expires_at": (datetime.now(timezone.utc)
                           + timedelta(hours=commenting.TTL_HOURS)).isoformat(),
        }
        try:
            saved = db.table("comments").upsert(
                row, on_conflict="post_key").execute().data
            row["id"] = saved[0]["id"] if saved else None
            out.append(row)
            made += 1
            print(f"   ✅ {p['author'][:18]:<20}{body}")
        except Exception as exc:
            print(f"   (حفظ فشل — {type(exc).__name__}: {exc})"[:120])

    return {"proposed": made, "rejected": rejected, "items": out}


def send_for_approval(db, items: list[dict], token: str, chat: str) -> int:
    sent = 0
    for i, c in enumerate(items):
        icon = "🎉" if c["kind"] == "celebration" else "💬"
        text = (f"{icon} <b>{telegram.esc(c['author'])}</b>\n"
                f"<i>{telegram.esc(telegram.clip(c['post_excerpt'], 200))}</i>\n\n"
                f"💭 <b>{telegram.esc(c['body'])}</b>\n"
                f"<code>{c['words']} كلمة · تنتهي بعد "
                f"{commenting.TTL_HOURS:g} ساعات</code>")
        markup = {"inline_keyboard": [[
            {"text": "✅ انشر", "callback_data": f"ka:{c['id']}"},
            {"text": "❌ لأ", "callback_data": f"kr:{c['id']}"},
        ]]}
        try:
            mid = telegram.send_with_retry(text, token, chat, markup=markup)
            db.table("comments").update({"message_id": mid}) \
                .eq("id", c["id"]).execute()
            sent += 1
        except Exception as exc:
            print(f"   (إرسال فشل — {str(exc)[:70]})")
        if i < len(items) - 1:
            time.sleep(PACE)
    return sent


# ── النشر ───────────────────────────────────────────────────────────────

def post_approved(db, limit: int) -> dict:
    rows = db.table("comments").select("*").eq("status", "approved") \
        .gt("expires_at", datetime.now(timezone.utc).isoformat()) \
        .order("decided_at").limit(limit).execute().data
    if not rows:
        return {"posted": 0, "failed": 0}

    posted = failed = 0
    with session.browser(headless=False) as page:
        if not session.logged_in(page):
            return {"error": "مفيش جلسة"}
        for i, c in enumerate(rows):
            try:
                ok, why = feed.publish(page, c["post_url"], c["body"])
            except Blocked as b:
                print(f"🛑 {b}")
                break
            now = datetime.now(timezone.utc).isoformat()
            if ok:
                posted += 1
                db.table("comments").update(
                    {"status": "posted", "posted_at": now}).eq("id", c["id"]).execute()
                print(f"   ✅ {c['author'][:18]:<20}{c['body'][:44]}")
            else:
                failed += 1
                db.table("comments").update(
                    {"error": why[:300]}).eq("id", c["id"]).execute()
                print(f"   ✗ {c['author'][:18]:<20}{why[:50]}")
            if i < len(rows) - 1:
                session.human_pause(30, 80)
    return {"posted": posted, "failed": failed}


def show_stats(db) -> None:
    rows = db.table("comments").select("status,words,kind").execute().data
    if not rows:
        print("مفيش كومنتات لسه.")
        return
    import collections
    st = collections.Counter(r["status"] for r in rows)
    print(f"\nالكومنتات: {len(rows)}")
    for k in ("proposed", "approved", "posted", "rejected", "expired"):
        if st[k]:
            print(f"   {k:<10}{st[k]}")

    decided = st["posted"] + st["approved"] + st["rejected"]
    if decided:
        rate = (st["posted"] + st["approved"]) / decided * 100
        print(f"\n   معدل قبولك: {rate:.0f}%")
        if rate < 60:
            print("   ⚠️  أقل من 60% — الكومنتات مش كويسة كفاية.")
            print("      عدّل القواعد أو الـ prompt قبل ما تزوّد العدد.")
        elif decided >= 10:
            print("   الجودة مقبولة على العيّنة دي.")

    if st["expired"] > decided:
        print(f"\n   ⚠️  {st['expired']} انتهت من غير قرار — أكتر من اللي قررت فيه.")
        print("      يا إما الصلاحية قصيرة، يا إما العدد كتير عليك.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--limit", type=int, default=PER_RUN)
    args = ap.parse_args()

    db = get_client()

    if args.stats:
        show_stats(db)
        return 0

    gone = expire(db)
    if gone:
        print(f"⏳ {gone} مقترح انتهت صلاحيته")

    if args.post:
        r = post_approved(db, args.limit)
        if r.get("error"):
            print(f"❌ {r['error']}")
            return 1
        print(f"\n📊 اتنشر {r['posted']} · فشل {r['failed']}")
        return 0

    started = datetime.now(timezone.utc)
    result = propose(db, args.limit)
    if result.get("error"):
        print(f"❌ {result['error']}")
        return 1

    items = result.get("items", [])
    if args.dry_run:
        print(f"\n(--dry-run: {len(items)} مقترح، مفيش إرسال)")
        return 0

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    sent = send_for_approval(db, items, token, chat) if items else 0

    print(f"\n📊 اقترح {result['proposed']} · اترفض {result['rejected']} · "
          f"اتبعت {sent}")

    try:
        db.table("agent_runs").insert({
            "component": "comment",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok" if sent else "partial",
            "items_seen": result["proposed"] + result["rejected"],
            "items_new": sent,
            "detail": {"proposed": result["proposed"],
                       "rejected_by_rules": result["rejected"],
                       "expired": gone},
        }).execute()
    except Exception as exc:
        print(f"(تحذير: مقدرتش أسجّل التشغيلة — {exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
