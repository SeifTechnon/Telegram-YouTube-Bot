#!/bin/bash

# تحميل النموذج مع معالجة الأخطاء
echo "جارٍ تحميل النموذج..."
if python -c "import whisper; model = whisper.load_model('small'); print('✅ نجاح: النموذج small تم تحميله')"; then
    echo "النموذج جاهز للاستخدام!"
else
    echo "❌ خطأ: فشل تحميل النموذج"
    exit 1
fi

# إضافة أوامر التطبيق الرئيسية هنا (مثل تشغيل السيرفر)
# مثال: uvicorn main:app --host 0.0.0.0 --port 8000