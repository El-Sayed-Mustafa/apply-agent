"""
متابعة التقديمات — على مرحلتين.

  python -m src.followup            → شغّل المرحلتين
  python -m src.followup --dry-run  → اعرض من غير إرسال
  python -m src.followup --stats    → الحقيقة الأرضية لحد دلوقتي

المرحلة 1 · بعد ساعة   "خلّصت تقديم فعلاً؟"
المرحلة 2 · بعد 7 أيام  "فيه رد؟"
الإغلاق  · بعد 21 يوم  الصمت بيتسجّل "مفيش رد" لوحده

ليه المرحلتين مختلفتين:

  ضغطة ✅         = نويت أقدّم
  confirmed = true = قدّمت فعلاً
  outcome          = حصل إيه بعدها

من غير الأولى، بنقيس "التقييم بيتوقع إنه هيدوس زرار".
من غير التانية، بنقيس "التقييم بيتوقع إنه هيقدّم".
باللي الاتنين، بنقيس "التقييم بيتوقع إنه هيتقبل" — وهي دي اللي بتهم.

والإغلاق التلقائي مقصود: لو استنينا ضغطة زرار على كل تقديم مالوش رد،
نص العيّنة هيفضل فاضي للأبد. الصمت بعد 3 أسابيع **هو** الإجابة.
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

CONFIRM_AFTER_HOURS = float(os.getenv("FOLLOWUP_CONFIRM_HOURS", "1"))
OUTCOME_AFTER_DAYS = float(os.getenv("FOLLOWUP_OUTCOME_DAYS", "7"))
AUTO_CLOSE_DAYS = float(os.getenv("FOLLOWUP_CLOSE_DAYS", "21"))
MAX_PER_RUN = int(os.getenv("FOLLOWUP_MAX", "5"))
PACE = 1.5

OUTCOME_KEYS = {
    "or": "reply", "oi": "interview", "of": "offer",
    "oj": "rejected", "on": "none",
}


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def _jobs(db, ids: list[int]) -> dict:
    if not ids:
        return {}
    return {j["id"]: j for j in db.table("jobs")
            .select("id,company_name,title,url").in_("id", ids).execute().data}


# ── المرحلة 1: تأكيد التقديم ────────────────────────────────────────────

def pending_confirm(db, limit: int) -> list[dict]:
    rows = db.table("applications") \
        .select("job_id,decided_at") \
        .eq("status", "applied").is_("confirmed", "null").is_("asked_at", "null") \
        .lt("decided_at", _ago(hours=CONFIRM_AFTER_HOURS)) \
        .order("decided_at").limit(limit).execute().data
    jobs = _jobs(db, [r["job_id"] for r in rows])
    return [{"job": jobs[r["job_id"]]} for r in rows if r["job_id"] in jobs]


def confirm_message(job: dict) -> tuple[str, dict]:
    text = (f"❓ <b>{telegram.esc(job['company_name'])}</b>\n"
            f"{telegram.esc(telegram.clip(job['title'], 80))}\n\n"
            "خلّصت تقديم عليها فعلاً؟")
    markup = {"inline_keyboard": [[
        {"text": "✅ آه، قدّمت", "callback_data": f"c:{job['id']}"},
        {"text": "❌ لأ، مكمّلتش", "callback_data": f"n:{job['id']}"},
    ]]}
    return text, markup


# ── المرحلة 2: النتيجة ──────────────────────────────────────────────────

def pending_outcome(db, limit: int) -> list[dict]:
    rows = db.table("applications") \
        .select("job_id,decided_at") \
        .eq("confirmed", True).is_("outcome", "null") \
        .is_("outcome_asked_at", "null") \
        .lt("decided_at", _ago(days=OUTCOME_AFTER_DAYS)) \
        .order("decided_at").limit(limit).execute().data
    jobs = _jobs(db, [r["job_id"] for r in rows])
    return [{"job": jobs[r["job_id"]], "since": r["decided_at"]}
            for r in rows if r["job_id"] in jobs]


def outcome_message(job: dict, days: int) -> tuple[str, dict]:
    text = (f"📮 <b>{telegram.esc(job['company_name'])}</b>\n"
            f"{telegram.esc(telegram.clip(job['title'], 80))}\n\n"
            f"قدّمت من <b>{days}</b> يوم. حصل إيه؟")
    markup = {"inline_keyboard": [
        [{"text": "📧 رد", "callback_data": f"or:{job['id']}"},
         {"text": "🎤 مقابلة", "callback_data": f"oi:{job['id']}"}],
        [{"text": "❌ رفض", "callback_data": f"oj:{job['id']}"},
         {"text": "🔇 مفيش", "callback_data": f"on:{job['id']}"}],
    ]}
    return text, markup


# ── الإغلاق التلقائي ────────────────────────────────────────────────────

def auto_close(db) -> int:
    """
    تقديم عدى عليه 21 يوم من غير نتيجة = مفيش رد.

    من غير ده، العيّنة بتفضل ناقصة للأبد لأن مفيش حد بيدوس زرار على
    وظيفة محدش رد عليها. الصمت هو الإجابة، والتسجيل التلقائي بيحوّله
    لبيانات نقدر نقيس عليها.
    """
    rows = db.table("applications").select("job_id") \
        .eq("confirmed", True).is_("outcome", "null") \
        .lt("decided_at", _ago(days=AUTO_CLOSE_DAYS)).execute().data
    if not rows:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        try:
            db.table("applications").update(
                {"outcome": "none", "outcome_at": now,
                 "notes": f"auto-closed after {AUTO_CLOSE_DAYS:g} days"}
            ).eq("job_id", r["job_id"]).execute()
        except Exception as exc:
            print(f"   (إغلاق {r['job_id']} فشل — {exc})"[:110])
    return len(rows)


# ── الإرسال ─────────────────────────────────────────────────────────────

def send_batch(db, items, builder, stamp_column, token, chat_id) -> dict:
    sent = failed = 0
    for i, item in enumerate(items):
        job = item["job"]
        days = 0
        if item.get("since"):
            days = (datetime.now(timezone.utc)
                    - datetime.fromisoformat(item["since"])).days
        text, markup = (builder(job, days) if stamp_column == "outcome_asked_at"
                        else builder(job))
        try:
            telegram.send_with_retry(text, token, chat_id, markup=markup)
            sent += 1
            print(f"   ❓ {job['company_name'][:16]:<18}{job['title'][:42]}")
        except Exception as exc:
            failed += 1
            print(f"   ❌ {job['title'][:38]} — {str(exc)[:60]}")

        # الختم بيتسجّل حتى لو الإرسال فشل — عشان مانلفّش على نفس
        # الوظيفة كل ساعة. الفشل نفسه بيبان في agent_runs.
        try:
            db.table("applications").update(
                {stamp_column: datetime.now(timezone.utc).isoformat()}
            ).eq("job_id", job["id"]).execute()
        except Exception as exc:
            print(f"   (تسجيل السؤال فشل — {exc})"[:110])

        if i < len(items) - 1:
            time.sleep(PACE)
    return {"sent": sent, "failed": failed}


# ── الإحصائيات ──────────────────────────────────────────────────────────

def show_stats(db) -> None:
    rows = db.table("applications").select(
        "status,confirmed,outcome,asked_at,outcome_asked_at").execute().data
    if not rows:
        print("مفيش قرارات لسه.")
        return

    applied = [r for r in rows if r["status"] == "applied"]
    yes = [r for r in applied if r["confirmed"] is True]
    no = [r for r in applied if r["confirmed"] is False]

    print(f"\nالقرارات: {len(rows)}")
    for st in ("applied", "skipped", "later"):
        print(f"   {st:<9}{sum(1 for r in rows if r['status'] == st)}")

    print(f"\nمن {len(applied)} ضغطة ✅:")
    print(f"   أكّد إنه قدّم    {len(yes)}")
    print(f"   قال مكمّلش      {len(no)}")
    print(f"   لسه ماردّش      {len(applied) - len(yes) - len(no)}")

    if yes or no:
        rate = len(yes) / (len(yes) + len(no)) * 100
        print(f"   نسبة التأكيد    {rate:.0f}%")
        if rate < 70:
            print("   ⚠️  أقل من 70% — الضغطة مش دليل تقديم. أي قياس")
            print("      على 'applied' من غير confirmed هيبقى غلط.")

    done = [r for r in yes if r["outcome"]]
    print(f"\nمن {len(yes)} تقديم مؤكد:")
    for o, label in (("interview", "مقابلة"), ("offer", "عرض"),
                     ("reply", "رد"), ("rejected", "رفض"), ("none", "مفيش رد")):
        n = sum(1 for r in done if r["outcome"] == o)
        if n:
            print(f"   {label:<10}{n}")
    print(f"   لسه مفتوح  {len(yes) - len(done)}")

    if len(done) >= 20:
        good = sum(1 for r in done if r["outcome"] in ("reply", "interview", "offer"))
        print(f"\n   نسبة الرد: {good / len(done) * 100:.0f}%  "
              f"({good} من {len(done)})")
        print("   العيّنة بقت كفاية لقياس دقة التقييم.")
    else:
        print(f"\n   العيّنة {len(done)} — محتاجين 20+ عشان القياس يبقى له معنى.")


# ── التشغيل ─────────────────────────────────────────────────────────────

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

    confirms = pending_confirm(db, args.limit)
    outcomes = pending_outcome(db, args.limit)

    if args.dry_run:
        print(f"تأكيد: {len(confirms)} · نتيجة: {len(outcomes)}")
        for it in confirms + outcomes:
            print(f"   {it['job']['company_name'][:16]:<18}"
                  f"{it['job']['title'][:46]}")
        print("\n(--dry-run: مفيش إرسال ولا إغلاق)")
        return 0

    closed = auto_close(db)
    if closed:
        print(f"🔇 اتقفل {closed} تقديم تلقائيًا "
              f"(عدى عليهم {AUTO_CLOSE_DAYS:g} يوم من غير رد)")

    if not confirms and not outcomes:
        print("مفيش تقديمات محتاجة متابعة.")
        return 0

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("❌ ناقص إعدادات تليجرام")
        return 1

    started = datetime.now(timezone.utc)
    total = {"sent": 0, "failed": 0}

    if confirms:
        print(f"\n❓ {len(confirms)} تقديم محتاج تأكيد")
        r = send_batch(db, confirms, confirm_message, "asked_at", token, chat)
        total = {k: total[k] + r[k] for k in total}

    if outcomes:
        print(f"\n📮 {len(outcomes)} تقديم عدى عليه {OUTCOME_AFTER_DAYS:g} أيام")
        r = send_batch(db, outcomes, outcome_message, "outcome_asked_at",
                       token, chat)
        total = {k: total[k] + r[k] for k in total}

    print(f"\n📊 اتسأل {total['sent']} · فشل {total['failed']} · "
          f"اتقفل تلقائيًا {closed}")

    try:
        db.table("agent_runs").insert({
            "component": "followup",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed" if (total["failed"] and not total["sent"])
                      else ("partial" if total["failed"] else "ok"),
            "items_seen": len(confirms) + len(outcomes),
            "items_new": total["sent"],
            "detail": total | {"auto_closed": closed,
                               "confirms": len(confirms),
                               "outcomes": len(outcomes)},
        }).execute()
    except Exception as exc:
        print(f"(تحذير: مقدرتش أسجّل التشغيلة — {exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
