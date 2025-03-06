FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    libgl1 \
    ffmpeg-codecs-extra \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir openai-whisper
RUN whisper download small  # تنزيل نموذج Whisper

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x start.sh
CMD ["./start.sh"]