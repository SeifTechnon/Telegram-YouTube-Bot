#!/bin/bash

echo "🔍 التحقق من المتغيرات البيئية..."
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
  echo "❌ TELEGRAM_BOT_TOKEN غير محدد"
  exit 1
fi

echo "🔍 التحقق من نموذج Whisper..."
if [ ! -f "/root/.cache/whisper/tiny.pt" ]; then
  echo "⚠️ نموذج Whisper tiny غير موجود"
  exit 1
fi

# اختبار تحميل النموذج
if python -c "import whisper; model = whisper.load_model('tiny')" &> /dev/null; then
    echo "✅ النموذج tiny تم تحميله بنجاح"
else
    echo "❌ فشل تحميل النموذج: ${model}"
    exit 1
fi

echo "🚀 بدء تشغيل البوت..."
hypercorn bot:app --bind 0.0.0.0:$PORT --workers 1 --worker-class asyncio