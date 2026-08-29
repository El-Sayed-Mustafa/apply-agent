"""
نقطة التشغيل.

  python -m src.main            → اسحب من كل الشركات واحفظ الجديد
  python -m src.main --verify   → بس اتأكد إن كل شركة في السجل بترجّع وظايف
  python -m src.main --dry-run  → اسحب واعرض من غير ما تحفظ

الخطوات: اقرا السجل → اسحب → طبّع → شيل المكرر → احفظ الجديد بس.
مفيش AI هنا. ده الجزء الممل والمهم.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

from .adapters import Job, fetch

load_dotenv()

REGISTRY_PATH = os.getenv("REGISTRY_PATH", "companies.yaml")
CHUNK = 200  # عدد البصمات في استعلام واحد


# ---------------------------------------------------------------------------

def load_companies() -> list[dict]:
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    companies = data.get("companies") or []
    for c in companies:
        missing = [k for k in ("name", "ats", "token") if not c.get(k)]
        if missing:
            raise ValueError(f"شركة ناقصة حقول {missing}: {c}")
        c.setdefault("tier", 2)
    return companies


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("❌ ناقص SUPABASE_URL أو SUPABASE_SERVICE_KEY. شوف .env.example")
    from supabase import create_client
    return create_client(url, key)


def existing_hashes(client, hashes: list[str]) -> set[str]:
    """رجّع البصمات الموجودة أصلاً في الداتابيز، على دفعات."""
    found: set[str] = set()
    for i in range(0, len(hashes), CHUNK):
        batch = hashes[i:i + CHUNK]
        res = client.table("jobs").select("content_hash").in_("content_hash", batch).execute()
        found.update(row["content_hash"] for row in (res.data or []))
    return found


def touch_seen(client, hashes: list[str]) -> None:
    """حدّث last_seen_at للوظايف اللي لسه معروضة — عشان نعرف اللي اتشال."""
    now = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(hashes), CHUNK):
        batch = hashes[i:i + CHUNK]
        client.table("jobs").update({"last_seen_at": now}).in_("content_hash", batch).execute()


# ---------------------------------------------------------------------------

def collect(companies: list[dict]) -> tuple[list[Job], list[dict]]:
    """اسحب من كل الشركات. رجّع (الوظايف، تقرير المصادر)."""
    all_jobs: list[Job] = []
    report: list[dict] = []

    for c in companies:
        label = f"{c['name']} ({c['ats']}/{c['token']})"
        try:
            jobs = fetch(c)
            all_jobs.extend(jobs)
            status = "ok" if jobs else "empty"
            icon = "✅" if jobs else "⚠️ "
            print(f"{icon} {label}: {len(jobs)} وظيفة")
            report.append({"company": c["name"], "status": status, "count": len(jobs)})
        except Exception as exc:
            print(f"❌ {label}: {type(exc).__name__} — {exc}")
            report.append({"company": c["name"], "status": "failed", "error": str(exc)[:300]})

    return all_jobs, report


def check_health(client, report: list[dict]) -> list[str]:
    """
    قارن كل مصدر بآخر تشغيلة ناجحة.

    المشكلة اللي بتحلها: مصدر ممكن "ينجح" وهو راجع بحاجة غلط. لو شركة
    بترجّع 248 وظيفة رجّعت النهاردة 3، الكود مش هيقع — هيقول ✅ ويكمّل،
    وإنت هتفضل فاكر إن كل حاجة تمام لأسابيع.

    مفيش جدول جديد هنا: الأرقام متسجلة أصلاً في agent_runs.detail،
    فبنقراها ونقارن.
    """
    try:
        prev = client.table("agent_runs") \
            .select("detail") \
            .eq("component", "discover") \
            .in_("status", ["ok", "partial"]) \
            .order("id", desc=True).limit(1).execute().data
    except Exception:
        return []                      # مفيش تاريخ = مفيش مقارنة، مش خطأ

    if not prev:
        return []

    before = {s["company"]: s.get("count", 0)
              for s in (prev[0].get("detail") or {}).get("sources", [])}

    alerts = []
    for src in report:
        old = before.get(src["company"])
        new = src.get("count", 0)
        if not old or old < 5:         # عدد صغير أصلاً = التذبذب طبيعي
            continue
        if new < old * 0.5:
            drop = round((1 - new / old) * 100)
            alerts.append(f"{src['company']}: {old} → {new} (نزل {drop}%)")

    return alerts


def dedupe_in_batch(jobs: list[Job]) -> list[Job]:
    """شيل المكرر جوّا نفس السحبة (شركة ناشرة نفس الوظيفة مرتين)."""
    seen: set[str] = set()
    unique = []
    for j in jobs:
        if j.content_hash not in seen:
            seen.add(j.content_hash)
            unique.append(j)
    return unique


def save(client, jobs: list[Job]) -> list[Job]:
    """احفظ الجديد بس. رجّع اللي اتحفظ فعلاً."""
    if not jobs:
        return []

    hashes = [j.content_hash for j in jobs]
    already = existing_hashes(client, hashes)

    new = [j for j in jobs if j.content_hash not in already]
    old = [h for h in hashes if h in already]

    if old:
        touch_seen(client, old)

    for i in range(0, len(new), 100):
        client.table("jobs").insert([j.as_row() for j in new[i:i + 100]]).execute()

    return new


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="اتأكد من السجل بس")
    ap.add_argument("--dry-run", action="store_true", help="اسحب من غير حفظ")
    args = ap.parse_args()

    companies = load_companies()
    print(f"📋 السجل: {len(companies)} شركة\n")

    jobs, report = collect(companies)
    jobs = dedupe_in_batch(jobs)

    ok = sum(1 for r in report if r["status"] == "ok")
    empty = [r["company"] for r in report if r["status"] == "empty"]
    failed = [r["company"] for r in report if r["status"] == "failed"]

    print(f"\n📊 {ok} مصدر شغال · {len(empty)} فاضي · {len(failed)} فشل")
    print(f"📥 {len(jobs)} وظيفة فريدة في السحبة دي")

    if empty:
        print(f"⚠️  رجّعوا صفر وظيفة (غالبًا الـ token غلط): {', '.join(empty)}")
    if failed:
        print(f"❌ فشلوا: {', '.join(failed)}")

    if args.verify:
        print("\n(--verify: مفيش حفظ)")
        return 1 if failed else 0

    if args.dry_run:
        print("\n(--dry-run: مفيش حفظ) — أول 10:")
        for j in jobs[:10]:
            print(f"   · {j.company_name} — {j.title} [{j.location or '—'}] ({j.remote_type})")
        return 0

    client = get_client()
    started = datetime.now(timezone.utc)

    alerts = check_health(client, report)
    if alerts:
        print("\n🚨 مصادر نزلت فجأة مقارنة بآخر تشغيلة:")
        for a in alerts:
            print(f"   · {a}")

    try:
        new = save(client, jobs)
    except Exception:
        traceback.print_exc()
        return 1

    print(f"\n🆕 {len(new)} وظيفة جديدة اتحفظت")
    for j in new[:20]:
        print(f"   · {j.company_name} — {j.title} [{j.location or '—'}] ({j.remote_type})")
    if len(new) > 20:
        print(f"   … و{len(new) - 20} كمان")

    try:
        client.table("agent_runs").insert({
            "component": "discover",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed" if ok == 0 else ("partial" if (failed or alerts) else "ok"),
            "items_seen": len(jobs),
            "items_new": len(new),
            "detail": {"sources": report, "alerts": alerts},
        }).execute()
    except Exception as exc:
        # تسجيل التشغيلة مش أهم من الشغل نفسه — الوظايف اتحفظت بالفعل.
        print(f"(تحذير: مقدرتش أسجّل التشغيلة — {exc})")

    # الخروج بخطأ لما كل المصادر تقع. GitHub Actions بيبعتلك إيميل
    # على الفشل — فده أرخص تنبيه ممكن، من غير أي بنية تحتية.
    return 1 if ok == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
