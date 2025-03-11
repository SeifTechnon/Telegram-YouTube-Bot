#!/bin/bash

echo "🔍 التحقق من المتغيرات البيئية..."
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
  echo "❌ TELEGRAM_BOT_TOKEN غير محدد"
  exit 1
fi

echo "🔍 التحقق من نموذج Whisper..."
python -c "
import whisper
try:
    model = whisper.load_model('large-v3')
    print('✅ نموذج Whisper جاهز')
except Exception as e:
    print(f'❌ فشل تحميل نموذج Whisper: {e}')
    exit(1)
"

# تحديد منفذ افتراضي إذا لم يكن محددًا
PORT=${PORT:-8000}

echo "🚀 بدء التشغيل على المنفذ $PORT..."
exec hypercorn --worker-class uvloop --bind 0.0.0.0:$PORT bot:app