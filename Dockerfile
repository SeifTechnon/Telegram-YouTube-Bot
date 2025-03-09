# استخدام صورة أساسية خفيفة
FROM python:3.9-slim

# تثبيت التبعيات مع تنظيف الذاكرة
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir torch==2.0.0+cpu torchvision==0.15.1+cpu torchaudio==2.0.1 --extra-index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir whisper

# نسخ ملف التشغيل
COPY start.sh /start.sh

# تعريف نقطة الدخول
ENTRYPOINT ["/bin/bash", "/start.sh"]