# استخدم صورة Python الرسمية
FROM python:3.11

# ضبط مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ جميع الملفات إلى الحاوية
COPY . /app/

# تثبيت pip والمكتبات المطلوبة
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# تشغيل البوت تلقائيًا عند بدء التشغيل
CMD ["python3", "bot.py"]
