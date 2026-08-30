"""
متابعة التقديمات.

  python -m src.followup            → اسأل عن اللي فات عليه ساعة
  python -m src.followup --dry-run  → اعرض من غير إرسال
  python -m src.followup --stats    → نسبة التأكيد

ليه موجود أصلاً:

جدول applications هو الحقيقة الأرضية اللي كل قياس في المشروع مبني
عليها. ضغطة ✅ معناها "نويت أقدّم" — مش "قدّمت". استمارات الـ ATS
فيها كابتشا وحقول طويلة، وناس كتير بتبدأ وماتكملش.

لو خلطنا الاتنين، كل قياس عن دقة التقييم هيبقى مبني على تسميات غلط،
وهنستنتج إن المقيّم وحش وهو كويس — أو العكس، وده أسوأ.

السؤال بيتبعت **بعد ساعة**: كفاية إنك خلصت أو استسلمت، وقريّب كفاية
إنك لسه فاكر.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from . import telegram
from .main import get_client

load_dotenv()

AFTER_HOURS = float(os.getenv("FOLLOWUP_AFTER_HOURS", "1"))
MAX_PER_RUN = int(os.getenv("FOLLOWUP_MAX", "5"))
PACE = 1.5


def pending(db, limit: int) -> list[dict]:
    """
    تقديمات دُست ✅ وعدت عليها المهلة ولسه ماتسألناش عنها.

    asked_at بيمنع السؤال مرتين. من غيره، أي تقديم مش متأكد هيتسأل
    عنه كل ساعة للأبد.
    """
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=AFTER_HOURS)).isoformat()

    rows = db.table("applications") \
        .select("job_id,decided_at") \
        .eq("status", "applied").is_("confirmed", "null").is_("asked_at", "null") \
        .lt("decided_at", cutoff) \
        .order("decided_at").limit(limit).execute().data
    if not rows:
        return []

    jobs = {j["id"]: j for j in db.table("jobs")
            .select("id,company_name,title,url")
            .in_("id", [r["job_id"] for r in rows]).execute().data}

    return [{"job": jobs[r["job_id"]], "app": r}
            for r in rows if r["job_id"] in jobs]


def ask(db, items: list[dict], token: str, chat_id: str) -> dict:
    sent = failed = 0
    for i, item in enumerate(items):
        job = item["job"]
        text = (f"❓ <b>{telegram.esc(job['company_name'])}</b>\n"
                f"{telegram.esc(telegram.clip(job['title'], 80))}\n\n"
                "خلّصت تقديم عليها فعلاً؟")
        markup = {"inline_keyboard": [[
            {"text": "✅ آه، قدّمت", "callback_data": f"c:{job['id']}"},
            {"text": "❌ لأ، مكمّلتش", "callback_data": f"n:{job['id']}"},
        ]]}
        try:
            telegram.send_with_retry(text, token, chat_id, markup=markup)
            sent += 1
            print(f"   ❓ {job['company_name'][:16]:<18}{job['title'][:44]}")
        except Exception as exc:
            failed += 1
            print(f"   ❌ {job['title'][:40]} — {str(exc)[:70]}")

        # asked_at بيتسجّل حتى لو الإرسال فشل — عشان مانلفّش على نفس
        # الوظيفة كل ساعة. لو الإرسال بايظ، الفشل هيبان في agent_runs.
        try:
            db.table("applications").update(
                {"asked_at": datetime.now(timezone.utc).isoformat()}
            ).eq("job_id", job["id"]).execute()
        except Exception as exc:
            print(f"   (تسجيل السؤال فشل — {exc})"[:120])

        if i < len(items) - 1:
            time.sleep(PACE)

    return {"asked": sent, "failed": failed}


def show_stats(db) -> None:
    rows = db.table("applications").select("status,confirmed,asked_at").execute().data
    applied = [r for r in rows if r["status"] == "applied"]
    asked = [r for r in applied if r["asked_at"]]
    yes = [r for r in applied if r["confirmed"] is True]
    no = [r for r in applied if r["confirmed"] is False]
    waiting = [r for r in asked if r["confirmed"] is None]

    print(f"\nالقرارات: {len(rows)}")
    for st in ("applied", "skipped", "later"):
        n = sum(1 for r in rows if r["status"] == st)
        print(f"   {st:<9}{n}")

    print(f"\nمن {len(applied)} ضغطة ✅:")
    print(f"   اتسأل عنهم      {len(asked)}")
    print(f"   أكّد إنه قدّم    {len(yes)}")
    print(f"   قال مكمّلش      {len(no)}")
    print(f"   لسه ماردّش      {len(waiting)}")

    if yes or no:
        rate = len(yes) / (len(yes) + len(no)) * 100
        print(f"\n   نسبة التأكيد: {rate:.0f}%")
        if rate < 70:
            print("   ⚠️  أقل من 70% — يعني الضغطة مش دليل تقديم.")
            print("      أي قياس على 'applied' من غير confirmed هيبقى غلط.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--limit", type=int, default=MAX_PER_RUN)
    args = ap.parse_args()

    db = get_client()

    if args.stats:
        show_stats(db)
        return 0

    items = pending(db, args.limit)
    if not items:
        print("مفيش تقديمات محتاجة تأكيد.")
        return 0

    print(f"❓ {len(items)} تقديم فات عليه {AFTER_HOURS:g} ساعة\n")

    if args.dry_run:
        for it in items:
            print(f"   {it['job']['company_name'][:16]:<18}{it['job']['title'][:50]}")
        print("\n(--dry-run: مفيش إرسال)")
        return 0

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("❌ ناقص إعدادات تليجرام")
        return 1

    started = datetime.now(timezone.utc)
    result = ask(db, items, token, chat)
    print(f"\n📊 اتسأل {result['asked']} · فشل {result['failed']}")

    try:
        db.table("agent_runs").insert({
            "component": "followup",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed" if (result["failed"] and not result["asked"])
                      else ("partial" if result["failed"] else "ok"),
            "items_seen": len(items),
            "items_new": result["asked"],
            "detail": result,
        }).execute()
    except Exception as exc:
        print(f"(تحذير: مقدرتش أسجّل التشغيلة — {exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
