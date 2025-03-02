#!/bin/bash

echo "🔍 التحقق من متغيرات البيئة..."
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "⚠️ تنبيه: لم يتم تعيين TELEGRAM_BOT_TOKEN"
fi

if [ -z "$RAILWAY_STATIC_URL" ] && [ -z "$RAILWAY_PUBLIC_DOMAIN" ]; then
    echo "⚠️ تنبيه: لم يتم تعيين RAILWAY_STATIC_URL أو RAILWAY_PUBLIC_DOMAIN"
fi

while true; do
    echo "🚀 جاري بدء تشغيل البوت..."
    # استخدام Hypercorn بدلاً من تشغيل bot.py مباشرة
    hypercorn bot:app --bind 0.0.0.0:$PORT
    
    EXIT_CODE=$?
    echo "⚠️ توقف البوت برمز الخروج: $EXIT_CODE"
    echo "🔄 إعادة التشغيل خلال 5 ثوانٍ..."
    sleep 5
done