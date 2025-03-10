#!/bin/bash

echo "🔍 التحقق من المتغيرات البيئية..."
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
  echo "❌ TELEGRAM_BOT_TOKEN غير محدد"
  exit 1
fi

echo "🔍 التحقق من نموذج Whisper..."
if ! python -c "import whisper; model = whisper.load_model('tiny')" &> /dev/null; then
  echo "❌ فشل تحميل نموذج Whisper"
  exit 1
fi

echo "🚀 بدء التشغيل..."
# استخدام uvicorn لتحسين الأداء مع asyncio
hypercorn --worker-class uvloop --bind 0.0.0.0:$PORT bot:app