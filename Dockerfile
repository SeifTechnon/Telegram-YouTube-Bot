# استخدم صورة خفيفة مع Python 3.9
FROM python:3.9-slim

# تثبيت التبعيات الأساسية مع تنظيف الذاكرة
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libgl1 libavcodec-extra && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# تثبيت الإصدارات المتوافقة من PyTorch
RUN pip install --no-cache-dir torch==2.0.0+cpu torchvision==0.15.1+cpu torchaudio==2.0.1 --extra-index-url https://download.pytorch.org/whl/cpu

# تثبيت Whisper مع الإصدار الصحيح
RUN pip install --no-cache-dir openai-whisper==20231117

# تنزيل النموذج tiny مسبقًا لتجنب تحميله أثناء التشغيل
RUN python -c "import whisper; whisper.load_model('tiny')"

# تثبيت باقي المتطلبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# إعداد مجلد العمل
WORKDIR /app
COPY . .
RUN chmod +x start.sh

CMD ["./start.sh"]