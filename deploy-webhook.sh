#!/usr/bin/env bash
# نشر مستقبِل تليجرام.
#
#   SUPABASE_ACCESS_TOKEN=sbp_...  ./deploy-webhook.sh
#
# التوكن من:  supabase.com/dashboard/account/tokens
set -euo pipefail

REF=wpyberjqlizxinxknglj
set -a; . ./.env; set +a

echo "→ نشر الدالة"
npx --yes supabase@latest functions deploy telegram-webhook \
    --project-ref "$REF" --no-verify-jwt

echo "→ ضبط أسرار الدالة"
npx --yes supabase@latest secrets set --project-ref "$REF" \
    TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
    TELEGRAM_WEBHOOK_SECRET="$TELEGRAM_WEBHOOK_SECRET" \
    TELEGRAM_CHAT_ID="$TELEGRAM_CHAT_ID"

echo "→ ربط تليجرام بالدالة"
python -m src.webhook --set

echo "✅ تمام"
