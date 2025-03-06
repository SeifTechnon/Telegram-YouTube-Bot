#!/bin/bash

echo "🔍 التحقق من المتغيرات البيئية..."
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "⚠️ لم يتم تعيين TELEGRAM_BOT_TOKEN"
    exit 1
fi

if [ -z "$WEBHOOK_URL" ]; then
    echo "⚠️ لم يتم تعيين WEBHOOK_URL"
    exit 1
fi

echo "🚀 بدء تشغيل البوت..."
hypercorn bot:app --bind 0.0.0.0:$PORT --workers 1 --worker-class asyncio