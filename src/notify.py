"""
نقطة تشغيل الإرسال.

  python -m src.notify              → ابعت الوظايف الجديدة اللي فوق العتبة
  python -m src.notify --dry-run    → اعرض اللي هيتبعت من غير ما تبعت
  python -m src.notify --setup      → اتأكد من التوكن وجيب رقم المحادثة
  python -m src.notify --test       → ابعت رسالة تجربة

منفصل عن السحب والتقييم عن قصد: ده الجزء الوحيد اللي بيوصلك، فلو وقع
لازم يبان لوحده مش مدفون جوّا تشغيلة تانية.
"""
from __future__ import annotations

import argparse
import os
import re
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from . import telegram
from .main import get_client

load_dotenv()

# العتبة: تحتها مبنبعتش. من توزيع أول 10 وظايف، 60 بيسيب "المحتمل"
# يعدّي ويقفل الباب على الواضح إنه مش مناسب.
MIN_SCORE = int(os.getenv("NOTIFY_MIN_SCORE", "70"))

# سقف لكل تشغيلة. البرنامج بيشتغل كل ساعة — من غير السقف ده، أول
# تشغيلة بعد تقييم كبير هتبعتلك 40 رسالة مرة واحدة.
MAX_PER_RUN = int(os.getenv("NOTIFY_MAX_PER_RUN", "5"))

PACE = 1.5      # ثانية بين الرسايل — تليجرام بيخنق الإرسال السريع


def unsent(db, limit: int) -> list[dict]:
    """
    وظايف فوق العتبة، متبعتتش قبل كده. الأعلى تقييمًا الأول.

    زي التقييم: جدول deliveries هو الطابور. مفيش علامة "اتبعت" على
    الوظيفة نفسها — وجود صف هو العلامة.
    """
    from . import scoring

    rows = db.table("scores") \
        .select("job_id,score_initial,score_final,verdict,matched,gaps,reasoning") \
        .eq("scorer_version", scoring.SCORER_VERSION) \
        .gte("score_final", MIN_SCORE) \
        .order("score_final", desc=True).limit(200).execute().data
    if not rows:
        return []

    sent = {d["job_id"] for d in
            db.table("deliveries").select("job_id")
            .eq("channel", "telegram").execute().data}

    fresh = [r for r in rows if r["job_id"] not in sent]
    if not fresh:
        return []

    # كل الوظايف — المتبعتة والجديدة — عشان نعرف اللي إعلانه اتبعت قبل
    # كده في مدينة تانية.
    ids = [r["job_id"] for r in fresh] + list(sent)
    jobs = {}
    for i in range(0, len(ids), 200):
        jobs |= {j["id"]: j for j in db.table("jobs")
                 .select("id,company_name,title,location,remote_type,url")
                 .in_("id", ids[i:i + 200]).execute().data}

    # الشركة + العنوان = نفس الإعلان، حتى لو المدينة مختلفة.
    #
    # التخزين والإرسال قرارين مختلفين عن قصد: الموقع داخل في البصمة
    # عشان مانضيّعش وظيفة في الرياض وواحدة في دبي — لكن إنت مش عايز
    # 3 رسايل لنفس الإعلان. الجمع بيحصل هنا، مش في التخزين.
    def poster(j: dict) -> tuple[str, str]:
        return (str(j.get("company_name") or "").strip().lower(),
                re.sub(r"[\s\W]+", " ", str(j.get("title") or "").lower()).strip())

    seen = {poster(jobs[i]) for i in sent if i in jobs}

    out = []
    for r in fresh:
        job = jobs.get(r["job_id"])
        if not job:
            continue
        key = poster(job)
        if key in seen:
            continue
        seen.add(key)
        out.append({"job": job, "score": r})
        if len(out) >= limit:
            break
    return out


def deliver(db, items: list[dict], token: str, chat_id: str) -> dict:
    sent = failed = 0
    for i, item in enumerate(items):
        job, score = item["job"], item["score"]
        text = telegram.format_job(job, score)
        row = {"job_id": job["id"], "channel": "telegram",
               "score_at_send": score.get("score_final")}
        try:
            row["message_id"] = telegram.send_with_retry(
                text, token, chat_id, markup=telegram.keyboard(job["id"]))
            sent += 1
            print(f"   ✅ {score['score_final']:>3} {job['company_name'][:16]:<18}"
                  f"{job['title'][:44]}")
        except Exception as exc:
            failed += 1
            row["error"] = str(exc)[:400]
            print(f"   ❌ {job['title'][:40]} — {str(exc)[:80]}")

        # بنسجّل النجاح والفشل الاتنين. لو سجّلنا الناجح بس، الوظيفة
        # اللي فشلت هتتحاول كل ساعة للأبد.
        try:
            db.table("deliveries").upsert(row, on_conflict="job_id,channel").execute()
        except Exception as exc:
            print(f"   (تسجيل الإرسال فشل — {type(exc).__name__}: {exc})"[:160])

        if i < len(items) - 1:
            time.sleep(PACE)

    return {"sent": sent, "failed": failed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--limit", type=int, default=MAX_PER_RUN)
    args = ap.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    # ── الإعداد لأول مرة ──
    if args.setup:
        if not token:
            print("❌ حط TELEGRAM_BOT_TOKEN في .env الأول")
            return 1
        me = telegram.whoami(token)
        print(f"🤖 البوت: @{me.get('username')} ({me.get('first_name')})\n")
        chats = telegram.find_chat_id(token)
        if not chats:
            print("⚠️  مفيش رسايل. ابعت أي رسالة للبوت وشغّل الأمر تاني.")
            return 1
        for c in chats:
            print(f"   TELEGRAM_CHAT_ID={c['chat_id']}   ({c['name']} · {c['type']})")
        print("\nحط السطر ده في .env")
        return 0

    if args.test:
        mid = telegram.send("✅ <b>Apply Agent</b>\nالاتصال شغال.")
        print(f"اتبعت · message_id={mid}")
        return 0

    # ── التشغيل العادي ──
    db = get_client()
    items = unsent(db, args.limit)

    if not items:
        print(f"مفيش وظايف جديدة فوق {MIN_SCORE}.")
        return 0

    print(f"📬 {len(items)} وظيفة فوق {MIN_SCORE}\n")

    if args.dry_run:
        for it in items:
            print(f"   {it['score']['score_final']:>3}  "
                  f"{it['job']['company_name'][:16]:<18}{it['job']['title'][:50]}")
        print("\n(--dry-run: مفيش إرسال)")
        return 0

    if not token or not os.getenv("TELEGRAM_CHAT_ID"):
        print("❌ ناقص TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID. شغّل --setup")
        return 1

    started = datetime.now(timezone.utc)
    result = deliver(db, items, token, os.getenv("TELEGRAM_CHAT_ID").strip())
    print(f"\n📊 اتبعت {result['sent']} · فشل {result['failed']}")

    try:
        db.table("agent_runs").insert({
            "component": "notify",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed" if (result["failed"] and not result["sent"])
                      else ("partial" if result["failed"] else "ok"),
            "items_seen": len(items),
            "items_new": result["sent"],
            "detail": result | {"min_score": MIN_SCORE},
        }).execute()
    except Exception as exc:
        print(f"(تحذير: مقدرتش أسجّل التشغيلة — {exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
