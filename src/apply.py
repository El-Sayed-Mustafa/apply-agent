"""
التقديم: من "✅ قدّم" لحد "اتبعت".

  python -m src.apply              → كل الخطوات المستنية
  python -m src.apply --dry-run    → اعرض الوضع من غير ما تعمل حاجة

الرحلة لوظيفة على Ashby:
  1. دُست "✅ قدّم"            applications.status = approved
  2. السيرة والخطاب بيتعملوا  (src/prepare.py + src/customize.py)
  3. الأسئلة بتتجاوب           (src/form_answers.py) — اللي مش معروف بيتسألك
                               على تليجرام، وترد عليه Reply
  4. الفورم بيتملى ويتصوّر     متصفح مخفي، **من غير إرسال**
                               → صورة + الإجابات + [📤 ابعت] [🛑 متبعتش]
                               applications.status = ready
  5. دُست "📤 ابعت"            طلب الموافقة approved (صالح 24 ساعة)
  6. الإرسال                   متصفح ظاهر، نفس الإجابات، Submit، صورة دليل
                               applications.status = applied
أي حاجة مش ماشية (الإعلان اتقفل، تحقق/CAPTCHA، حقل مش مدعوم) → status =
manual والملف كله معاك تقدّم بنفسك. الوظايف اللي مش Ashby → manual على طول.

ضمانة الإرسال مرة واحدة: طلب الموافقة بيتقفل (approved → done) **قبل**
الضغط على Submit. لو حصل عطل في النص، مفيش إعادة أوتوماتيك.

الحالة المحلية لكل وظيفة في applications/<id>/form.json (في .gitignore).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import answers, ashby, ats, form_answers, prepare, telegram
from .main import get_client

EXPIRES_H = 24
LOCK = Path("state/apply.lock")
LOCK_MAX_AGE = 25 * 60
YES = re.compile(r"^(y|yes|yeah|yep|ok|نعم|ايوه|أيوه|ايوة|آه|اه|اة|تمام|موافق)\b", re.I)
NO = re.compile(r"^(n|no|nope|لا|لأ|لاء|مش موافق|لا شكرا)\b", re.I)
HIDE = {"_systemfield_name", "_systemfield_email"}
# الطريقة القديمة: صورة + 📤 والإرسال من هنا (Ashby بس). الافتراضي: إضافة كروم
AUTOSUBMIT = os.getenv("APPLY_AUTOSUBMIT") == "1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


# ── الحالة المحلية ──────────────────────────────────────────────────────

def _path(jid: int) -> Path:
    return prepare.ROOT / str(jid) / "form.json"


def load_state(jid: int) -> dict:
    try:
        return json.loads(_path(jid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(jid: int, st: dict) -> None:
    p = _path(jid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


# ── ردودك ───────────────────────────────────────────────────────────────

def parse_reply(field: dict, text: str):
    """ردك → قيمة الحقل. None = مش فاهم."""
    t = (text or "").strip()
    if not t:
        return None
    typ, opts = field["type"], field.get("options") or []
    if typ == "Boolean":
        return True if YES.search(t) else False if NO.search(t) else None
    if typ in ("ValueSelect", "MultiValueSelect"):
        picks = []
        for part in (re.split(r"[,،\s]+", t) if typ == "MultiValueSelect" else [t]):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= len(opts):
                picks.append(opts[int(part) - 1])
                continue
            hit = next((o for o in opts if o.strip().lower() == part.lower()), None) \
                or next((o for o in opts if o.strip().lower().startswith(part.lower())), None)
            if hit:
                picks.append(hit)
            elif YES.search(part) or NO.search(part):
                hit = form_answers.pick(opts, r"^yes\b" if YES.search(part) else r"^no\b")
                if hit:
                    picks.append(hit)
        if not picks:
            return None
        return picks if typ == "MultiValueSelect" else picks[0]
    if typ == "Number":
        n = re.sub(r"[^\d.]", "", t)
        return n or None
    return t


def question_text(job: dict, f: dict) -> str:
    lines = [f"❓ <b>سؤال في فورم التقديم</b>",
             f"{telegram.esc(job.get('title'))} — {telegram.esc(job.get('company_name'))}", "",
             f"<b>{telegram.esc(f['title'])}</b>"]
    desc = re.sub(r"<[^>]+>", " ", f.get("description") or "").strip()
    if desc:
        lines.append(f"<i>{telegram.esc(telegram.clip(desc, 300))}</i>")
    lines.append("")
    if f["type"] == "Boolean":
        lines.append("رد بـ <b>Yes</b> أو <b>No</b>")
    elif f.get("options"):
        lines += [f"{i}. {telegram.esc(o.strip())}" for i, o in enumerate(f["options"], 1)]
        lines.append("\nرد برقم الاختيار" + (" (أو أكتر، بينهم فاصلة)"
                                            if f["type"] == "MultiValueSelect" else ""))
    else:
        lines.append("رد بالإجابة زي ما هتتكتب في الفورم")
    lines.append("<i>(Reply على الرسالة دي)</i>")
    return "\n".join(lines)


def ask_pending(job: dict, st: dict, token: str, chat: str) -> int:
    by = {f["path"]: f for f in st["fields"]}
    sent = 0
    for path in form_answers.pending(st["answers"]):
        if path in st["questions"]:
            continue
        mid = telegram.send(question_text(job, by[path]), token, chat,
                            markup={"force_reply": True,
                                    "input_field_placeholder": "إجابتك"})
        st["questions"][path] = mid
        sent += 1
    return sent


def read_replies(db, states: dict[int, dict], jobs: dict[int, dict],
                 token: str, chat: str) -> set[int]:
    """طابق ردودك (tg_messages) على الأسئلة. رجّع الوظايف اللي اتغيّرت."""
    where = {mid: (jid, path) for jid, st in states.items()
             for path, mid in st.get("questions", {}).items()}
    if not where:
        return set()
    rows = (db.table("tg_messages").select("id,reply_to_id,text")
            .is_("consumed_at", "null").in_("reply_to_id", list(where))
            .order("id").execute().data)
    changed = set()
    for r in rows:
        jid, path = where[r["reply_to_id"]]
        st = states[jid]
        f = next(x for x in st["fields"] if x["path"] == path)
        value = parse_reply(f, r["text"])
        db.table("tg_messages").update({"consumed_at": _iso()}).eq("id", r["id"]).execute()
        if value is None:
            telegram.send("مش فاهم الرد ده — هبعت السؤال تاني.", token, chat)
            st["questions"].pop(path, None)
        else:
            st["answers"][path] = form_answers.ans(value, "you")
            if f["type"] != "LongText":
                form_answers.learn(f["title"], form_answers._ctx(jobs[jid], {})["scope"], value)
        changed.add(jid)
    return changed


# ── الملخص قبل الإرسال ──────────────────────────────────────────────────

ICON = {"profile": "👤", "policy": "📏", "learned": "🧠", "you": "🗣",
        "claude": "✍️", "letter": "✉️"}


def summary(job: dict, st: dict) -> str:
    lines = [f"📝 <b>الفورم اتملى — مستني موافقتك</b>",
             f"<b>{telegram.esc(job.get('title'))}</b> — {telegram.esc(job.get('company_name'))}", ""]
    for f in st["fields"]:
        a = st["answers"].get(f["path"]) or {}
        v = a.get("value")
        if f["path"] in HIDE or v in (None, "", []) or a.get("source") == "skip":
            continue
        if f["type"] == "File":
            v = Path(str(v)).name
        elif isinstance(v, bool):
            v = "Yes" if v else "No"
        elif isinstance(v, list):
            v = ", ".join(v)
        lines.append(f"{ICON.get(a.get('source'), '•')} <b>{telegram.esc(telegram.clip(f['title'], 90))}</b>")
        lines.append(f"   {telegram.esc(telegram.clip(str(v), 700))}")
    lines += ["", f"⏳ الموافقة صالحة {EXPIRES_H} ساعة. الإرسال بيحصل في التشغيلة الجاية "
                  "(كل نص ساعة).",
              "👤 بياناتك · 📏 قاعدة · 🧠 جاوبتها قبل كده · 🗣 ردك · ✍️ Sonnet من سيرتك"]
    return "\n".join(lines)


# ── المراحل ─────────────────────────────────────────────────────────────

def _set_status(db, jid: int, status: str, note: str | None = None, **extra) -> None:
    row = {"status": status, "updated_at": _iso(), **extra}
    if note:
        row["notes"] = note[:500]
    db.table("applications").update(row).eq("job_id", jid).execute()


COPY_MAX = 256          # حد تليجرام لنص زرار النسخ


def copy_kit(job: dict, st: dict) -> list[tuple[str, dict | None]]:
    """
    الإجابات للنسخ. رجّع [(نص، أزرار)] — كل رسالة تحت حد تليجرام.

    17 نوفمبر على أندرويد: <pre> القصير مابيظهرش عليه COPY CODE، والضغط
    على <code> مابينسخش. اللي اشتغل:
      · القصير → زرار "📋 العنوان" (copy_text) بينسخ الإجابة دي بالظبط
      · الطويل → <pre>، وعليه COPY CODE
    الاختيارات (Yes/No، dropdown) مكتوبة عشان تختارها، مش للنسخ.
    """
    head = (f"📋 <b>للنسخ</b> — دوس على زرار 📋 تحت تتنسخ الإجابة · الطويل عليه COPY CODE\n"
            f"<b>{telegram.esc(job.get('title'))}</b> — {telegram.esc(job.get('company_name'))}")
    url = job.get("url")
    if url:
        link = ats.application_url(url, job.get("company_name"))
        head += f'\n<a href="{telegram.esc(link)}">🔗 صفحة التقديم</a>'
    blocks, buttons = [], []
    for f in st.get("fields") or []:
        a = (st.get("answers") or {}).get(f["path"]) or {}
        v = a.get("value")
        title = f"<b>{telegram.esc(telegram.clip(f['title'], 120))}</b>"
        if a.get("source") == "manual":
            blocks.append(f"{title}\n✋ ده بإيدك (ملف أو حاجة السيستم مايعرفهاش)")
            continue
        if v in (None, "", []) or a.get("source") == "skip":
            continue
        if f["type"] == "File":
            blocks.append(f"{title}\n📎 ارفع: {telegram.esc(Path(str(v)).name)} (الملف اللي فوق)")
        elif isinstance(v, bool):
            blocks.append(f"{title}\n☑️ اختار: <b>{'Yes' if v else 'No'}</b>")
        elif f["type"] in ("ValueSelect", "MultiValueSelect") or isinstance(v, list):
            v = ", ".join(v) if isinstance(v, list) else str(v)
            blocks.append(f"{title}\n☑️ اختار: <b>{telegram.esc(v.strip())}</b>")
        elif "\n" in str(v) or len(str(v)) > COPY_MAX:
            blocks.append(f"{title}\n<pre>{telegram.esc(str(v))}</pre>")
        else:
            blocks.append(f"{title}\n📋 {telegram.esc(str(v))}")
            buttons.append([{"text": "📋 " + telegram.clip(f["title"], 40),
                             "copy_text": {"text": str(v)}}])
    out, cur = [], head
    for b in blocks:
        if len(cur) + len(b) + 2 > 3900:
            out.append(cur)
            cur = b
        else:
            cur += "\n\n" + b
    out.append(cur)
    # الأزرار على أول رسالة — فيها الإجابات القصيرة بالترتيب
    return [(m, {"inline_keyboard": buttons} if i == 0 and buttons else None)
            for i, m in enumerate(out)]


def to_manual(db, job: dict, why: str, token: str, chat: str,
              facts=None, policy=None, have_package: bool = False,
              st: dict | None = None) -> None:
    """التقديم الأوتوماتيك مش ماشي — الملف ليك وإنت تقدّم."""
    if st:
        for msg, kb in copy_kit(job, st):
            telegram.send(msg, token, chat, markup=kb)
    if not have_package:
        prepare.prepare_one(db, job, facts, policy or answers.load(), manual=True)
    else:
        telegram.send(f"✋ <b>قدّم بنفسك</b> — {telegram.esc(job.get('title'))}\n"
                      f"السبب: {telegram.esc(why)}\nالسيرة والخطاب اللي فوق جاهزين."
                      + (f'\n<a href="{telegram.esc(job["url"])}">🔗 صفحة التقديم</a>'
                         if job.get("url") else ""), token, chat)
    _set_status(db, job["id"], "manual", why)


def start(db, job: dict, facts, policy, token, chat) -> str:
    """أول مرة: افتح الفورم، جهّز الملف، جاوب. رجّع المرحلة."""
    site = ats.site_of(job["url"], job.get("company_name"))
    try:
        fields = ats.form(job["url"], job.get("company_name"))
    except Exception as exc:
        to_manual(db, job, f"الفورم مقريش: {type(exc).__name__}", token, chat, facts, policy)
        return "manual"
    if fields is None:
        telegram.send(f"🚪 الإعلان اتقفل — {telegram.esc(job.get('title'))} "
                      f"({telegram.esc(job.get('company_name'))})", token, chat)
        _set_status(db, job["id"], "failed", "الإعلان اتقفل قبل التقديم")
        return "closed"
    # الإرسال الأوتوماتيك (Ashby بس) محتاج كل حقل؛ الإضافة لأ — اللي مش
    # بتعرفه بيتعلّم "املاه بإيدك" وإنت بتراجع
    bad = ashby.unsupported(fields) if site == "ashby" and AUTOSUBMIT else []
    if bad:
        to_manual(db, job, "حقل مش مدعوم: " + bad[0]["type"], token, chat, facts, policy)
        return "manual"
    pkg = prepare.prepare_one(db, job, facts, policy, manual=False)
    files = {"cv": pkg["cv_path"], "letter": pkg.get("letter_text")}
    if pkg.get("letter_text") and any(f["type"] == "File" and "cover" in f["title"].lower()
                                      for f in fields):
        files["letter_pdf"] = prepare.letter_pdf(job, pkg["letter_text"])
    amap, _ = form_answers.answer_all(fields, job, facts, policy, files)
    st = {"stage": "asking", "fields": fields, "answers": amap, "questions": {},
          "files": files, "url": job["url"], "site": site,
          "company": job.get("company_name"), "started_at": _iso()}
    save_state(job["id"], st)
    return "asking"


def ready_for_extension(db, job: dict, st: dict, token, chat) -> str:
    """
    الإجابات خلصت. الإرسال بقى من كروم بتاعك (extension/): الإضافة بتملا
    وإنت بتدوس Submit. على الموبايل: قايمة النسخ.

    17 نوفمبر: الإرسال الأوتوماتيك على Cohere ماتأكدش (reCAPTCHA غالبًا)،
    ومش هنتحايل عليه. متصفحك وضغطتك = مفيش حاجة تتمسك.
    APPLY_AUTOSUBMIT=1 بيرجّع الطريقة القديمة (صورة + 📤).
    """
    telegram.send(f"✅ <b>جاهز للتقديم</b> — {telegram.esc(job.get('title'))} "
                  f"({telegram.esc(job.get('company_name'))})\n"
                  "💻 على الكمبيوتر: افتح صفحة التقديم ودوس «📋 املا من Apply Agent»، "
                  "راجع، ودوس Submit بنفسك.\n"
                  "📱 على الموبايل: الأزرار اللي تحت.", token, chat)
    for msg, kb in copy_kit(job, st):
        telegram.send(msg, token, chat, markup=kb)
    _set_status(db, job["id"], "ready", "جاهز للإضافة")
    st["stage"] = "extension"
    save_state(job["id"], st)
    return "extension"


def advance(db, job: dict, st: dict, facts, policy, token, chat) -> str:
    """فيه أسئلة؟ اسأل. مفيش؟ جاهز للإضافة (أو، قديمًا: املا وصوّر واطلب الموافقة)."""
    if form_answers.pending(st["answers"]):
        ask_pending(job, st, token, chat)
        st["stage"] = "asking"
        save_state(job["id"], st)
        return "asking"
    if not AUTOSUBMIT or st.get("site", "ashby") != "ashby":
        return ready_for_extension(db, job, st, token, chat)

    folder = prepare.ROOT / str(job["id"])
    shot = folder / "form-preview.png"
    problems = ashby.preview(st["url"], st["fields"], st["answers"], shot)
    if problems:
        if shot.exists():
            telegram.send_document(shot.open("rb"), shot.name, "الفورم وقت المشكلة", token, chat)
        to_manual(db, job, "الملء ماكملش: " + "؛ ".join(problems[:3]), token, chat,
                  have_package=True, st=st)
        st["stage"] = "manual"
        save_state(job["id"], st)
        return "manual"

    data = shot.read_bytes()
    prepare._record(db, job["id"], "form_preview", shot, data)
    req = db.table("approval_requests").insert({
        "job_id": job["id"], "kind": "submit", "status": "pending",
        "payload": {p: a.get("value") for p, a in st["answers"].items()
                    if p not in HIDE and a.get("source") != "skip"
                    and not isinstance(a.get("value"), (dict,))},
        "expires_at": _iso(_now() + timedelta(hours=EXPIRES_H)),
    }).execute().data[0]
    telegram.send_document(shot.open("rb"), f"form-{job['id']}.png",
                           f"🖼 الفورم بعد الملء — {telegram.esc(job.get('title'))}",
                           token, chat)
    mid = telegram.send(summary(job, st), token, chat,
                        markup=telegram.submit_keyboard(req["id"]))
    db.table("approval_requests").update({"message_id": mid}).eq("id", req["id"]).execute()
    _set_status(db, job["id"], "ready")
    st.update(stage="preview", approval_id=req["id"])
    save_state(job["id"], st)
    return "preview"


def send_approved(db, token, chat) -> int:
    """الطلبات اللي دُست فيها "📤 ابعت". بنقفل الطلب الأول وبعدين نبعت."""
    rows = (db.table("approval_requests").select("id,job_id,expires_at")
            .eq("kind", "submit").eq("status", "approved").execute().data)
    done = 0
    for r in rows:
        claimed = (db.table("approval_requests").update({"status": "done"})
                   .eq("id", r["id"]).eq("status", "approved").execute().data)
        if not claimed:
            continue                         # تشغيلة تانية خدته
        jid = r["job_id"]
        job = db.table("jobs").select("id,title,company_name,url,ats").eq("id", jid).execute().data[0]
        st = load_state(jid)
        if not st:
            to_manual(db, job, "حالة الفورم مش موجودة على الجهاز", token, chat, have_package=True)
            continue
        shot = prepare.ROOT / str(jid) / "submitted.png"
        try:
            ok, why = ashby.submit(st["url"], st["fields"], st["answers"], shot)
        except Exception as exc:
            ok, why = False, f"عطل: {type(exc).__name__}: {exc}"[:200]
        if shot.exists():
            prepare._record(db, jid, "submission_evidence", shot, shot.read_bytes())
        if ok:
            _set_status(db, jid, "applied", None, submitted_at=_iso(), confirmed=True)
            st["stage"] = "sent"
            telegram.send_document(shot.open("rb"), f"submitted-{jid}.png",
                                   f"✅ <b>اتبعت</b> — {telegram.esc(job.get('title'))} "
                                   f"({telegram.esc(job.get('company_name'))})", token, chat)
            done += 1
        else:
            if shot.exists():
                telegram.send_document(shot.open("rb"), f"not-sent-{jid}.png",
                                       "⚠️ الصفحة وقت المشكلة", token, chat)
            to_manual(db, job, f"ماتبعتش: {why}", token, chat, have_package=True, st=st)
            st["stage"] = "manual"
        save_state(jid, st)
    return done


def close_rejected_and_expired(db, token, chat) -> None:
    ready = {a["job_id"] for a in db.table("applications").select("job_id")
             .eq("status", "ready").execute().data}
    if not ready:
        return
    now = _iso()
    stale = (db.table("approval_requests").select("id,job_id").eq("kind", "submit")
             .eq("status", "pending").lt("expires_at", now).execute().data)
    for r in stale:
        db.table("approval_requests").update({"status": "expired"}).eq("id", r["id"]) \
            .eq("status", "pending").execute()
    rejected = (db.table("approval_requests").select("id,job_id").eq("kind", "submit")
                .eq("status", "rejected").in_("job_id", list(ready)).execute().data)
    for r in stale + rejected:
        if r["job_id"] not in ready:
            continue
        why = "الموافقة انتهت" if r in stale else "دُست متبعتش"
        _set_status(db, r["job_id"], "manual", why)
        telegram.send(f"🛑 مش هيتبعت ({why}). الملف معاك لو حبيت تقدّم بنفسك.", token, chat)
        ready.discard(r["job_id"])


# ── التشغيلة ────────────────────────────────────────────────────────────

def _lock() -> bool:
    try:
        if LOCK.exists() and time.time() - LOCK.stat().st_mtime < LOCK_MAX_AGE:
            return False
    except OSError:
        pass
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()))
    return True


def run(db=None, dry: bool = False) -> dict:
    why = prepare.ready()
    if why:
        return {"skipped": why}
    if not dry and not _lock():
        return {"skipped": "تشغيلة تانية شغالة"}
    try:
        return _run(db or get_client(), dry)
    finally:
        if not dry:
            LOCK.unlink(missing_ok=True)


def _run(db, dry: bool) -> dict:
    out = {"sent": 0, "asking": 0, "preview": 0, "manual": 0, "closed": 0}
    approved = [a["job_id"] for a in db.table("applications").select("job_id")
                .eq("status", "approved").order("decided_at").execute().data]
    jobs = {j["id"]: j for j in (db.table("jobs").select(
        "id,title,company_name,location,remote_type,description,url,ats")
        .in_("id", approved).execute().data if approved else [])}
    form_ids = [j for j in approved if j in jobs
                and ats.site_of(jobs[j].get("url"), jobs[j].get("company_name"))]
    if dry:
        for jid in approved:
            st = load_state(jid)
            print(f"   {jid} {jobs.get(jid, {}).get('title', '?')[:40]:<42} "
                  f"{ats.site_of(jobs[jid].get('url'), jobs[jid].get('company_name')) if jid in form_ids else 'يدوي'} · {st.get('stage', 'جديدة')}"
                  + (f" · أسئلة {len(form_answers.pending(st['answers']))}" if st else ""))
        return out

    token, chat = telegram._config()
    policy = answers.load()
    close_rejected_and_expired(db, token, chat)
    out["sent"] = send_approved(db, token, chat)

    # اللي مش Ashby: الملف وتقدّم بنفسك (زي الدفعة 2أ)
    manual_ids = [j for j in approved if j not in form_ids]
    if manual_ids:
        r = prepare.run(db, skip_ids=set(form_ids), limit=prepare.BATCH)
        out["manual"] += r.get("prepared", 0)

    states = {jid: load_state(jid) for jid in form_ids}
    changed = read_replies(db, {k: v for k, v in states.items() if v}, jobs, token, chat)
    for jid in form_ids:
        job = jobs[jid]
        sc = (db.table("scores").select("facts").eq("job_id", jid)
              .order("created_at", desc=True).limit(1).execute().data)
        facts = sc[0].get("facts") if sc else None
        try:
            st = states[jid]
            if not st:
                stage = start(db, job, facts, policy, token, chat)
                if stage != "asking":
                    out[stage] = out.get(stage, 0) + 1
                    continue
                st = load_state(jid)
            elif st.get("stage") != "asking":
                continue
            elif jid not in changed and form_answers.pending(st["answers"]) and \
                    all(p in st["questions"] for p in form_answers.pending(st["answers"])):
                out["asking"] += 1
                continue                      # لسه مستني ردك
            stage = advance(db, job, st, facts, policy, token, chat)
            out[stage] = out.get(stage, 0) + 1
        except Exception as exc:
            print(f"   ✗ {job['title'][:40]} — {type(exc).__name__}: {exc}"[:200])
            _set_status(db, jid, "failed", f"apply: {type(exc).__name__}: {exc}")
    print(f"📊 اتبعت {out['sent']} · جاهز للإضافة {out.get('extension', 0)} · مستني موافقتك {out['preview']} · "
          f"مستني ردك {out['asking']} · يدوي {out['manual']} · اتقفل {out['closed']}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    r = run(dry=a.dry_run)
    if r.get("skipped"):
        print(f"⏭ {r['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
