"""
حلقة اكتشاف الشركات.

    مصدر تجميعي  →  اسم شركة جديد  →  ندوّر على الـ ATS token
                                              │
                            ┌─────────────────┴─────────────────┐
                         لقيناه                            ملقناهوش
                            │                                   │
                     active في السجل                      unresolved
                            │                                   │
              كل وظايفها كل ساعة · للأبد          إعادة محاولة بعد 14 يوم

نسبة النجاح المقاسة على عيّنة حقيقية: 22%. مش عالية، بس التكلفة
~0.9 ثانية للشركة، والمكسب دايم: شركة اتحلّت مرة بتديك وظايفها للأبد.

مفيش AI هنا. تجريب منظّم بس.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from . import targeting
from .adapters import HEADERS

# نجرّب الأنظمة دي بالترتيب ده لكل صيغة اسم
PROBES = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{t}/jobs",
    "lever":      "https://api.lever.co/v0/postings/{t}?mode=json",
    "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{t}",
    "workable":   "https://apply.workable.com/api/v1/widget/accounts/{t}",
    "recruitee":  "https://{t}.recruitee.com/api/offers/",
}

PROBE_TIMEOUT = 8
RETRY_AFTER_DAYS = 14      # شركة ملقناهاش — منجربهاش تاني قبل كده
MAX_PER_RUN = 25           # سقف لكل تشغيلة عشان مانتعداش مهلة الـ workflow

# أسماء عامة مش شركات، بتيجي من المصادر التجميعية
JUNK = {"confidential", "private", "undisclosed", "n/a", "none", "various",
        "recruitment", "agency", "stealth", "startup", "company"}


def _count(ats: str, payload) -> int:
    if ats == "lever":
        return len(payload) if isinstance(payload, list) else 0
    if ats == "recruitee":
        return len(payload.get("offers", []))
    return len(payload.get("jobs", []))


def normalise(name: str) -> str:
    """المفتاح اللي بنقارن بيه. لازم يطابق الفهرس في الداتابيز."""
    return re.sub(r"\s+", " ", (name or "")).strip().lower()


def slugs(name: str) -> list[str]:
    """
    صيغ الـ token المحتملة. الشركات بتشيل اللواحق القانونية من الـ slug
    عادة: "everdrop GmbH" بيبقى "everdrop".
    """
    b = re.sub(r"[^a-z0-9 &]", " ", (name or "").lower())
    b = re.sub(r"\b(inc|llc|ltd|limited|gmbh|ag|bv|corp|co|the|group|holding)\b",
               " ", b)
    b = re.sub(r"\s+", " ", b).strip()
    if not b:
        return []
    out = [b.replace(" ", ""), b.replace(" ", "-")]
    if " " in b:
        out.append(b.split()[0])          # أول كلمة لوحدها
    seen, uniq = set(), []
    for s in out:
        if len(s) >= 2 and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _probe(args) -> tuple[str, str, int] | None:
    ats, token = args
    try:
        r = requests.get(PROBES[ats].format(t=token), headers=HEADERS,
                         timeout=PROBE_TIMEOUT)
        if r.status_code == 200:
            n = _count(ats, r.json())
            if n:
                return ats, token, n
    except Exception:
        pass
    return None


def resolve(name: str) -> tuple[str, str, int] | None:
    """اسم شركة → (النظام، الـ token، عدد الوظايف) أو None."""
    combos = [(a, s) for s in slugs(name) for a in PROBES]
    if not combos:
        return None
    with ThreadPoolExecutor(max_workers=10) as pool:
        for hit in pool.map(_probe, combos):
            if hit:
                return hit
    return None


def is_plausible(name: str) -> bool:
    n = normalise(name)
    return bool(n) and len(n) >= 2 and n not in JUNK and not n.isdigit()


# ── السجل في الداتابيز ──────────────────────────────────────────────────

def sync_seeds(client, companies: list[dict]) -> int:
    """
    شركات companies.yaml هي مصدر الحقيقة لنفسها. بنكتبها في الجدول
    كل تشغيلة عشان تعديلك في الملف يوصل، من غير ما نلمس المكتشفة.
    """
    n = 0
    for c in companies:
        try:
            client.table("companies").upsert({
                "name": c["name"], "name_key": normalise(c["name"]),
                "ats": c["ats"], "token": c["token"],
                "tier": c.get("tier", 2), "source": "seed", "status": "active",
            }, on_conflict="name_key").execute()
            n += 1
        except Exception as exc:
            # الطبع مش اختياري. النسخة الأولى كانت بتبلع الاستثناء،
            # فالتشغيلة قالت "لقيت 5 شركة" والجدول كان فاضي تمامًا.
            print(f"   (تزامن {c['name']} فشل — {type(exc).__name__}: {exc})"[:200])
    return n


def active_companies(client) -> list[dict]:
    rows = client.table("companies").select("name,ats,token,tier") \
        .eq("status", "active").not_.is_("token", "null").execute().data
    return [{"name": r["name"], "ats": r["ats"], "token": r["token"],
             "tier": r["tier"]} for r in rows]


def known_names(client) -> set[str]:
    rows = client.table("companies").select("name").execute().data
    return {normalise(r["name"]) for r in rows}


def due_for_retry(client, limit: int) -> list[str]:
    """شركات ملقناش لها token وعدت فترة الانتظار."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETRY_AFTER_DAYS)).isoformat()
    rows = client.table("companies").select("name") \
        .eq("status", "unresolved").lt("last_checked_at", cutoff) \
        .order("last_checked_at").limit(limit).execute().data
    return [r["name"] for r in rows]


def record(client, name: str, hit, source: str | None) -> bool:
    """سجّل نتيجة المحاولة. رجّع True لو اتكتبت فعلاً."""
    row = {
        "name": name.strip(),
        "name_key": normalise(name),
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
        "discovered_from": source,
        "source": "discovered",
    }
    if hit:
        ats, token, count = hit
        row |= {"ats": ats, "token": token, "status": "active", "jobs_count": count}
    else:
        row |= {"status": "unresolved"}

    try:
        client.table("companies").upsert(row, on_conflict="name_key").execute()
        return True
    except Exception as exc:
        # شركتين بأسماء مختلفة وصلوا لنفس الـ token — تصادم متوقع،
        # سجّلها unresolved بدل ما نفقد الاسم خالص.
        if hit and "duplicate" in str(exc).lower():
            try:
                client.table("companies").upsert(
                    row | {"ats": None, "token": None, "status": "unresolved"},
                    on_conflict="name_key").execute()
                return True
            except Exception:
                pass
        print(f"   (تسجيل {name} فشل — {type(exc).__name__}: {exc})"[:200])
        return False


def discover(client, jobs, budget: int = MAX_PER_RUN) -> dict:
    """
    خد أسماء الشركات من وظايف المصادر التجميعية، وحاول تحل الجديد منها.

    السقف مقصود: الـ workflow مهلته 10 دقايق، والحل بياخد ~1 ثانية
    للشركة. الباقي بيستنى التشغيلة الجاية — مفيش استعجال، دي حلقة
    بتشتغل كل ساعة.
    """
    seen = known_names(client)
    fresh: dict[str, str] = {}
    skipped = 0

    for j in jobs:
        k = normalise(j.company_name)
        if not k or k in seen or k in fresh or not is_plausible(j.company_name):
            continue

        # الفلتر ده هو الفرق بين حلقة بتكبر وحلقة بتنفجر.
        #
        # من غيره بنضيف أي شركة نقدر نحل الـ token بتاعها — وكل شركة
        # بتجيب بوردها كامل. شركة تجارة سلع ألمانية ظهرت من إعلان
        # "Werkstudent Controlling" بتضيف 200 وظيفة مالهاش أي لازمة.
        #
        # قيسناها: من غير الفلتر، التشغيلة كانت بتضيف 2400 وظيفة
        # وبتزيد كل ساعة — كان هياكل الحد المجاني في أسبوعين.
        if not targeting.matches_role(j.title):
            skipped += 1
            continue

        fresh[k] = j.ats
        seen.add(k)

    names = [(n, src) for n, src in fresh.items()][:budget]

    # المتبقي من الميزانية يروح لإعادة محاولة القديم
    if len(names) < budget:
        names += [(n, None) for n in due_for_retry(client, budget - len(names))]

    resolved = written = 0
    for name, src in names:
        hit = resolve(name)
        if record(client, name, hit, src):
            written += 1
        if hit:
            resolved += 1

    # written بيتسجّل عن قصد: لو الكتابة فشلت، الرقم ده بيفضح الفرق
    # بدل ما نقول "لقيت 5" والجدول فاضي.
    return {"candidates": len(fresh), "tried": len(names), "skipped": skipped,
            "resolved": resolved, "written": written}
