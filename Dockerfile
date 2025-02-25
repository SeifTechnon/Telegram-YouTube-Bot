# استخدم صورة Python الرسمية
FROM python:3.11

# ضبط مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ جميع الملفات إلى الحاوية
COPY . /app/

# تثبيت pip والمكتبات المطلوبة بدون ذاكرة مؤقتة
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# إعطاء صلاحيات تنفيذ لـ start.sh
RUN chmod +x /app/start.sh

# تشغيل البوت تلقائيًا عند بدء التشغيل
CMD ["bash", "/app/start.sh"]
