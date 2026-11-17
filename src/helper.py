"""
المساعد المحلي لإضافة كروم (extension/) — بيدّيها إجابات الوظيفة والسيرة.

  python -m src.helper        شغّال على 127.0.0.1:8765 لحد ما تقفله

ليه مساعد محلي ومش الإضافة تكلّم Supabase على طول: الإجابات (المرتب،
تصريح العمل) والسِّيَر على جهازك في applications/ ومش متجاهلة لأي مكان
تاني، ومفتاح Supabase مالوش مكان جوّه إضافة.

الأمان:
  · بيسمع على 127.0.0.1 بس
  · بيرفض أي Host غير 127.0.0.1:8765 / localhost:8765 (ضد DNS rebinding)
  · كل طلب لازم معاه X-Token. التوكن في state/helper_token، وبيتكتب في
    extension/config.js عشان الإضافة تقراه — الاتنين برّه git
  · مفيش CORS headers، فصفحة ويب عادية متقدرش تقرا أي رد

الإرسال نفسه مش هنا خالص: الإضافة بتملا، وإنت اللي بتدوس Submit.
/submitted بيسجّل بس إنه اتبعت، بعد ما الصفحة نفسها أكدت.
"""
from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import os
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import ats, prepare

PORT = int(os.getenv("HELPER_PORT", "8765"))
TOKEN_FILE = Path("state/helper_token")
CONFIG_JS = Path(__file__).resolve().parent.parent / "extension" / "config.js"
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


def token() -> str:
    """التوكن، ويتعمل أول مرة. config.js بيتكتب كل مرة عشان يفضل مطابق."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
    CONFIG_JS.write_text(
        "// بيتكتب من src/helper.py — مش في git\n"
        f"self.APPLY_AGENT = {json.dumps({'url': f'http://127.0.0.1:{PORT}', 'token': tok})};\n",
        encoding="utf-8")
    return tok


def find_state(page_url: str, root: Path | None = None) -> tuple[int, dict] | None:
    """
    الوظيفة اللي صفحتها مفتوحة: نفس الموقع ونفس رقم الإعلان — من أي لينك
    ليه (صفحة البورد، الـembed، /apply).
    """
    want = ats.posting_key(page_url)
    if not want:
        return None
    root = root or prepare.ROOT
    for f in sorted(root.glob("*/form.json")):
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if ats.posting_key(st.get("url"), st.get("company")) == want:
            return int(f.parent.name), st
    return None


def build_pack(jid: int, st: dict, job: dict | None = None) -> dict:
    """اللي الإضافة محتاجاه: الخانات، القيم، والملفات نفسها base64."""
    answers, files = {}, {}
    for f in st.get("fields") or []:
        a = (st.get("answers") or {}).get(f["path"]) or {}
        v = a.get("value")
        if a.get("source") == "skip" or v in (None, "", []):
            continue
        if f["type"] == "File":
            p = Path(str(v))
            if p.exists():
                files[f["path"]] = {
                    "name": p.name,
                    "type": mimetypes.guess_type(p.name)[0] or "application/pdf",
                    "b64": base64.b64encode(p.read_bytes()).decode()}
                answers[f["path"]] = p.name
            continue
        answers[f["path"]] = v
    job = job or {}
    return {"site": st.get("site", "ashby"),
            "job": {"id": jid, "title": job.get("title") or st.get("title") or f"#{jid}",
                    "company": job.get("company_name") or ""},
            "fields": [{k: f.get(k) for k in ("path", "type", "title", "required", "options")}
                       for f in st.get("fields") or []],
            "answers": answers, "files": files}


def _job(jid: int) -> dict:
    try:
        from .main import get_client
        rows = get_client().table("jobs").select("id,title,company_name") \
            .eq("id", jid).execute().data
        return rows[0] if rows else {}
    except Exception:
        return {}


def mark_submitted(jid: int, url: str = "") -> dict:
    """الصفحة أكدت الإرسال — سجّله، وبلّغ على تليجرام."""
    from . import apply, telegram
    from .main import get_client
    db = get_client()
    row = db.table("applications").select("status").eq("job_id", jid).execute().data
    if row and row[0]["status"] == "applied":
        return {"ok": True, "already": True}
    now = datetime.now(timezone.utc).isoformat()
    db.table("applications").update({
        "status": "applied", "submitted_at": now, "confirmed": True, "updated_at": now,
        "notes": "اتبعت من إضافة كروم — الصفحة أكدت"}).eq("job_id", jid).execute()
    st = apply.load_state(jid)
    if st:
        st["stage"] = "sent"
        apply.save_state(jid, st)
    job = _job(jid)
    try:
        telegram.send(f"✅ <b>اتبعت واتسجّل</b> — {telegram.esc(job.get('title'))} "
                      f"({telegram.esc(job.get('company_name'))})")
    except Exception:
        pass
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    server_version = "ApplyAgentHelper/1"
    tok = ""

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self) -> bool:
        if self.headers.get("Host") not in HOSTS:
            self._send(403, {"error": "host"})
            return False
        if not hmac.compare_digest(self.headers.get("X-Token", ""), self.tok):
            self._send(401, {"error": "التوكن غلط — اعمل Reload للإضافة"})
            return False
        return True

    def do_GET(self):
        if not self._allowed():
            return
        u = urlparse(self.path)
        if u.path == "/ping":
            return self._send(200, {"ok": True})
        if u.path == "/pack":
            page = (parse_qs(u.query).get("url") or [""])[0]
            found = find_state(page)
            if not found:
                return self._send(404, {"error": "الوظيفة دي مش متجهّزة — دوس «قدّم» عليها في تليجرام الأول"})
            jid, st = found
            return self._send(200, build_pack(jid, st, _job(jid)))
        self._send(404, {"error": "مش موجود"})

    def do_POST(self):
        if not self._allowed():
            return
        path = urlparse(self.path).path
        if path == "/sitejobs":
            # كروت وظايف من صفحة نتايج (extension/sitejobs.js) — فلترة وحفظ
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 500_000)
                payload = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
                    raise ValueError
            except Exception:
                return self._send(400, {"error": "طلب غلط"})
            try:
                from . import sitejobs
                r = sitejobs.ingest_pages(payload, quiet=True)
                return self._send(200, {"ok": True, "kept": r["kept"], "saved": r["saved"]})
            except Exception as exc:
                return self._send(500, {"error": f"{type(exc).__name__}"})
        if path != "/submitted":
            return self._send(404, {"error": "مش موجود"})
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 10_000)
            body = json.loads(self.rfile.read(n) or b"{}")
            jid = int(body["job_id"])
        except Exception:
            return self._send(400, {"error": "طلب غلط"})
        if not prepare.ROOT.joinpath(str(jid), "form.json").exists():
            return self._send(404, {"error": "الوظيفة مش عندنا"})
        try:
            return self._send(200, mark_submitted(jid, body.get("url") or ""))
        except Exception as exc:
            return self._send(500, {"error": f"{type(exc).__name__}"})

    def log_message(self, fmt, *args):          # من غير ضوضاء في التيرمنال
        pass


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    Handler.tok = token()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"🟢 المساعد شغّال على 127.0.0.1:{PORT} — سيبه مفتوح وإنت بتقدّم.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
