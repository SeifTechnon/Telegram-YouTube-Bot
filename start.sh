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

echo "🔍 التحقق من نموذج Whisper..."
if [ ! -f "/root/.cache/whisper/small.pt" ]; then
    echo "⚠️ نموذج Whisper غير موجود في /root/.cache/whisper/small.pt"
    exit 1
fi

# عرض محتويات المجلد للتحقق من وجود النموذج
echo "📂 محتويات مجلد /root/.cache/whisper/:"
ls -l /root/.cache/whisper/

echo "🧪 اختبار Whisper..."
python -c "import whisper; model = whisper.load_model('small'); print('Whisper model loaded successfully')" || {
    echo "⚠️ فشل تحميل نموذج Whisper"
    exit 1
}

echo "🚀 بدء تشغيل البوت..."
hypercorn bot:app --bind 0.0.0.0:$PORT --workers 1 --worker-class asyncio