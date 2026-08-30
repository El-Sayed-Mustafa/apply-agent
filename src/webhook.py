"""
ربط الـ Edge Function بتليجرام.

  python -m src.webhook --set     → اربط
  python -m src.webhook --info    → اعرض الحالة والأخطاء
  python -m src.webhook --clear   → فك الربط (رجوع للاستطلاع)

الـ secret_token هو كل الأمان هنا: الرابط مفتوح على الإنترنت، وأي حد
يعرفه يقدر يبعتله. تليجرام بيحط التوكن في هيدر كل نداء، والدالة بترفض
أي حاجة من غيره — قبل ما تلمس الداتابيز.
"""
from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from . import telegram

load_dotenv()

PROJECT_REF = os.getenv("SUPABASE_PROJECT_REF", "wpyberjqlizxinxknglj")
FUNCTION_URL = f"https://{PROJECT_REF}.supabase.co/functions/v1/telegram-webhook"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="store_true")
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--clear", action="store_true")
    args = ap.parse_args()

    if args.clear:
        telegram.call("deleteWebhook", {"drop_pending_updates": False})
        print("اتفك الربط.")
        return 0

    if args.info:
        info = telegram.webhook_info()
        print(f"الرابط:            {info.get('url') or '(مفيش)'}")
        print(f"معلّق:             {info.get('pending_update_count', 0)}")
        print(f"توكن سري متضبّط:   {'✅' if info.get('has_custom_certificate') is not None else '?'}")
        if info.get("last_error_message"):
            print(f"\n⚠️  آخر خطأ: {info['last_error_message']}")
            print("   (لو 401 → السر مش متطابق · 404 → الدالة مش منشورة)")
        else:
            print("مفيش أخطاء ✅")
        return 0

    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not secret:
        print("❌ ناقص TELEGRAM_WEBHOOK_SECRET في .env")
        return 1

    telegram.set_webhook(FUNCTION_URL, secret)
    print(f"✅ اتربط بـ {FUNCTION_URL}")
    print(json.dumps(telegram.webhook_info(), ensure_ascii=False, indent=2)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
