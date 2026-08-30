"""
نقطة تشغيل التقييم.

  python -m src.score              → قيّم دفعة (الافتراضي 20 وظيفة)
  python -m src.score --limit 5    → دفعة أصغر
  python -m src.score --top        → اعرض أحسن الوظايف المقيّمة
  python -m src.score --stats      → إحصائيات بس، من غير أي نداء

منفصل عن src.main عن قصد: السحب مجاني وسريع، والتقييم بيكلّف ومقيّد
بحدود. لو التقييم وقف، السحب لازم يفضل شغال.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .main import get_client
from . import scoring


def show_top(db, n: int = 25) -> None:
    rows = db.table("scores") \
        .select("score_final,verdict,gaps,reasoning,job_id") \
        .eq("scorer_version", scoring.SCORER_VERSION) \
        .order("score_final", desc=True).limit(n).execute().data
    if not rows:
        print("مفيش تقييمات لسه.")
        return

    ids = [r["job_id"] for r in rows]
    jobs = {j["id"]: j for j in db.table("jobs")
            .select("id,company_name,title,location,url")
            .in_("id", ids).execute().data}

    print(f"\nأحسن {len(rows)} وظيفة\n")
    print(f"{'':4} {'الشركة':<16}{'الوظيفة':<44}{'المكان':<24}أهم فجوة")
    print("-" * 116)
    for r in rows:
        j = jobs.get(r["job_id"], {})
        gap = (r.get("gaps") or ["—"])[0]
        print(f"{r['score_final']:>3}  {j.get('company_name','?')[:14]:<16}"
              f"{j.get('title','?')[:42]:<44}{(j.get('location') or '—')[:22]:<24}{gap[:30]}")


def show_stats(db) -> None:
    rows = db.table("scores").select("score_final,verdict,total_tokens") \
        .eq("scorer_version", scoring.SCORER_VERSION).execute().data
    if not rows:
        print("مفيش تقييمات لسه.")
        return

    scores = sorted(r["score_final"] for r in rows if r["score_final"] is not None)
    tokens = sum(r.get("total_tokens") or 0 for r in rows)
    buckets = {"90+": 0, "70-89": 0, "50-69": 0, "30-49": 0, "<30": 0}
    for s in scores:
        k = ("90+" if s >= 90 else "70-89" if s >= 70 else
             "50-69" if s >= 50 else "30-49" if s >= 30 else "<30")
        buckets[k] += 1

    print(f"\nنسخة المقيّم: {scoring.SCORER_VERSION} · موديل: {scoring.MODEL}")
    print(f"متقيّم: {len(scores)} وظيفة · {tokens:,} توكن\n")
    for k, n in buckets.items():
        bar = "#" * round(n / max(len(scores), 1) * 40)
        print(f"  {k:<7}{n:>5}  {bar}")

    if scores:
        mid = scores[len(scores) // 2]
        print(f"\n  أعلى {scores[-1]} · وسيط {mid} · أقل {scores[0]}")

    # التوزيع هو اللي يهم مش المتوسط: لو كل حاجة بين 90 و98،
    # التقييم مش بيميّز حاجة والترتيب ضوضاء.
    top = sum(1 for s in scores if s >= 85)
    if len(scores) >= 20 and top > len(scores) * 0.6:
        print(f"\n  ⚠️  {top} من {len(scores)} فوق 85 — المقيّم كريم أوي، "
              "والترتيب في القمة مالوش معنى")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=scoring.BATCH)
    ap.add_argument("--top", action="store_true")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    db = get_client()

    if args.top:
        show_top(db)
        return 0
    if args.stats:
        show_stats(db)
        return 0

    started = datetime.now(timezone.utc)
    print(f"🤖 التقييم — {scoring.MODEL} · نسخة {scoring.SCORER_VERSION}\n")
    result = scoring.run(db, args.limit)

    if result.get("error"):
        print(f"❌ {result['error']}")
        return 1

    print(f"\n📊 قيّمت {result['scored']} · فشل {result['failed']} · "
          f"{result['tokens']:,} توكن · {result.get('seconds', 0)}ث")

    try:
        db.table("agent_runs").insert({
            "component": "score",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed" if (result["failed"] and not result["scored"])
                      else ("partial" if result["failed"] else "ok"),
            "items_seen": result["pending"],
            "items_new": result["scored"],
            "detail": result | {"scorer_version": scoring.SCORER_VERSION},
        }).execute()
    except Exception as exc:
        print(f"(تحذير: مقدرتش أسجّل التشغيلة — {exc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
