#!/bin/bash

echo "🔍 التحقق من متغيرات البيئة..."
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "⚠️ تنبيه: لم يتم تعيين TELEGRAM_BOT_TOKEN"
    exit 1
fi

if [ -z "$WEBHOOK_URL" ]; then
    echo "⚠️ تنبيه: لم يتم تعيين WEBHOOK_URL"
    exit 1
fi

echo "🚀 جاري بدء تشغيل البوت..."
# استخدام Hypercorn لتشغيل تطبيق Quart مع Webhook
hypercorn bot:app --bind 0.0.0.0:$PORT --workers 1 --worker-class asyncio