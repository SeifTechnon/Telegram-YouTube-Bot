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

# تثبيت wget
RUN apt-get update && apt-get install -y wget

# إنشاء مجلد لتخزين النموذج
RUN mkdir -p /root/.cache/whisper

# تنزيل نموذج Whisper "small" يدويًا
RUN wget -O /root/.cache/whisper/small.pt https://openaipublic.azureedge.net/main/whisper/models/small.pt

# التحقق من وجود الملف بعد التنزيل
RUN ls -lh /root/.cache/whisper/small.pt || (echo "⚠️ فشل تنزيل النموذج!" && exit 1)

# إزالة wget لتقليل الحجم
RUN apt-get remove -y wget && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

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