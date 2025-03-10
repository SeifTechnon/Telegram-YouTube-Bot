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

echo "🧪 اختبار Whisper..."
if ! python -c "import openai_whisper as whisper; model = whisper.load_model('tiny')" &> /dev/null; then
  echo "❌ فشل تحميل نموذج Whisper"
  exit 1
fi

echo "🚀 بدء التشغيل..."
hypercorn --worker-class uvloop --bind 0.0.0.0:$PORT bot:app