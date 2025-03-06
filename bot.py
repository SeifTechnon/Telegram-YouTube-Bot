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

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
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
            "❌ حدث خطأ أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً."
        )
    
    if TELEGRAM_CHAT_ID:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"⚠️ تنبيه إداري:\n{error_message}\nمن المستخدم: {update.effective_user.id if update else 'غير معروف'}"
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    keyboard = [
        [InlineKeyboardButton("🔍 طريقة الاستخدام", callback_data="help")],
        [InlineKeyboardButton("📱 تواصل مع المطور", url="https://t.me/yourusername")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_message, parse_mode="Markdown", reply_markup=reply_markup)

# ... (باقي الدوال الأخرى مع التصحيحات التالية) ...

async def download_video(video_url: str, output_dir: str, message_ref) -> str:
    info = get_video_info(video_url)
    video_id = info['id']
    video_title = info['title']
    await message_ref.edit_text(f"⬇️ جاري تنزيل الفيديو:\n{video_title}\n\n⏳ يرجى الانتظار...")
    
    ydl_opts = {
        'format': 'bestvideo[height<=720]+bestaudio/best',
        'outtmpl': os.path.join(output_dir, f"{video_id}.mp4"),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    return os.path.join(output_dir, f"{video_id}.mp4")

async def generate_subtitles(video_file: str, output_dir: str, message_ref) -> str:
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
    return output_file

async def process_videos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message_text = update.message.text
    youtube_links = await extract_youtube_links(message_text)
    
    if not youtube_links:
        await update.message.reply_text("❌ لم يتم العثور على روابط يوتيوب صالحة...")
        return
    
    status_message = await update.message.reply_text(f"🔍 تم العثور على {len(youtube_links)} روابط. جاري المعالجة...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        processed_videos = []
        for i, video_url in enumerate(youtube_links, 1):
            try:
                await status_message.edit_text(f"⚙️ معالجة الفيديو {i}/{len(youtube_links)}: {video_url}")
                
                video_file = await download_video(video_url, temp_dir, status_message)
                subtitle_file = await generate_subtitles(video_file, temp_dir, status_message)
                subtitled_video = await burn_subtitles(video_file, subtitle_file, temp_dir, status_message)
                
                processed_videos.append(subtitled_video)
                
            except Exception as e:
                logger.error(f"خطأ في معالجة الفيديو {i}: {str(e)}")
                await status_message.edit_text(f"⚠️ خطأ في الفيديو {i}: {str(e)}. المتابعة مع الفيديو التالي...")
                await asyncio.sleep(3)
        
        if not processed_videos:
            await status_message.edit_text("❌ لم يتم معالجة أي فيديو بنجاح.")
            return
        
        final_video = processed_videos[0]
        if len(processed_videos) > 1:
            final_video = await merge_videos(processed_videos, temp_dir, status_message)
        
        try:
            with open(final_video, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption=f"🎬 تم معالجة {len(processed_videos)} فيديو بنجاح!\n✅ ترجمة عربية تلقائية",
                    supports_streaming=True
                )
            await status_message.delete()
        except Exception as e:
            logger.error(f"فشل في إرسال الفيديو: {str(e)}")
            await status_message.edit_text(f"❌ فشل في الإرسال: {str(e)}")