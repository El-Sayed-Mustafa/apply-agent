"""
تجهيز ملف التقديم للوظايف اللي دُست عليها "✅ قدّم".

  python -m src.prepare              → جهّز كل اللي مستني
  python -m src.prepare --dry-run    → اعرض من غير ما تبعت ولا تسجّل

لكل وظيفة:
  1. السيرة متظبطة عليها (src/customize.py: العنوان، الملخص، صياغة النقط،
     الترتيب) — PDF بشكل FlowCV، ومعاها رسالة باللي اتغيّر
  2. cover letter من Sonnet، بعد الفحص (src/cover.py)
  3. إجابات الأسئلة المعتادة من answers.yaml وسياسة المرتب
كله بيتحفظ في applications/<رقم الوظيفة>/ (في .gitignore) ومتسجّل في
application_documents.

الدفعة 2أ: الملف بيتبعتلك على تليجرام وإنت تقدّم بنفسك (status = manual).
الدفعة 2ب: Ashby بيتملى أوتوماتيك وبيستنى موافقتك على الإرسال.

بيشتغل على جهازك بس: محتاج answers.yaml (ملف خاص) ومفتاح Claude.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from . import answers, cover, render, tailor, targeting, telegram
from .main import get_client

load_dotenv()

ROOT = Path("applications")
BATCH = 5


def ready() -> str:
    """الشروط المحلية. رجّع "" لو تمام، أو السبب."""
    if not answers.PATH.exists():
        return "answers.yaml مش موجود"
    if not os.getenv("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY مش في .env"
    return ""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def answer_sheet(job: dict, facts: dict | None, policy: dict) -> dict:
    """الإجابات المعتادة لوظيفة بعينها — كلها من answers.yaml والسياسة."""
    country, _ = targeting.detect_country(job.get("location"))
    remote = (job.get("remote_type") or "") == "remote"
    local = answers.LOCAL_CURRENCY.get(country) if not remote else None
    expected = answers.expected_text(job, facts, country, policy, local)
    usd = answers.in_currency(answers.expected_salary(job, facts, country, policy),
                              "USD", policy)
    minimum = answers.in_currency(
        answers.minimum_acceptable(job, country, policy),
        local or answers.band(job, country, policy)["currency"], policy)
    sheet = {
        "Full name": f"{policy.get('first_name', '')} {policy.get('last_name', '')}".strip(),
        "Email": policy.get("email", ""),
        "Phone": policy.get("phone", ""),
        "Location": f"{policy.get('city', '')}, {policy.get('country', '')}".strip(", "),
        "LinkedIn": policy.get("linkedin", ""),
        "GitHub": policy.get("github", ""),
        "Portfolio": policy.get("portfolio", ""),
        "Years of experience": policy.get("years_of_experience", ""),
        "Work authorization": answers.work_authorization(country, remote, policy),
        "Requires sponsorship": "No" if (remote or country == "Egypt")
                                else policy.get("requires_sponsorship", ""),
        "Willing to relocate": policy.get("relocation_note", "")
                               or policy.get("willing_to_relocate", ""),
        "Notice period": policy.get("notice_period", ""),
        "Earliest start date": policy.get("earliest_start_date", ""),
        "Expected salary": expected + ("" if expected.startswith("USD") else f" (≈ {usd})"),
        "Minimum acceptable salary": minimum,
    }
    return {k: v for k, v in sheet.items() if v}


def relocation_line(job: dict) -> str:
    country, _ = targeting.detect_country(job.get("location"))
    if (job.get("remote_type") or "") == "remote" or country == "Egypt":
        return ""
    return ("I am open to relocating, with employer visa sponsorship and "
            "relocation support.")


def _cv_pdf(job: dict) -> tuple[bytes, str, dict, list[str], float]:
    """
    السيرة متظبطة على الوظيفة دي — بتتعمل هنا بس، بعد ما دُست "قدّم".
    رجّع (الملف، الاسم، الخطة، اللي اترفض، التكلفة). لو التظبيط فشل،
    السيرة الأصلية.
    """
    from . import customize
    cv = tailor.full()
    plan, rejected, spent = customize.plan_for(job)
    bullets, _ = tailor.load_catalogue()
    tailored = customize.apply(cv, plan, job.get("description") or "")
    pdf = render.build(tailored, bullets, customize.chosen_ids(cv, plan)).getvalue()
    return pdf, render.filename(job), plan, rejected, spent


def _record(db, job_id: int, kind: str, path: Path | None = None,
            data: bytes | None = None, content: str | None = None) -> None:
    db.table("application_documents").insert({
        "job_id": job_id, "kind": kind,
        "path": str(path) if path else None,
        "sha256": _sha(data) if data else None,
        "content": content,
    }).execute()


def package_text(job: dict, sheet: dict, letter_ok: bool) -> str:
    lines = [f"📦 <b>ملف التقديم جاهز</b>",
             f"<b>{telegram.esc(job.get('title'))}</b> — {telegram.esc(job.get('company_name'))}",
             telegram.esc(job.get("location") or ""), ""]
    if job.get("ats") in ("linkedin_job", "linkedin_post"):
        lines.append("لينكدإن: قدّم إنت من اللينك (Easy Apply مش أوتوماتيك).")
    else:
        lines.append("قدّم من اللينك. الملء الأوتوماتيك جاي في الدفعة 2ب.")
    if not letter_ok:
        lines.append("⚠️ الـcover letter اترفض في الفحص — مش مرفق.")
    lines.append("")
    lines.append("<b>الإجابات:</b>")
    for k, v in sheet.items():
        if k in ("Full name", "Email", "Phone", "LinkedIn", "GitHub", "Portfolio"):
            continue
        lines.append(f"• {telegram.esc(k)}: <code>{telegram.esc(v)}</code>")
    if job.get("url"):
        lines += ["", f'<a href="{telegram.esc(job["url"])}">🔗 صفحة التقديم</a>']
    return "\n".join(lines)


def prepare_one(db, job: dict, facts: dict | None, policy: dict,
                dry: bool = False, manual: bool = True) -> dict:
    """
    manual=True  → الملف كله + "قدّم من اللينك" (إنت اللي هتقدّم)
    manual=False → السيرة والخطاب بس؛ الفورم هيتملى (src/apply.py)
    """
    folder = ROOT / str(job["id"])
    pdf, fname, plan, rejected, cv_cost = _cv_pdf(job)
    letter, problems, spent = cover.write(job, relocation_line(job))
    spent += cv_cost
    sheet = answer_sheet(job, facts, policy)
    if dry:
        return {"cv": fname, "letter": letter, "problems": problems,
                "sheet": sheet, "cost": spent, "plan": plan, "rejected": rejected}

    folder.mkdir(parents=True, exist_ok=True)
    cv_path = folder / fname
    cv_path.write_bytes(pdf)
    _record(db, job["id"], "cv", cv_path, pdf)
    if letter:
        lp = folder / "cover-letter.txt"
        lp.write_text(letter, encoding="utf-8")
        _record(db, job["id"], "cover_letter", lp, letter.encode(), letter)
    (folder / "cv-changes.json").write_text(
        json.dumps({"plan": plan, "rejected": rejected}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    sheet_json = json.dumps(sheet, ensure_ascii=False, indent=1)
    (folder / "answers.json").write_text(sheet_json, encoding="utf-8")
    _record(db, job["id"], "answers", folder / "answers.json",
            sheet_json.encode(), sheet_json)

    token, chat = telegram._config()
    from io import BytesIO
    # الإجابات رسالة لوحدها: كابشن المستند حده 1024 حرف وكانت هتتقص
    telegram.send_document(
        BytesIO(pdf), fname,
        f"📄 السيرة المتظبطة — {telegram.esc(job.get('title'))}", token, chat)
    from . import customize
    telegram.send(customize.changes_text(tailor.full(), plan, rejected), token, chat)
    if manual:
        telegram.send(package_text(job, sheet, bool(letter)), token, chat)
    if letter:
        telegram.send(f"✉️ <b>Cover letter</b> — اضغط عليه يتنسخ\n"
                      f"<pre>{telegram.esc(letter)}</pre>", token, chat)
    return {"cv": fname, "cv_path": str(cv_path), "letter": bool(letter),
            "letter_text": letter, "problems": problems, "cost": spent}


def run(db=None, dry: bool = False, limit: int = BATCH,
        skip_ats: tuple = (), skip_ids: set | None = None) -> dict:
    why = ready()
    if why:
        return {"skipped": why}
    db = db or get_client()
    pending = (db.table("applications").select("job_id").eq("status", "approved")
               .order("decided_at").limit(limit).execute().data)
    if not pending:
        return {"prepared": 0}
    policy = answers.load()
    done = failed = 0
    cost = 0.0
    for p in pending:
        jid = p["job_id"]
        job = (db.table("jobs").select("id,title,company_name,location,remote_type,"
                                       "description,url,ats")
               .eq("id", jid).execute().data or [None])[0]
        if not job or job.get("ats") in skip_ats or jid in (skip_ids or ()):
            continue
        sc = (db.table("scores").select("facts").eq("job_id", jid)
              .order("created_at", desc=True).limit(1).execute().data)
        facts = sc[0].get("facts") if sc else None
        try:
            r = prepare_one(db, job, facts, policy, dry)
            cost += r.get("cost", 0)
            print(f"   📦 {job['title'][:40]:<42} cv ✓ · letter "
                  f"{'✓' if r.get('letter') else '✗ ' + '; '.join(r.get('problems', []))[:60]}")
            if not dry:
                db.table("applications").update(
                    {"status": "manual",
                     "updated_at": datetime.now(timezone.utc).isoformat()}
                ).eq("job_id", jid).eq("status", "approved").execute()
            done += 1
        except Exception as exc:
            failed += 1
            print(f"   ✗ {job['title'][:40]} — {type(exc).__name__}: {exc}"[:160])
            if not dry:
                db.table("applications").update(
                    {"status": "failed", "notes": f"prepare: {exc}"[:500]}
                ).eq("job_id", jid).eq("status", "approved").execute()
    print(f"\n📊 اتجهّز {done} · فشل {failed} · Sonnet ≈ ${cost:.3f}")
    return {"prepared": done, "failed": failed, "cost": round(cost, 4)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=BATCH)
    a = ap.parse_args()
    r = run(dry=a.dry_run, limit=a.limit)
    if r.get("skipped"):
        print(f"⏭ {r['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def letter_pdf(job: dict, text: str, folder: Path | None = None) -> str:
    """
    الخطاب كـPDF — لفورمات بتطلب cover letter كملف (Lever و Greenhouse
    أحيانًا). نفس النص اللي اتفحص، صفحة واحدة بخط عادي.
    """
    from html import escape
    from playwright.sync_api import sync_playwright

    folder = folder or ROOT / str(job["id"])
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / render.filename(job).replace("Elsayed-Mustafa-", "Elsayed-Mustafa-Cover-Letter-", 1)
    paras = "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>"
                    for p in text.strip().split("\n\n"))
    html = ("<html><body style=\"font:11.5pt/1.55 Georgia,serif;margin:0;color:#111\">"
            f"<div style=\"padding:28mm 24mm\">{paras}</div></body></html>")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page()
        page.set_content(html)
        page.pdf(path=str(path), format="A4")
        b.close()
    return str(path)
