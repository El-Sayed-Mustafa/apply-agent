"""
الإرسال على تليجرام.

بنستخدم Bot API مباشرة — نداء HTTP عادي، من غير أي مكتبة. سطرين كود
مقابل اعتمادية كاملة مالهاش لازمة.

القناة دي هي المكان الوحيد اللي المنظومة بتكلمك منه. عشان كده فيها
حاجتين مهمين:
  · الرسالة لازم تتقري في ثانيتين على موبايل — سكور، شركة، فجوة، لينك
  · مستحيل تتبعت مرتين — الضمانة في الداتابيز مش في الكود
"""
from __future__ import annotations

import html
import os
import re
import time

import requests
from pathlib import Path

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 20

VERDICT_ICON = {
    "strong": "🟢", "good": "🟢", "partial": "🟡", "weak": "🟠", "no": "🔴",
}


def _config() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        raise RuntimeError("ناقص TELEGRAM_BOT_TOKEN أو TELEGRAM_CHAT_ID")
    return token, chat


def call(method: str, payload: dict, token: str | None = None) -> dict:
    """نداء واحد على الـ Bot API. بيرمي استثناء لو تليجرام رفض."""
    token = token or _config()[0]
    r = requests.post(API.format(token=token, method=method),
                      json=payload, timeout=TIMEOUT)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"تليجرام رفض: {data.get('description', r.text)[:200]}")
    return data["result"]


def esc(text: str | None) -> str:
    """تليجرام بيرفض الرسالة كلها لو فيه < أو & غير مهرّب."""
    return html.escape(str(text or ""), quote=False)


def clip(text: str | None, n: int) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def format_job(job: dict, score: dict) -> str:
    """
    الرسالة. مصمّمة تتقري على موبايل في ثانيتين:
    السكور والشركة في أول سطر، والفجوات قبل اللينك عشان تعرف
    إنت داخل على إيه قبل ما تدوس.
    """
    icon = VERDICT_ICON.get(score.get("verdict"), "⚪")
    s = score.get("score_final") or score.get("score_initial") or 0

    lines = [
        f"{icon} <b>{s}</b> · {esc(job.get('company_name'))}",
        f"<b>{esc(clip(job.get('title'), 90))}</b>",
    ]

    where = " · ".join(filter(None, [
        job.get("location"),
        job.get("remote_type") if job.get("remote_type") != "unknown" else None,
    ]))
    if where:
        lines.append(f"📍 {esc(where)}")

    matched = [m for m in (score.get("matched") or []) if m][:3]
    gaps = [g for g in (score.get("gaps") or []) if g][:3]
    lines.append("")
    if matched:
        lines.append(f"✅ {esc(', '.join(clip(m, 34) for m in matched))}")
    if gaps:
        lines.append(f"⚠️ {esc(', '.join(clip(g, 34) for g in gaps))}")

    if score.get("reasoning"):
        lines.append("")
        lines.append(f"<i>{esc(clip(score['reasoning'], 260))}</i>")

    if job.get("url"):
        lines.append("")
        lines.append(f'<a href="{esc(job["url"])}">🔗 افتح الوظيفة</a>')

    return "\n".join(lines)


def keyboard(job_id: int) -> dict:
    """
    الأزرار تحت الرسالة.

    callback_data محدود بـ 64 بايت عند تليجرام، فبنبعت حرف ورقم بس:
    "a:123". الـ Edge Function بيتحقق من الشكل ده بتعبير صارم قبل
    ما يلمس الداتابيز.
    """
    return {"inline_keyboard": [[
        {"text": "✅ قدّمت",     "callback_data": f"a:{job_id}"},
        {"text": "❌ مش مناسبة", "callback_data": f"s:{job_id}"},
        {"text": "🕐 بعدين",     "callback_data": f"l:{job_id}"},
    ]]}


def send(text: str, token: str | None = None, chat_id: str | None = None,
         markup: dict | None = None) -> int:
    """ابعت رسالة. رجّع message_id."""
    if token is None or chat_id is None:
        token, chat_id = _config()
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],                 # حد تليجرام الصلب
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if markup:
        payload["reply_markup"] = markup
    return call("sendMessage", payload, token)["message_id"]


def send_with_retry(text: str, token: str, chat_id: str, tries: int = 3,
                    markup: dict | None = None) -> int:
    """تليجرام بيرجّع 429 مع retry_after لما تستعجل."""
    last = ""
    for attempt in range(tries):
        try:
            return send(text, token, chat_id, markup)
        except Exception as exc:
            last = str(exc)
            m = re.search(r"retry after (\d+)", last, re.I)
            if m:
                time.sleep(int(m.group(1)) + 1)
                continue
            if "Too Many Requests" in last or "500" in last:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"فشل بعد {tries} محاولات — {last[:150]}")


# ── الإعداد لأول مرة ────────────────────────────────────────────────────

def find_chat_id(token: str) -> list[dict]:
    """
    بيقرا آخر الرسايل اللي وصلت للبوت ويطلّع منها رقم المحادثة.
    عشان كده لازم تبعت رسالة للبوت الأول.
    """
    r = requests.get(API.format(token=token, method="getUpdates"), timeout=TIMEOUT)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"التوكن مرفوض: {data.get('description', '')[:150]}")

    seen, out = set(), []
    for u in data.get("result", []):
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            out.append({
                "chat_id": cid,
                "type": chat.get("type"),
                "name": " ".join(filter(None, [chat.get("first_name"),
                                               chat.get("last_name")]))
                        or chat.get("title") or chat.get("username") or "?",
            })
    return out


def whoami(token: str) -> dict:
    r = requests.get(API.format(token=token, method="getMe"), timeout=TIMEOUT)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"التوكن مرفوض: {data.get('description', '')[:150]}")
    return data["result"]


def set_webhook(url: str, secret: str, token: str | None = None) -> dict:
    """
    اربط الـ Edge Function بتليجرام.

    الـ secret_token بيرجع في هيدر كل نداء، والدالة بتتحقق منه قبل أي
    كتابة. من غيره، أي حد يعرف الرابط يقدر يزوّر ضغطات أزرار.
    """
    return call("setWebhook", {
        "url": url,
        "secret_token": secret,
        "allowed_updates": ["callback_query"],   # أقل صلاحية تكفي الشغل
        "drop_pending_updates": True,
    }, token or _config()[0])


def webhook_info(token: str | None = None) -> dict:
    return call("getWebhookInfo", {}, token or _config()[0])


def send_document(buf, filename: str, caption: str,
                  token: str, chat_id: str, markup: dict | None = None) -> int:
    """
    ابعت ملف. الأزرار بتتحط على رسالة المستند نفسها — عشان يبقى فيه
    رسالة واحدة للوظيفة، مش اتنين.
    """
    payload = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
    if markup:
        import json as _json
        payload["reply_markup"] = _json.dumps(markup)
    # النوع بيتحدد من الامتداد. لو بعتنا PDF بنوع docx، تليجرام
    # بيقبله بس بعض العملاء بتفشل في المعاينة.
    mime = {
        ".pdf":  "application/pdf",
        ".docx": ("application/vnd.openxmlformats-officedocument"
                  ".wordprocessingml.document"),
    }.get(Path(filename).suffix.lower(), "application/octet-stream")

    r = requests.post(
        API.format(token=token, method="sendDocument"),
        data=payload,
        files={"document": (filename, buf, mime)},
        timeout=90,
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"تليجرام رفض الملف: {data.get('description', '')[:200]}")
    return data["result"]["message_id"]
