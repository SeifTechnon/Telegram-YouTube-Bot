# استخدم صورة Python 3.9 خفيفة
FROM python:3.9-slim

# تثبيت التبعيات الأساسية مع تنظيف الذاكرة
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libgl1 libavcodec-extra && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# تثبيت المتطلبات مباشرة
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تنزيل النموذج مسبقًا لتجنب تحميله أثناء التشغيل
RUN python -c "import whisper; whisper.load_model('large-v3')"

# إعداد مجلد العمل
WORKDIR /app
COPY . .
RUN chmod +x start.sh

# تشغيل البرنامج عند بدء الحاوية
CMD ["./start.sh"]