# استخدم صورة Python الرسمية
FROM python:3.11

# ضبط مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المتطلبات وتثبيتها أولاً
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . /app/

# إعطاء صلاحيات تنفيذ لـ start.sh
RUN chmod +x /app/start.sh

# تشغيل البوت تلقائيًا عند بدء التشغيل
CMD ["bash", "/app/start.sh"]
