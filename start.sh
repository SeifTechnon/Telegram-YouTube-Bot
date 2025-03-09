#!/bin/bash

echo "⏳ التحقق من المتغيرات البيئية..."
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
  echo "❌ TELEGRAM_BOT_TOKEN غير محدد"
  exit 1
fi

echo "🔍 التحقق من نموذج Whisper..."
if python -c "import openai_whisper as whisper; model = whisper.load_model('tiny').to('cpu')" 2>/dev/null; then
  echo "✅ نجاح: النموذج tiny جاهز"
else
  echo "❌ خطأ: فشل تحميل النموذج"
  exit 1
fi

echo "🚀 بدء تشغيل البوت..."
hypercorn bot:app --bind 0.0.0.0:$PORT --workers 1 --worker-class asyncio