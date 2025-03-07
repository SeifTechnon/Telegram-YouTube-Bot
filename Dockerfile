# Dockerfile
FROM python:3.10-slim

# تثبيت الحزم المطلوبة لـ FFmpeg و Whisper
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    libgl1 \
    libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

# تثبيت Whisper
RUN pip install --no-cache-dir openai-whisper
RUN whisper download small  # ← هذا السطر ضروري لتنزيل النموذج

# إعداد مجلد العمل
WORKDIR /app

# نسخ ملفات المتطلبات
COPY requirements.txt .

# تثبيت الباياثون
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملفات المشروع
COPY . .

# جعل ملف start.sh قابل للتنفيذ
RUN chmod +x start.sh

# تشغيل البوت
CMD ["./start.sh"]