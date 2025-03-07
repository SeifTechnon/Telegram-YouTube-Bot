import os
import re
import logging
import asyncio
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from quart import Quart, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from yt_dlp import YoutubeDL
import ffmpeg
import sentry_sdk
from sentry_sdk.integrations.quart import QuartIntegration

app = Quart(__name__)
PORT = int(os.environ.get('PORT', 8080))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[QuartIntegration()],
    traces_sample_rate=1.0,
    environment="production",
    release="v1.0.0",
    attach_stacktrace=True,
    send_default_pii=True,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("⚠️ لم يتم تعيين TELEGRAM_BOT_TOKEN في المتغيرات البيئية!")
    raise ValueError("TELEGRAM_BOT_TOKEN is not set!")

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # إضافة معرف الدردشة الإدارية

USE_WEBHOOK = True

YOUTUBE_REGEX = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|shorts/)?([a-zA-Z0-9_-]{11})'

telegram_app = None
telegram_initialized = False

@app.route('/health')
async def health_check():
    logger.info("تم استقبال طلب للتحقق من صحة التطبيق")
    return jsonify({
        "status": "healthy",
        "message": "Bot is running",
        "webhook_mode": USE_WEBHOOK,
        "initialized": telegram_initialized
    }), 200

@app.route(f'/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
async def webhook():
    if not telegram_app:
        return jsonify({"status": "error", "message": "Telegram application not initialized"}), 500

    update = Update.de_json(await request.get_json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return jsonify({"status": "success"}), 200

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"حدث خطأ: {context.error}")
    sentry_sdk.capture_exception(context.error)
    error_message = f"❌ حدث خطأ: {str(context.error)}"
    
    if update and hasattr(update, 'effective_message'):
        await update.effective_message.reply_text(
            "❌ حدث خطأ أثناء معالجة طلبك. يرجى المحاولة لاحقاً."
        )

    if TELEGRAM_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"⚠️ تنبيه إداري:\n{error_message}\nمن المستخدم: {update.effective_user.id if update else 'غير معروف'}"
            )
        except Exception as e:
            logger.error(f"فشل إرسال الإشعار: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    welcome_message = (
        f"👋 مرحباً {user.first_name}!\n\n"
        "🎬 بوت تنزيل فيديوهات يوتيوب مع ترجمة عربية 🎬\n\n"
        "📝 *طريقة الاستخدام:*\n"
        "1️⃣ أرسل رابط فيديو واحد للتنزيل مع ترجمة\n"
        "2️⃣ أرسل عدة روابط (كل رابط في سطر) لدمجها في فيديو واحد\n\n"
        "⚠️ الحد الأقصى 5 فيديوهات\n\n"
        "🌟 مثال:\n"
        "```\n"
        "https://www.youtube.com/watch?v=zdLc6i9uNVc\n"
        "https://www.youtube.com/watch?v=I9YDayY7Dk4\n"
        "```\n\n"
        "🔄 ابدأ الآن!"
    )

    keyboard = [
        [InlineKeyboardButton("🔍 طريقة الاستخدام", callback_data="help")],
        [InlineKeyboardButton("📱 تواصل مع المطور", url="https://t.me/yourusername")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_message, parse_mode="Markdown", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_message = (
        "🔍 *دليل الاستخدام*\n\n"
        "1️⃣ لتنزيل فيديو واحد: أرسل رابط الفيديو\n"
        "2️⃣ لدمج عدة فيديوهات: أرسل روابطها في سطور منفصلة\n"
        "3️⃣ أوامر متاحة: /start, /help, /status\n\n"
        "⏱ مدة المعالجة تعتمد على طول الفيديو."
    )
    await update.message.reply_text(help_message, parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "help":
        help_message = (
            "🔍 *كيفية الاستخدام*\n\n"
            "1️⃣ أرسل رابط فيديو واحد\n"
            "2️⃣ أرسل عدة روابط في سطور منفصلة\n"
            "⏱ المدة: تختلف حسب طول الفيديو."
        )
        await query.edit_message_text(text=help_message, parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "✅ البوت يعمل\n"
        "🔄 وضع الاتصال: Webhook"
    )

async def extract_youtube_links(text: str) -> list:
    links = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        match = re.search(YOUTUBE_REGEX, line)
        if match:
            video_id = match.group(5)
            if video_id:
                links.append(f"https://www.youtube.com/watch?v={video_id}")
    return links

def get_video_info(video_url: str) -> dict:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'socket_timeout': 30,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return {
                'id': info.get('id'),
                'title': info.get('title'),
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail'),
            }
    except Exception as e:
        logger.error(f"خطأ في معلومات الفيديو: {str(e)}")
        raise Exception("فشل في الوصول إلى معلومات الفيديو")

async def download_video(video_url: str, output_dir: str, message_ref) -> str:
    info = get_video_info(video_url)
    video_id = info['id']
    video_title = info['title']
    await message_ref.edit_text(f"⬇️ جاري تنزيل: {video_title}\n⏳ يرجى الانتظار...")
    
    ydl_opts = {
        'format': 'bestvideo[height<=720]+bestaudio/best',
        'outtmpl': os.path.join(output_dir, f"{video_id}.%(ext)s"),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
            'keepvideo': True  # ← إصلاح إملائي
        }]
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    
    # ابحث عن الفيديو الأصلي (مثل .mp4 أو .webm)
    video_files = [f for f in os.listdir(output_dir) if f.startswith(f"{video_id}") and f.endswith(('.mp4', '.webm'))]
    return os.path.join(output_dir, video_files[0]) if video_files else None

async def generate_subtitles(video_file: str, output_dir: str, message_ref) -> str:
    await message_ref.edit_text("🔊 جاري استخراج النص من الفيديو...\n\n⏳ يرجى الانتظار...")
    base_name = os.path.basename(video_file).split('.')[0]
    srt_file = os.path.join(output_dir, f"{base_name}.srt")
    
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
    await process.communicate()
    
    if not os.path.exists(srt_file):
        srt_files = [f for f in os.listdir(output_dir) if f.endswith('.srt') and f.startswith(base_name)]
        srt_file = os.path.join(output_dir, srt_files[0]) if srt_files else None
    
    return srt_file

async def burn_subtitles(video_file: str, subtitle_file: str, output_dir: str, message_ref) -> str:
    base_name = os.path.basename(video_file).split('.')[0]
    output_file = os.path.join(output_dir, f"{base_name}_subtitled.mp4")
    
    ffmpeg_cmd = [
        "ffmpeg", "-i", video_file,
        "-vf", f"subtitles={subtitle_file}:force_style='FontName=Arial,FontSize=24,PrimaryColour=0xFFFFFF,OutlineColour=0x000000,BackColour=0x000000,BorderStyle=1,Outline=1,Shadow=1,Alignment=2'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-y", output_file
    ]
    
    process = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()
    
    if not os.path.exists(output_file):
        raise FileNotFoundError(f"فشل في حرق الترجمة: {output_file}")
    
    return output_file

async def merge_videos(video_files: list, output_dir: str, message_ref) -> str:
    list_file = os.path.join(output_dir, "filelist.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for video in video_files:
            f.write(f"file '{os.path.abspath(video)}'\n")  # ← المسار المطلق
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"merged_{timestamp}.mp4")
    
    ffmpeg_cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        "-y", output_file
    ]
    
    process = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()
    
    if not os.path.exists(output_file):
        raise FileNotFoundError("فشل في دمج الفيديوهات")
    
    return output_file

async def process_videos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_text = update.message.text
    youtube_links = await extract_youtube_links(message_text)
    
    if not youtube_links:
        await update.message.reply_text("❌ روابط غير صالحة!")
        return
    
    if len(youtube_links) > 5:
        youtube_links = youtube_links[:5]
    
    status_message = await update.message.reply_text(
        f"🔍 تم العثور على {len(youtube_links)} روابط. جاري المعالجة..."
    )
    
    processed_videos = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir).absolute()  # ← ضمان المسار المطلق
        
        for i, video_url in enumerate(youtube_links, 1):
            try:
                await status_message.edit_text(f"⚙️ معالجة الفيديو {i}/{len(youtube_links)}: {video_url}")
                
                video_file = await download_video(video_url, str(temp_dir), status_message)
                if not video_file:
                    raise FileNotFoundError("لم يتم تنزيل الفيديو")
                
                subtitle_file = await generate_subtitles(video_file, str(temp_dir), status_message)
                if not subtitle_file:
                    raise FileNotFoundError("لم يتم إنشاء ملف الترجمة")
                
                subtitled_video = await burn_subtitles(video_file, subtitle_file, str(temp_dir), status_message)
                if not subtitled_video:
                    raise FileNotFoundError("فشل في حرق الترجمة")
                
                processed_videos.append(subtitled_video)
                
            except Exception as e:
                logger.error(f"خطأ في الفيديو {i}: {str(e)}")
                await status_message.edit_text(f"⚠️ خطأ في الفيديو {i}: {str(e)}. المتابعة مع الفيديو التالي...")
                await asyncio.sleep(3)
        
        if not processed_videos:
            await status_message.edit_text("❌ لم يتم معالجة أي فيديو.")
            return
        
        final_video = await merge_videos(processed_videos, str(temp_dir), status_message) if len(processed_videos) > 1 else processed_videos[0]
        
        try:
            with open(final_video, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption=f"🎬 تم معالجة {len(processed_videos)} فيديو مع ترجمة عربية",
                    supports_streaming=True
                )
            await status_message.delete()
        except Exception as e:
            logger.error(f"فشل في الإرسال: {str(e)}")
            await status_message.edit_text(f"❌ خطأ في الإرسال: {str(e)}")

def create_telegram_app():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_videos))
    application.add_error_handler(error_handler)
    return application

@app.before_serving
async def startup():
    global telegram_app, telegram_initialized
    logger.info("بدء تشغيل البوت...")
    
    try:
        telegram_app = create_telegram_app()
        await telegram_app.initialize()
        webhook_url = f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
        await telegram_app.bot.set_webhook(webhook_url)
        telegram_initialized = True
        logger.info("✅ تم تشغيل البوت بنجاح!")
        
        if TELEGRAM_CHAT_ID:
            await telegram_app.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text="🚀 البوت يعمل الآن!"
            )
    except Exception as e:
        logger.error(f"❌ خطأ في التهيئة: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise

@app.after_serving
async def shutdown():
    global telegram_app, telegram_initialized
    logger.info("إيقاف البوت...")
    
    if telegram_app:
        await telegram_app.bot.delete_webhook()
        await telegram_app.stop()
        await telegram_app.shutdown()
        
        if TELEGRAM_CHAT_ID:
            await telegram_app.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text="🛑 تم إيقاف البوت."
            )
    
    telegram_initialized = False
    logger.info("تم الإيقاف بنجاح!")

if __name__ == "__main__":
    pass