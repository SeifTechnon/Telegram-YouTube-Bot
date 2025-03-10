# استخدم صورة خفيفة مع Python 3.9
FROM python:3.9-slim

# تثبيت التبعيات الأساسية مع تنظيف الذاكرة
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libgl1 libavcodec-extra && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# تثبيت الإصدارات المتوافقة من PyTorch لدعم النموذج الكبير
RUN pip install --no-cache-dir torch==2.0.1+cpu torchvision==0.15.2+cpu torchaudio==2.0.2+cpu --extra-index-url https://download.pytorch.org/whl/cpu

# تثبيت NumPy 1.x (لتجنب تعارضات Whisper)
RUN pip install --no-cache-dir numpy==1.24.4

# تثبيت Whisper مع الإصدار الأخير (المتوافق مع النماذج الكبيرة)
RUN pip install --no-cache-dir openai-whisper==20240930

# تنزيل النموذج large-v3 مسبقًا لتجنب تحميله أثناء التشغيل
RUN python -c "import openai_whisper as whisper; whisper.load_model('large-v3')"

# تثبيت باقي المتطلبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# إعداد مجلد العمل
WORKDIR /app
COPY . .
RUN chmod +x start.sh

CMD ["./start.sh"]