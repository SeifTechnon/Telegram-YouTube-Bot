import os
import re
import logging
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from quart import Quart, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler
)
from yt_dlp import YoutubeDL
import ffmpeg
import openai_whisper as whisper
import sentry_sdk
from sentry_sdk.integrations.quart import QuartIntegration

# إعداد التطبيق
app = Quart(__name__)
PORT = int(os.environ.get('PORT', 8080))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

# Sentry لتسجيل الأخطاء
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[QuartIntegration()],
    traces_sample_rate=1.0,
    environment="production",
    release="v1.0.0",
    attach_stacktrace=True,
    send_default_pii=True,
)

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# التحقق من المتغيرات البيئية
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("⚠️ TELEGRAM_BOT_TOKEN غير متوفر")
    raise ValueError("TELEGRAM_BOT_TOKEN is required")

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_REGEX = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|shorts/)?([a-zA-Z0-9_-]{11})'

telegram_app = None
telegram_initialized = False

### دوال المساعدة

async def download_video(url: str, output_dir: str) -> str:
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'outtmpl': os.path.join(output_dir, '%(id)s.%(ext)s'),
        'quiet': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

async def generate_subtitles(video_file: str, output_dir: str) -> str:
    try:
        # استخدام النموذج tiny مع الجهاز cpu
        model = whisper.load_model("tiny")
        result = model.transcribe(video_file, language="ar")
        
        base_name = Path(video_file).stem
        srt_file = Path(output_dir) / f"{base_name}.srt"
        
        with open(srt_file, "w", encoding="utf-8") as f:
            f.write(result["text"])
            
        return str(srt_file)
    except Exception as e:
        logger.error(f"فشل إنشاء الترجمة: {str(e)}")
        raise

async def burn_subtitles(video_file: str, subtitle_file: str, output_dir: str) -> str:
    try:
        output_path = Path(output_dir) / f"{Path(video_file).stem}_subtitled.mp4"
        (
            ffmpeg
            .input(video_file)
            .output(
                str(output_path),
                vf=f"subtitles={subtitle_file}:force_style='FontName=Arial,FontSize=24,PrimaryColour=0xFFFFFF,OutlineColour=0x000000,BorderStyle=1'",
                c='copy',
                preset='fast',
                crf=22,
                loglevel='error'
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return str(output_path)
    except Exception as e:
        logger.error(f"فشل حرق الترجمة: {str(e)}")
        raise FileNotFoundError("فشل في حرق الترجمة")

async def process_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    text = message.text
    
    # استخراج الروابط من الرسالة
    urls = re.findall(YOUTUBE_REGEX, text)
    valid_urls = [f"https://{match[2]}/watch?v={match[5]}" for match in urls]
    
    if not valid_urls:
        await message.reply_text("❌ الرابط غير صالح أو غير مدعوم")
        return
    
    # إنشاء مجلد مؤقت
    with tempfile.TemporaryDirectory() as temp_dir:
        status_message = await message.reply_text("🔄 جاري التنزيل والمعالجة...")
        processed_videos = []
        
        for i, url in enumerate(valid_urls, 1):
            try:
                video_file = await download_video(url, temp_dir)
                if not video_file:
                    raise FileNotFoundError("فشل تنزيل الفيديو")
                
                subtitle_file = await generate_subtitles(video_file, temp_dir)
                if not subtitle_file:
                    raise FileNotFoundError("فشل إنشاء الترجمة")
                
                subtitled_video = await burn_subtitles(video_file, subtitle_file, temp_dir)
                processed_videos.append(subtitled_video)
                
                await status_message.edit_text(f"✅ فيديو {i}/{len(valid_urls)} معالج بنجاح")
                
            except Exception as e:
                logger.error(f"خطأ في الفيديو {i}: {str(e)}")
                await status_message.edit_text("❌ حدث خطأ أثناء المعالجة")
                return
            
        # إرسال الفيديوهات مع الترجمة
        for video_path in processed_videos:
            await context.bot.send_video(
                chat_id=message.chat_id,
                video=open(video_path, 'rb'),
                supports_streaming=True
            )
        
        await status_message.edit_text(f"✅ تم معالجة {len(processed_videos)} فيديوهات بنجاح")

### تهيئة التطبيق

@app.before_serving
async def startup():
    global telegram_app, telegram_initialized
    try:
        telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # إضافة المعالجات
        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CommandHandler("help", help_command))
        telegram_app.add_handler(CommandHandler("status", status_command))
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_videos))
        telegram_app.add_error_handler(error_handler)
        
        # إعداد الـ Webhook
        webhook_url = f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
        await telegram_app.initialize()
        await telegram_app.bot.set_webhook(webhook_url)
        telegram_initialized = True
        
        logger.info("✅ البوت يعمل بنجاح!")
        if TELEGRAM_CHAT_ID:
            await telegram_app.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text="🚀 البوت يعمل الآن!"
            )
    except Exception as e:
        logger.error(f"❌ خطأ التهيئة: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise

@app.after_serving
async def shutdown():
    global telegram_app, telegram_initialized
    if telegram_app:
        await telegram_app.bot.delete_webhook()
        await telegram_app.stop()
        await telegram_app.shutdown()
        telegram_initialized = False
        if TELEGRAM_CHAT_ID:
            await telegram_app.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text="🛑 تم إيقاف البوت"
            )
        logger.info("✅ تم الإيقاف بنجاح!")

### معالجات الأوامر

@app.route(f'/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
async def webhook():
    if not telegram_app:
        return jsonify({"status": "error", "message": "البوت غير مهيأ"}), 500
    update = Update.de_json(await request.get_json(), telegram_app.bot)
    await telegram_app.process_update(update)
    return jsonify({"status": "success"}), 200

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"حدث خطأ: {context.error}", exc_info=context.error)
    sentry_sdk.capture_exception(context.error)
    if update and hasattr(update, 'effective_message'):
        await update.effective_message.reply_text("❌ حدث خطأ، يرجى المحاولة لاحقا")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"👋 مرحباً {user.first_name}!\n"
        "🎬 بوت تنزيل فيديوهات يوتيوب مع ترجمة عربية 🎬\n"
        "📝 *طريقة الاستخدام:*\n"
        "1️⃣ أرسل رابط فيديو واحد للتنزيل مع ترجمة\n"
        "2️⃣ أرسل عدة روابط (كل رابط في سطر) لدمجها في فيديو واحد\n"
        "⚠️ الحد الأقصى 5 فيديوهات\n"
        "🌟 مثال:\n"
        "```\n"
        "https://www.youtube.com/watch?v=zdLc6i9uNVc\n"
        "https://www.youtube.com/watch?v=I9YDayY7Dk4\n"
        "```\n"
        "🔄 ابدأ الآن!"
    )
    keyboard = [
        [InlineKeyboardButton("🔍 طريقة الاستخدام", callback_data="help")],
        [InlineKeyboardButton("📱 تواصل مع المطور", url="https://t.me/yourusername")]
    ]
    await update.message.reply_text(
        welcome_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_message = (
        "🔍 *دليل الاستخدام*\n"
        "1️⃣ لتنزيل فيديو واحد: أرسل رابط الفيديو\n"
        "2️⃣ لدمج عدة فيديوهات: أرسل روابطها في سطور منفصلة\n"
        "3️⃣ الأوامر المتاحة: /start, /help, /status\n"
        "⏱ مدة المعالجة تعتمد على طول الفيديو."
    )
    await update.message.reply_text(help_message, parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status = "✅ يعمل" if telegram_initialized else "❌ متوقف"
    await update.message.reply_text(f"حالة البوت: {status}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)