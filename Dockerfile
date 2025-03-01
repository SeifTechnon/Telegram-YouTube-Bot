# استخدم صورة Python الرسمية
FROM python:3.11-slim

# تثبيت FFmpeg (مطلوب لـ yt-dlp وffmpeg-python)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

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

# تعريف متغيرات البيئة
ENV PORT=8080

# تشغيل البوت تلقائيًا عند بدء التشغيل
CMD ["bash", "/app/start.sh"]