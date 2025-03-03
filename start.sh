#!/bin/bash

echo "🔍 التحقق من متغيرات البيئة..."
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "⚠️ تنبيه: لم يتم تعيين TELEGRAM_BOT_TOKEN"
fi

echo "🚀 جاري بدء تشغيل البوت..."
# استخدام Hypercorn لتشغيل تطبيق Quart
hypercorn bot:app --bind 0.0.0.0:$PORT --workers 2 --worker-class uvloop