FROM python:3.10-slim

# تثبيت الحزم المطلوبة
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    libgl1 \
    libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

# تثبيت Whisper
RUN pip install --no-cache-dir openai-whisper

# تنزيل نموذج Whisper "small" أثناء البناء
RUN mkdir -p /root/.cache/whisper && \
    whisper download small --model_dir /root/.cache/whisper

# تثبيت أحدث إصدار من yt-dlp
RUN pip install --no-cache-dir yt-dlp --upgrade

# إعداد مجلد العمل
WORKDIR /app

# نسخ ملفات المتطلبات
COPY requirements.txt .

# تثبيت المتطلبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ ملفات المشروع
COPY . .

# جعل ملف start.sh قابل للتنفيذ
RUN chmod +x start.sh

# تشغيل البوت
CMD ["./start.sh"]