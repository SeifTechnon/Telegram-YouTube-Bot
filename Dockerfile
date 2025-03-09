FROM python:3.9-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libavcodec-extra \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir torch==2.0.0+cpu torchvision==0.15.1+cpu torchaudio==2.0.1 --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir openai-whisper==20231116

# تحميل النموذج مسبقًا
RUN python -c "import openai_whisper as whisper; whisper.load_model('tiny').to('cpu')"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x start.sh
CMD ["./start.sh"]