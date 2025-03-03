# Dockerfile
FROM python:3.10-slim

# تثبيت الحزم المطلوبة
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# تثبيت Whisper
RUN pip install --no-cache-dir openai-whisper

# إنشاء مجلد العمل
WORKDIR /app

# نسخ ملفات المتطلبات
COPY requirements.txt .

# تثبيت المتطلبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملفات المشروع
COPY . .

# جعل ملف start.sh قابل للتنفيذ
RUN chmod +x start.sh

# تشغيل البوت باستخدام start.sh
CMD ["./start.sh"]