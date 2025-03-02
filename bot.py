import os
import re
import logging
import asyncio
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from quart import Quart, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from yt_dlp import YoutubeDL
import ffmpeg

# إنشاء تطبيق Quart وتطبيق Telegram
app = Quart(__name__)
PORT = int(os.environ.get('PORT', 8080))

# إعداد السجل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# الحصول على رمز البوت من المتغيرات البيئية
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ لم يتم تحديد TELEGRAM_BOT_TOKEN في المتغيرات البيئية!")

# نمط للتعرف على روابط يوتيوب
YOUTUBE_REGEX = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|shorts/)?([a-zA-Z0-9_-]{11})'

# إضافة مسار صحة التطبيق (healthcheck)
@app.route('/health')
async def health_check():
    return jsonify({"status": "healthy", "message": "Bot is running"}), 200


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """الرد على أمر /start"""
    user = update.effective_user
    welcome_message = (
        f"👋 مرحباً {user.first_name}!\n\n"
        "🎬 هذا البوت يساعدك في تنزيل فيديوهات يوتيوب مع إضافة ترجمات باللغة العربية! 🎬\n\n"
        "📝 *طريقة الاستخدام:*\n"
        "1️⃣ أرسل رابط فيديو يوتيوب واحد للتنزيل مع ترجمة\n"
        "2️⃣ أو أرسل عدة روابط (كل رابط في سطر) لتنزيلها ودمجها في فيديو واحد مع ترجمات\n\n"
        "⚠️ *ملاحظات مهمة:*\n"
        "• قد يستغرق تجهيز الفيديوهات وقتًا حسب مدة المقاطع\n"
        "• يجب أن تكون الروابط من يوتيوب فقط\n"
        "• الحد الأقصى للفيديوهات هو 5 في المرة الواحدة\n\n"
        "🌟 *مثال:*\n"
        "```\n"
        "https://www.youtube.com/watch?v=zdLc6i9uNVc\n"
        "https://www.youtube.com/watch?v=I9YDayY7Dk4\n"
        "```\n\n"
        "🔄 ابدأ الآن بإرسال روابط فيديوهات يوتيوب!"
    )
    
    # إنشاء أزرار تفاعلية
    keyboard = [
        [InlineKeyboardButton("🔍 طريقة الاستخدام", callback_data="help")],
        [InlineKeyboardButton("📱 تواصل مع المطور", url="https://t.me/yourusername")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_message, parse_mode="Markdown", reply_markup=reply_markup)


async def extract_youtube_links(text: str) -> list:
    """استخراج روابط يوتيوب من النص"""
    links = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        match = re.search(YOUTUBE_REGEX, line)
        if match:
            # استخراج معرف الفيديو
            video_id = match.group(5)
            if video_id:
                # تنسيق الرابط بشكل موحد
                links.append(f"https://www.youtube.com/watch?v={video_id}")
    
    return links


def get_video_info(video_url: str) -> dict:
    """الحصول على معلومات الفيديو باستخدام yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        return {
            'id': info.get('id'),
            'title': info.get('title'),
            'duration': info.get('duration'),
            'thumbnail': info.get('thumbnail'),
        }


async def download_video(video_url: str, output_dir: str, message_ref) -> str:
    """تنزيل فيديو من يوتيوب"""
    # الحصول على معلومات الفيديو
    info = get_video_info(video_url)
    video_id = info['id']
    video_title = info['title']
    
    await message_ref.edit_text(
        f"⬇️ جاري تنزيل الفيديو:\n{video_title}\n\n⏳ يرجى الانتظار..."
    )
    
    # تكوين خيارات التنزيل
    output_file = os.path.join(output_dir, f"{video_id}.mp4")
    ydl_opts = {
        'format': '136+bestaudio/best',  # mp4 720p
        'merge_output_format': 'mp4',
        'outtmpl': output_file,
        'quiet': True,
    }
    
    # تنزيل الفيديو
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    
    return output_file


async def generate_subtitles(video_file: str, output_dir: str, message_ref) -> str:
    """توليد ملف الترجمة باستخدام Whisper"""
    await message_ref.edit_text(
        f"🔊 جاري استخراج النص من الفيديو...\n\n⏳ يرجى الانتظار..."
    )
    
    # استخراج اسم الملف بدون امتداد
    base_name = os.path.basename(video_file).split('.')[0]
    srt_file = os.path.join(output_dir, f"{base_name}.srt")
    
    # استخدام Whisper لاستخراج النص وتوليد ملف SRT
    whisper_cmd = [
        "whisper", video_file,
        "--model", "small",
        "--output_dir", output_dir,
        "--output_format", "srt",
        "--language", "ar"
    ]
    
    process = await asyncio.create_subprocess_exec(
        *whisper_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        logger.error(f"خطأ في استخراج النص: {stderr.decode()}")
        raise Exception("فشل في استخراج النص من الفيديو")
    
    return srt_file


async def burn_subtitles(video_file: str, subtitle_file: str, output_dir: str, message_ref) -> str:
    """حرق الترجمة في الفيديو"""
    await message_ref.edit_text(
        f"🔥 جاري دمج الترجمة مع الفيديو...\n\n⏳ يرجى الانتظار..."
    )
    
    # إنشاء اسم ملف الإخراج
    base_name = os.path.basename(video_file).split('.')[0]
    output_file = os.path.join(output_dir, f"{base_name}_subtitled.mp4")
    
    # استخدام FFmpeg لحرق الترجمة في الفيديو
    try:
        (
            ffmpeg
            .input(video_file)
            .output(
                output_file,
                vf=f"subtitles={subtitle_file}:force_style='FontName=Arial,FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BackColour=&H000000,BorderStyle=1,Outline=1,Shadow=1,Alignment=2'",
                codec='copy',
                acodec='aac'
            )
            .run(quiet=True, overwrite_output=True)
        )
        return output_file
    
    except ffmpeg.Error as e:
        logger.error(f"خطأ في حرق الترجمة: {e.stderr.decode() if e.stderr else str(e)}")
        raise Exception("فشل في حرق الترجمة في الفيديو")


async def merge_videos(video_files: list, output_dir: str, message_ref) -> str:
    """دمج عدة مقاطع فيديو في ملف واحد"""
    await message_ref.edit_text(
        f"🔄 جاري دمج {len(video_files)} فيديوهات في ملف واحد...\n\n⏳ يرجى الانتظار..."
    )
    
    # إنشاء ملف قائمة للدمج
    list_file = os.path.join(output_dir, "filelist.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for video_file in video_files:
            f.write(f"file '{video_file}'\n")
    
    # إنشاء اسم ملف الإخراج
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"merged_{timestamp}.mp4")
    
    # استخدام FFmpeg لدمج الفيديوهات
    try:
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_file
        ]
        
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            logger.error(f"خطأ في دمج الفيديوهات: {stderr.decode()}")
            raise Exception("فشل في دمج مقاطع الفيديو")
        
        return output_file
        
    except Exception as e:
        logger.error(f"خطأ في دمج الفيديوهات: {str(e)}")
        raise Exception("فشل في دمج مقاطع الفيديو")


async def process_videos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة رسالة تحتوي على روابط فيديو"""
    # استخراج روابط يوتيوب من الرسالة
    message_text = update.message.text
    youtube_links = await extract_youtube_links(message_text)
    
    # التحقق من وجود روابط صالحة
    if not youtube_links:
        await update.message.reply_text(
            "❌ لم يتم العثور على روابط يوتيوب صالحة في رسالتك!\n\n"
            "يرجى إرسال روابط بتنسيق صحيح مثل:\n"
            "https://www.youtube.com/watch?v=abcdefghijk"
        )
        return
    
    # التحقق من عدد الروابط (الحد الأقصى 5)
    if len(youtube_links) > 5:
        await update.message.reply_text(
            "⚠️ لقد تجاوزت الحد الأقصى المسموح به (5 فيديوهات).\n"
            f"سأقوم بمعالجة أول 5 فيديوهات فقط من أصل {len(youtube_links)}."
        )
        youtube_links = youtube_links[:5]
    
    # إرسال رسالة الانتظار
    status_message = await update.message.reply_text(
        f"🔍 تم العثور على {len(youtube_links)} روابط يوتيوب.\n"
        "⏳ جاري بدء المعالجة... يرجى الانتظار."
    )
    
    # إنشاء مجلد مؤقت للعمل
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            processed_videos = []
            
            # معالجة كل فيديو على حدة
            for i, video_url in enumerate(youtube_links):
                await status_message.edit_text(
                    f"⚙️ جاري معالجة الفيديو {i+1} من {len(youtube_links)}...\n\n"
                    f"🔗 {video_url}\n\n"
                    "⏳ يرجى الانتظار..."
                )
                
                # تنزيل الفيديو
                video_file = await download_video(video_url, temp_dir, status_message)
                
                # توليد ملف الترجمة
                subtitle_file = await generate_subtitles(video_file, temp_dir, status_message)
                
                # حرق الترجمة في الفيديو
                subtitled_video = await burn_subtitles(video_file, subtitle_file, temp_dir, status_message)
                
                processed_videos.append(subtitled_video)
            
            # التحقق من عدد الفيديوهات المعالجة
            if len(processed_videos) == 0:
                await status_message.edit_text("❌ لم يتم معالجة أي فيديو بنجاح.")
                return
            
            # الفيديو النهائي (مدمج أو منفرد)
            final_video = ""
            if len(processed_videos) > 1:
                # دمج الفيديوهات إذا كان هناك أكثر من واحد
                await status_message.edit_text(
                    f"🔄 جاري دمج {len(processed_videos)} فيديوهات في ملف واحد...\n\n"
                    "⏳ يرجى الانتظار..."
                )
                final_video = await merge_videos(processed_videos, temp_dir, status_message)
            else:
                # استخدام الفيديو الوحيد مباشرة
                final_video = processed_videos[0]
            
            # إرسال الفيديو النهائي
            await status_message.edit_text("✅ اكتملت المعالجة! جاري إرسال الفيديو...")
            
            with open(final_video, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption=(
                        "🎬 تم معالجة الفيديو بنجاح!\n"
                        f"✅ عدد الفيديوهات: {len(youtube_links)}\n"
                        "🔤 تمت إضافة الترجمة باللغة العربية"
                    ),
                    supports_streaming=True,
                    width=1280,
                    height=720
                )
            
            await status_message.delete()
                
        except Exception as e:
            logger.error(f"خطأ أثناء معالجة الفيديوهات: {str(e)}")
            await status_message.edit_text(
                f"❌ حدث خطأ أثناء معالجة الفيديوهات:\n{str(e)}"
            )


# إنشاء وتشغيل تطبيق Telegram
async def init_telegram_bot():
    """تهيئة وتشغيل بوت التلجرام"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    
    # إضافة معالج الرسائل النصية (للروابط)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_videos))
    
    # بدء البوت
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    return application


@app.before_serving
async def startup():
    """تنفيذ هذه الدالة عند بدء تشغيل التطبيق"""
    logger.info("بدء تشغيل البوت...")
    app.telegram_bot = await init_telegram_bot()
    logger.info("تم بدء تشغيل البوت بنجاح!")


@app.after_serving
async def shutdown():
    """تنفيذ هذه الدالة عند إيقاف التطبيق"""
    logger.info("إيقاف تشغيل البوت...")
    if hasattr(app, 'telegram_bot'):
        await app.telegram_bot.stop()
        await app.telegram_bot.shutdown()
    logger.info("تم إيقاف تشغيل البوت بنجاح!")


if __name__ == "__main__":
    # استخدام متغير PORT من البيئة أو استخدام 8080 كقيمة افتراضية
    app.run(host="0.0.0.0", port=PORT)