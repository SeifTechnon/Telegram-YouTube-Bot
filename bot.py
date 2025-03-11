import os
import re
import asyncio
import yt_dlp
import whisper
import torch
import subprocess
from deep_translator import GoogleTranslator
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

# إضافة Quart للواجهة الويب
from quart import Quart, jsonify

# تحميل توكن البوت من المتغيرات البيئية
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# إنشاء المجلدات اللازمة
if not os.path.exists("downloads"):
    os.makedirs("downloads")

# إعداد البوت
bot = Bot(token=TOKEN)
dp = Dispatcher()

# إنشاء تطبيق Quart
app = Quart(__name__)

# إضافة مسار الصحة للتحقق من حالة الخدمة
@app.route("/health")
async def health_check():
    return jsonify({"status": "healthy"}), 200

# التأكد من استخدام GPU إن كان متاحًا
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🖥️ استخدام جهاز: {device}")

# تحميل نموذج Whisper
MODEL_SIZE = "large-v3"
print(f"⏳ جاري تحميل نموذج Whisper {MODEL_SIZE}...")
model = whisper.load_model(MODEL_SIZE).to(device)
print("✅ تم تحميل النموذج!")

# رسالة الترحيب والشرح
START_MESSAGE = """
👋 مرحبًا بك في البوت! هذا البوت يقوم بـ:
1️⃣ تحميل فيديوهات يوتيوب بجودة 136 (فيديو فقط).
2️⃣ استخدام Whisper لإنشاء ترجمة تلقائية.
3️⃣ ترجمة النصوص إلى العربية.
4️⃣ دمج الترجمة في الفيديو وإرساله لك.
📌 أرسل رابط يوتيوب أو عدة روابط للبدء.
"""

# تحقق من رابط اليوتيوب
YOUTUBE_REGEX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$")

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.reply(START_MESSAGE)

@dp.message(lambda message: not message.text.startswith('/'))
async def handle_message(message: types.Message):
    text = message.text.strip()
    urls = text.split("\n")

    valid_urls = [url for url in urls if YOUTUBE_REGEX.match(url)]
    
    if not valid_urls:
        await message.reply("❌ لم يتم العثور على روابط يوتيوب صالحة. الرجاء إرسال رابط صحيح.")
        return

    status_message = await message.reply("⏳ جاري تحميل الفيديوهات، يرجى الانتظار...")

    output_files = []
    for i, url in enumerate(valid_urls):
        try:
            await bot.edit_message_text(
                f"⏳ جاري معالجة الفيديو {i+1}/{len(valid_urls)}: التحميل...", 
                chat_id=message.chat.id, 
                message_id=status_message.message_id
            )
            video_path = await download_video(url)
            
            await bot.edit_message_text(
                f"⏳ جاري معالجة الفيديو {i+1}/{len(valid_urls)}: استخراج الترجمة...", 
                chat_id=message.chat.id, 
                message_id=status_message.message_id
            )
            sub_file = await generate_subtitles(video_path)
            
            await bot.edit_message_text(
                f"⏳ جاري معالجة الفيديو {i+1}/{len(valid_urls)}: ترجمة النصوص...", 
                chat_id=message.chat.id, 
                message_id=status_message.message_id
            )
            translated_sub = await translate_subtitles(sub_file)
            
            await bot.edit_message_text(
                f"⏳ جاري معالجة الفيديو {i+1}/{len(valid_urls)}: دمج الترجمة...", 
                chat_id=message.chat.id, 
                message_id=status_message.message_id
            )
            final_video = await burn_subtitles(video_path, translated_sub)
            
            output_files.append(final_video)
        except Exception as e:
            await message.reply(f"❌ حدث خطأ أثناء معالجة الفيديو {i+1}: {str(e)}")
    
    if not output_files:
        await bot.edit_message_text(
            "❌ لم يتم إنتاج أي ملفات بسبب أخطاء في المعالجة.", 
            chat_id=message.chat.id, 
            message_id=status_message.message_id
        )
        return
    
    await bot.edit_message_text(
        "⏳ جاري إنهاء المعالجة...", 
        chat_id=message.chat.id, 
        message_id=status_message.message_id
    )
    
    if len(output_files) > 1:
        await bot.edit_message_text(
            "⏳ جاري دمج الفيديوهات...", 
            chat_id=message.chat.id, 
            message_id=status_message.message_id
        )
        final_video = await merge_videos(output_files)
        await send_video(message, final_video)
    else:
        await send_video(message, output_files[0])
    
    await bot.edit_message_text(
        "✅ تمت المعالجة بنجاح!", 
        chat_id=message.chat.id, 
        message_id=status_message.message_id
    )

async def download_video(url):
    """ تحميل فيديو باستخدام yt-dlp """
    output_path = f"downloads/%(id)s.%(ext)s"
    ydl_opts = {
        "format": "136",  # mp4 بدقة 720p
        "outtmpl": output_path,
        "quiet": True
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return f"downloads/{info['id']}.mp4"

async def generate_subtitles(video_path):
    """ إنشاء ملف الترجمة باستخدام Whisper """
    result = model.transcribe(video_path)
    
    # إنشاء ملف SRT
    srt_file = video_path.replace(".mp4", ".srt")
    
    with open(srt_file, "w", encoding="utf-8") as f:
        for i, segment in enumerate(result["segments"]):
            start_time = format_timestamp(segment["start"])
            end_time = format_timestamp(segment["end"])
            text = segment["text"].strip()
            
            f.write(f"{i+1}\n")
            f.write(f"{start_time} --> {end_time}\n")
            f.write(f"{text}\n\n")
    
    return srt_file

def format_timestamp(seconds):
    """ تنسيق الوقت بصيغة SRT (HH:MM:SS,mmm) """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}"

async def translate_subtitles(sub_file):
    """ ترجمة الترجمة إلى العربية """
    translator = GoogleTranslator(source="auto", target="ar")
    
    with open(sub_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    translated_file = sub_file.replace(".srt", "_ar.srt")
    
    with open(translated_file, "w", encoding="utf-8") as f:
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # كتابة رقم المقطع كما هو
            if line.isdigit():
                f.write(f"{line}\n")
                i += 1
                continue
            
            # كتابة التوقيت كما هو
            if "-->" in line:
                f.write(f"{line}\n")
                i += 1
                continue
            
            # تجميع النص للترجمة
            text_to_translate = ""
            while i < len(lines) and lines[i].strip() and "-->" not in lines[i]:
                text_to_translate += lines[i].strip() + " "
                i += 1
            
            # ترجمة النص إذا كان هناك نص
            if text_to_translate:
                try:
                    translated_text = translator.translate(text_to_translate)
                    f.write(f"{translated_text}\n")
                except Exception as e:
                    # إذا فشلت الترجمة، استخدم النص الأصلي
                    f.write(f"{text_to_translate}\n")
            
            # كتابة سطر فارغ
            f.write("\n")
            
            # تخطي السطور الفارغة
            while i < len(lines) and not lines[i].strip():
                i += 1
    
    return translated_file

async def burn_subtitles(video_path, sub_file):
    """ حرق الترجمة داخل الفيديو باستخدام FFmpeg """
    output_path = video_path.replace(".mp4", "_sub.mp4")
    
    command = [
        "ffmpeg", "-y", "-i", video_path, 
        "-vf", f"subtitles={sub_file}:force_style='FontSize=24,Alignment=2,BorderStyle=3,Outline=1,Shadow=0,MarginV=25'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    await process.communicate()
    
    if process.returncode != 0:
        # إذا فشل FFmpeg، نجرب بديلاً أبسط
        command = [
            "ffmpeg", "-y", "-i", video_path, 
            "-vf", f"subtitles={sub_file}",
            "-c:v", "libx264", "-preset", "fast",
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        await process.communicate()
    
    return output_path

async def merge_videos(video_paths):
    """ دمج عدة فيديوهات في فيديو واحد """
    # إنشاء ملف قائمة بالفيديوهات
    list_file = "downloads/file_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for path in video_paths:
            f.write(f"file '{os.path.abspath(path)}'\n")
    
    output_path = "downloads/merged_video.mp4"
    
    command = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    await process.communicate()
    
    return output_path

async def send_video(message, video_path):
    """ إرسال الفيديو إلى المستخدم """
    try:
        video = FSInputFile(video_path)
        await message.reply_video(
            video=video,
            caption="✅ تمت معالجة الفيديو بنجاح!"
        )
    except Exception as e:
        # إذا كان الملف كبيرًا جدًا، نرسله كملف
        await message.reply("⚠️ الفيديو كبير جدًا، سيتم إرساله كملف...")
        document = FSInputFile(video_path)
        await message.reply_document(
            document=document,
            caption="✅ تمت معالجة الفيديو بنجاح!"
        )

@dp.message(Command("clean"))
async def clean(message: types.Message):
    try:
        for file in os.listdir("downloads"):
            if file.endswith((".mp4", ".srt")):
                os.remove(os.path.join("downloads", file))
        await message.reply("✅ تم تنظيف جميع الملفات بنجاح!")
    except Exception as e:
        await message.reply(f"❌ حدث خطأ أثناء تنظيف الملفات: {str(e)}")

# إعداد وظيفة لبدء البوت مع تطبيق Quart
@app.before_serving
async def startup():
    print("🚀 بدء تشغيل البوت...")
    await dp.start_polling(bot)

# إعداد وظيفة لإغلاق البوت مع تطبيق Quart
@app.after_serving
async def shutdown():
    print("📴 إيقاف تشغيل البوت...")
    await bot.session.close()

# تشغيل البوت (يستخدم فقط عند تشغيل الملف مباشرة وليس عبر hypercorn)
async def main():
    print("🚀 البوت يعمل...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())