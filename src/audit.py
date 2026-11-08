"""
الرقيب.

  python -m src.audit   → اطبع الملاحظات

بيتنده لوحده من `src.report` في آخر كل تشغيلة يومية، وملاحظاته
بتتلزق تحت التقرير على تليجرام. فمفيش أمر جديد في المهمة المجدولة —
وده مقصود: أي أمر جديد هناك بيوقف التشغيلة على سؤال صلاحيات.

ليه الملف ده موجود:

أخطر أعطال المشروع كانت ساكتة. كل واحد فيهم كان شغال "بنجاح":
  · الكومنتات رجعت صفر منشور كل يوم من 6 أكتوبر — لينكدإن غيّر الصفحة
  · Supabase اتقيّد يوم 23 أكتوبر على حصة نقل البيانات — كل حاجة وقفت
  · سحب الـATS على GitHub بيقف عند العشر دقايق في كل تشغيلة من أيام
  · 16 وظيفة وصلت تليجرام في 9 أيام ومفيش ولا ضغطة زرار

ولا واحد فيهم كان بيبان غير لما حد يدوّر. الرقيب بيدوّر كل يوم.

الفحص قراءة بس، وخفيف عن قصد: سجل التشغيلات وعدّادات. مفيش أوصاف
ولا صفوف كبيرة — حصة نقل البيانات هي اللي وقعتنا أول مرة.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

LABEL = {
    "jobboard": "لوحة الوظايف",
    "harvest": "منشورات التوظيف",
    "score": "التقييم",
    "notify": "الإرسال",
    "engage": "متابعة الشركات",
    "comment": "الكومنتات",
    "followup": "متابعة التقديمات",
    "discover": "سحب الـATS (GitHub)",
    "connect": "الدعوات",
}

# خطوات التشغيلة اليومية — لازم كل واحدة تكون اتسجّلت النهاردة.
DAILY = ["jobboard", "harvest", "score", "notify", "engage", "comment",
         "followup"]

TODAY_HOURS = 20
ENGAGE_STATE = Path("state/engage.json")
JOB_QUEUE = Path("state/jobboard_queue.json")

RED, YELLOW = "🔴", "🟡"


def _ts(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def _err(r: dict) -> str:
    d = r.get("detail") or {}
    return str(d.get("error") or "")[:120] if isinstance(d, dict) else ""


# ── الفحوص ─────────────────────────────────────────────────────────────

def database(db) -> list[tuple[str, str]]:
    """من غير الداتابيز مفيش حاجة تانية تتفحص — ومفيش خطوة تشتغل."""
    try:
        db.table("agent_runs").select("id").limit(1).execute()
        return []
    except Exception as exc:
        msg = str(exc)
        if "egress" in msg:
            return [(RED, "Supabase متقيّد: حصة نقل البيانات خلصت "
                          "(exceed_egress_quota). كل الخطوات هتفشل لحد ما "
                          "الدورة تتجدد أو الخطة تترقّى.")]
        return [(RED, f"الداتابيز مش بترد: {msg[:140]}")]


def runs(rows: list[dict], now: datetime) -> list[tuple[str, str]]:
    """اللي ما اشتغلش، واللي فشل، واللي بيرجع صفر أيام ورا بعض."""
    out: list[tuple[str, str]] = []
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["component"], []).append(r)
    since = now - timedelta(hours=TODAY_HOURS)
    today = {c: [r for r in rs if _ts(r["started_at"]) >= since]
             for c, rs in by.items()}

    for r in rows:
        if _ts(r["started_at"]) >= since and "اعتراض" in json.dumps(
                r.get("detail") or {}, ensure_ascii=False):
            out.append((RED, f"لينكدإن اعترض في {LABEL.get(r['component'], r['component'])}"
                             f": {_err(r)} — وقّف كل حاجة وبص على الحساب بإيدك."))

    for c in DAILY:
        if not today.get(c):
            out.append((YELLOW, f"{LABEL[c]}: ما اتسجّلش في آخر {TODAY_HOURS} ساعة "
                                f"(ما اشتغلش، أو وقع قبل ما يسجّل)."))
    for c, rs in today.items():
        for r in rs:
            if r["status"] == "failed":
                out.append((RED, f"{LABEL.get(c, c)} فشل: {_err(r) or 'من غير سبب متسجّل'}"))

    def streak(c: str) -> int:
        n = 0
        for r in reversed(by.get(c, [])):
            if r["status"] == "failed" or r.get("items_seen"):
                break
            n += 1
        return n

    if streak("jobboard") >= 2:
        out.append((RED, f"لوحة الوظايف: صفر كروت {streak('jobboard')} تشغيلات ورا بعض "
                         "— غالبًا لينكدإن غيّر صفحة البحث."))
    if streak("harvest") >= 2:
        out.append((RED, f"منشورات التوظيف: صفر منشور {streak('harvest')} تشغيلات ورا بعض."))
    if streak("comment") >= 3:
        out.append((YELLOW, f"الكومنتات: صفر منشور {streak('comment')} تشغيلات ورا بعض."))

    sc = today.get("score", [])
    if sc:
        scored = sum((r.get("detail") or {}).get("scored", 0) or 0 for r in sc)
        failed = sum((r.get("detail") or {}).get("failed", 0) or 0 for r in sc)
        if not scored and failed:
            out.append((YELLOW, f"التقييم: ولا وظيفة اتقيّمت ({failed} فشل) — "
                                "غالبًا حصة Gemini خلصت."))

    disc = by.get("discover", [])
    if disc:
        age = (now - _ts(disc[-1]["started_at"])).total_seconds() / 3600
        if age > 12:
            out.append((YELLOW, f"سحب الـATS على GitHub ماخلّصش تشغيلة من {age:.0f} ساعة "
                                "(بيقف عند حد العشر دقايق)."))
    return out


def buttons(db, now: datetime) -> list[tuple[str, str]]:
    """من غير ضغطات مفيش متابعة ولا قياس — المرحلة 4 كلها بتقف."""
    since = (now - timedelta(days=14)).isoformat()
    try:
        sent = db.table("deliveries").select("id", count="exact") \
            .gte("sent_at", since).limit(1).execute().count or 0
        decided = db.table("applications").select("id", count="exact") \
            .gte("decided_at", since).limit(1).execute().count or 0
    except Exception:
        return []
    if sent and not decided:
        return [(YELLOW, f"وصلك {sent} وظيفة في أسبوعين ومفيش ولا ضغطة زرار — "
                         "من غيرها مفيش متابعة ولا قياس.")]
    return []


def _tokens(s: str, least: int = 3) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) >= least}


def same_company(name: str, slug: str) -> bool:
    """
    المعرّف بيخص الشركة دي؟ يا فيه كلمة مشتركة، يا المعرّف كله مكوّن
    من كلمات الاسم لازقة في بعض: `siemenssoftware` و`cntxtai` صح.
    `mossconstruct` لأ — "construct" مش من اسم الشركة.
    """
    if _tokens(name) & _tokens(slug.replace("-", " ")):
        return True
    words = _tokens(name, least=2)
    flat = re.sub(r"[^a-z0-9]", "", (slug or "").lower())
    ok = [True] + [False] * len(flat)
    for i in range(1, len(flat) + 1):
        ok[i] = any(ok[i - len(w)] and flat[i - len(w):i] == w
                    for w in words if len(w) <= i)
    return bool(flat) and ok[-1]


def follows(now: datetime) -> list[tuple[str, str]]:
    """
    متابعة شكلها لشركة تانية. حادثة `mossconstruct`: البحث عن "moss"
    تابع شركة إنشاءات.
    """
    try:
        state = json.loads(ENGAGE_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    since = now - timedelta(hours=TODAY_HOURS)
    out = []
    for name, v in (state.get("companies") or {}).items():
        if not isinstance(v, dict):      # سجلات قديمة كانت تاريخ بس
            continue
        try:
            if not v.get("followed") or _ts(v["at"]) < since:
                continue
        except (KeyError, ValueError):
            continue
        slug = v.get("slug") or ""
        if not same_company(name, slug):
            out.append((YELLOW, f"متابعة شكلها غلط: «{name}» → {v.get('url') or slug}"))
    return out


def queue() -> list[tuple[str, str]]:
    try:
        n = len(json.loads(JOB_QUEUE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []
    if n > 60:
        return [(YELLOW, f"طابور لوحة الوظايف فيه {n} وظيفة مستنية وصف — "
                         "السقف اليومي مش ملاحق.")]
    return []


# ── التجميع ────────────────────────────────────────────────────────────

def check(db=None, now: datetime | None = None) -> list[tuple[str, str]]:
    now = now or datetime.now(timezone.utc)
    if db is None:
        try:
            from .main import get_client
            db = get_client()
        except (Exception, SystemExit) as exc:
            return [(RED, f"مفيش اتصال بالداتابيز: {exc}")]

    out = database(db)
    if out:
        return out + follows(now)

    try:
        rows = db.table("agent_runs") \
            .select("component,started_at,status,items_seen,items_new,detail") \
            .gte("started_at", (now - timedelta(days=8)).isoformat()) \
            .order("started_at").limit(500).execute().data
    except Exception as exc:
        return [(RED, f"سجل التشغيلات مش بيتقري: {str(exc)[:140]}")]

    out = runs(rows, now) + buttons(db, now) + follows(now) + queue()
    return sorted(out, key=lambda x: x[0] != RED)


def render(items: list[tuple[str, str]]) -> str:
    if not items:
        return "🛡 الرقيب: مفيش ملاحظات."
    return "🛡 الرقيب:\n" + "\n".join(f"{lvl} {txt}" for lvl, txt in items)


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    print(render(check()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
