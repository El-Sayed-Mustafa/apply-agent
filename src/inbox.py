"""
الشريحة 12 — صندوق الطلبات.

  python -m src.inbox --dry-run    → اعرض اللي هيتنقل من غير ما تلمس حاجة
  python -m src.inbox              → نزّل المرفقات وحط اللِيبل
  python -m src.inbox --stats      → اللي اتجمع

البوست جاب 200 طلب في 3 أيام. الصندوق بقى مش قابل للقراءة، والـCVات
مدفونة جوّه الرسايل.

الشريحة دي بتعمل حاجتين:

  · بتنزّل كل مرفق على الجهاز في applications/ بمجلد لكل مرشّح
  · بتحط لِيبل على الرسالة في Gmail عشان تخرج من الإنبوكس

ليه IMAP مش الموصل بتاع Gmail:

الموصل بيقرا نص الرسالة وأسماء المرفقات بس — مفيش طريقة ينزّل
الملف نفسه. وكمان بيشتغل جوّه جلسة Claude بس، والمشروع كله بيشتغل
من Task Scheduler من غير ما حد يفتح حاجة.

**المرفقات دي ملفات من ناس مش معروفين.** بننزّلها وخلاص — مابنفتحش
ولا بننفّذ حاجة منها، وبنقبل امتدادات المستندات بس.
"""
from __future__ import annotations

import argparse
import email
import imaplib
import json
import os
import re
from datetime import datetime, timezone
from email.header import decode_header, make_header
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

HOST = "imap.gmail.com"
FOLDER = os.getenv("INBOX_LABEL", "Applications")
STATE = Path("state/applications.json")
FILES = Path(os.getenv("INBOX_DIR", "applications"))

# امتدادات المستندات بس. مرفق من حد مش معروف ممكن يكون أي حاجة،
# واحنا مش محتاجين غير السيرة الذاتية.
ALLOWED = {".pdf", ".doc", ".docx", ".rtf", ".odt", ".txt", ".md",
           ".png", ".jpg", ".jpeg"}
MAX_BYTES = 15 * 1024 * 1024

# الطلبات اللي وصلت كتبت العنوان بأشكال كتير: "Data Analyst - Scraping"،
# "Data analyst- scraping"، "Junior Python Developer"، "Data & SQL"،
# وواحد كتب "Scarping". فمابنطابقش العنوان — بنشوف الرسالة كلها.
APPLY = re.compile(
    r"scrap\w*|scarp\w*|data\s*analyst|python\s*develop\w*|data\s*&?\s*sql|"
    r"data\s*engineer|apply\w*|application|resume|\bcv\b|hiring|position|"
    r"join\s+(?:the|our|your)\s+team|interest(?:ed)?\s+in\s+(?:the\s+)?"
    r"(?:position|role|job|joining)|graduat\w*|\bintern\w*|"
    r"وظيف\w*|تقديم|السيرة|مهندس|خريج\w*|حديث\s*(?:ال)?تخرج", re.I)


def _text(raw) -> str:
    """عناوين الإيميل بتيجي مشفّرة (=?UTF-8?B?...) — رجّعها نص."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def sender(msg) -> tuple[str, str]:
    """رجّع (الاسم، الإيميل)."""
    name, addr = email.utils.parseaddr(_text(msg.get("From")))
    return name.strip() or addr.split("@")[0], addr.lower()


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s or "unknown")[:48]


def safe_name(raw: str) -> str | None:
    """
    اسم ملف آمن، أو None لو مرفوض.

    الاسم جاي من برّه: ممكن يكون فيه مسار (`../../x`) أو امتداد
    تنفيذي. بناخد آخر جزء بس، وبنقبل المستندات وخلاص.
    """
    name = _text(raw)
    name = re.sub(r"[\\/]", " ", name).strip()
    name = re.sub(r"[^\w\s.()\-]", "_", name)[:120]
    if not name or name.startswith("."):
        return None
    ext = Path(name).suffix.lower()
    return name if ext in ALLOWED else None


def looks_like_application(subject: str, body: str, files: list[str]) -> bool:
    if files:
        return True
    return bool(APPLY.search(f"{subject} {body[:1500]}"))


def body_text(msg) -> str:
    """نص الرسالة — بنفضّل text/plain وبنقع على HTML لو مالقيناش."""
    plain, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() != "text":
            continue
        if part.get_filename():
            continue
        try:
            raw = part.get_payload(decode=True) or b""
            txt = raw.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        (plain if part.get_content_subtype() == "plain" else html).append(txt)

    text = "\n".join(plain) or re.sub(r"<[^>]+>", " ", "\n".join(html))
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:4000]


# ── الحالة ──────────────────────────────────────────────────────────────

def load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"   ⚠ ملف الطلبات مقروش: {exc}")
    return {}


def store(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                     encoding="utf-8")


# ── التحميل ─────────────────────────────────────────────────────────────

def save_parts(msg, folder: Path, dry: bool) -> list[str]:
    """احفظ المرفقات المسموحة. رجّع أسماء اللي اتحفظ."""
    saved, skipped = [], []
    for part in msg.walk():
        raw_name = part.get_filename()
        if not raw_name:
            continue
        name = safe_name(raw_name)
        if not name:
            skipped.append(_text(raw_name)[:40])
            continue
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            continue
        if not data or len(data) > MAX_BYTES:
            skipped.append(f"{name} ({len(data)//1024}KB)")
            continue
        if not dry:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(data)
        saved.append(name)

    if skipped:
        print(f"      (اترفض: {', '.join(skipped[:3])})")
    return saved


def connect():
    user = os.getenv("GMAIL_USER")
    pwd = os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pwd:
        raise RuntimeError(
            "مفيش GMAIL_USER أو GMAIL_APP_PASSWORD في .env")
    box = imaplib.IMAP4_SSL(HOST)
    box.login(user, pwd)
    return box


def run(dry: bool = False, days: int = 14, limit: int = 0) -> dict:
    state = load()
    try:
        box = connect()
    except Exception as exc:
        return {"error": str(exc)}

    try:
        # اللِيبل بيتعمل مرة واحدة؛ لو موجود بيرجّع خطأ وبنعدّيه
        if not dry:
            box.create(FOLDER)

        box.select("INBOX")
        since = (datetime.now(timezone.utc) - __import__("datetime")
                 .timedelta(days=days)).strftime("%d-%b-%Y")
        ok, data = box.search(None, f'(SINCE "{since}")')
        if ok != "OK":
            return {"error": f"البحث فشل: {ok}"}

        ids = data[0].split()
        if limit:
            ids = ids[-limit:]
        print(f"📬 {len(ids)} رسالة في آخر {days} يوم\n")

        moved = skipped = seen = 0
        for num in ids:
            ok, raw = box.fetch(num, "(RFC822)")
            if ok != "OK" or not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])

            mid = (msg.get("Message-ID") or "").strip() or f"num:{num.decode()}"
            if mid in state:
                seen += 1
                continue

            name, addr = sender(msg)
            subject = _text(msg.get("Subject"))
            body = body_text(msg)

            folder = FILES / f"{slug(addr.split('@')[0])}"
            files = save_parts(msg, folder, dry)

            if not looks_like_application(subject, body, files):
                skipped += 1
                continue

            state[mid] = {
                "at": datetime.now(timezone.utc).isoformat(),
                "date": _text(msg.get("Date")),
                "name": name, "email": addr, "subject": subject,
                "body": body, "files": files,
                "folder": str(folder) if files else "",
            }
            if not dry:
                box.copy(num, FOLDER)
                store(state)
            moved += 1
            print(f"   ✅ {name[:24]:<26}{addr[:30]:<32}"
                  f"{len(files)} مرفق  {subject[:30]}")

        print(f"\n📊 {moved} طلب جديد · {seen} اتسجّل قبل كده"
              f" · {skipped} مش طلب")
        if dry:
            print("(--dry-run: مفيش تحميل ولا لِيبل)")
        return {"moved": moved, "seen": seen, "skipped": skipped}
    finally:
        try:
            box.logout()
        except Exception:
            pass


def show_stats() -> None:
    state = load()
    with_cv = [v for v in state.values() if v.get("files")]
    print(f"طلبات: {len(state)} · معاها مرفق: {len(with_cv)}\n")
    for v in sorted(state.values(), key=lambda x: x.get("date", ""), reverse=True)[:25]:
        print(f"   {v['name'][:22]:<24}{v['email'][:30]:<32}"
              f"{len(v.get('files', []))} ملف  {v['subject'][:28]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    if a.stats:
        show_stats()
        return 0

    r = run(dry=a.dry_run, days=a.days, limit=a.limit)
    if r.get("error"):
        print(f"❌ {r['error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
