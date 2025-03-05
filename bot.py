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

# إنشاء تطبيق Quart
app = Quart(__name__)
PORT = int(os.environ.get('PORT', 8080))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

# إعداد Sentry
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[QuartIntegration()],
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
    environment="production",
    release="v1.0.0",
    attach_stacktrace=True,
    send_default_pii=True,
)

# إعداد السجل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# الحصول على رمز البوت ومعرف الدردشة من المتغيرات البيئية
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("⚠️ لم يتم تعيين TELEGRAM_BOT_TOKEN في المتغيرات البيئية!")
    raise ValueError("TELEGRAM_BOT_TOKEN is not set!")

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # معرف الدردشة لإرسال الإشعارات إليك

# استخدام Webhook فقط في الإنتاج
USE_WEBHOOK = True  # تم إجباره على True لأننا في بيئة Railway

# نمط للتعرف على روابط يوتيوب
YOUTUBE_REGEX = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/(watch\?v=|shorts/)?([a-zA-Z0-9_-]{11})'

# متغير لتخزين تطبيق تليجرام
telegram_app = None
telegram_initialized = False

# إضافة مسار صحة التطبيق (healthcheck)
@app.route('/health')
async def health_check():
    logger.info("تم استقبال طلب للتحقق من صحة التطبيق")
    return jsonify({
        "status": "healthy",
        "message": "Bot is running",
        "webhook_mode": USE_WEBHOOK,
        "initialized": telegram_initialized
    }), 200

# مسار webhook لتلقي التحديثات من تليجرام
@app.route(f'/webhook/{TELEGRAM_BOT_TOKEN}', methods=['POST'])
async def webhook():
    if not telegram_app:
        logger.error("Telegram application not initialized")
        return jsonify({"status": "error", "message": "Telegram application not initialized"}), 500

    # الحصول على بيانات التحديث
    update_data = await request.get_json()
    logger.info("تم استقبال تحديث من تليجرام")

    # تحويل البيانات إلى كائن Update
    update = Update.de_json(update_data, telegram_app.bot)

    # معالجة التحديث
    await telegram_app.process_update(update)

    return jsonify({"status": "success"}), 200

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج الأخطاء العامة"""
    logger.error(f"حدث خطأ: {context.error}")
    sentry_sdk.capture_exception(context.error)
    error_message = f"❌ حدث خطأ: {str(context.error)}"
    
    # إرسال رسالة للمستخدم إذا كان هناك تحديث متاح
    if update and hasattr(update, 'effective_message') and update.effective_message:
        await update.effective_message.reply_text(
            "❌ حدث خطأ أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقاً."
        )
    
    # إرسال إشعار إليك (المدير) إذا كان TELEGRAM_CHAT_ID موجودًا
    if TELEGRAM_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"⚠️ تنبيه إداري:\n{error_message}\nمن المستخدم: {update.effective_user.id if update and update.effective_user else 'غير معروف'}"
            )
        except Exception as e:
            logger.error(f"فشل إرسال إشعار للمدير: {str(e)}")

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

    keyboard = [
        [InlineKeyboardButton("🔍 طريقة الاستخدام", callback_data="help")],
        [InlineKeyboardButton("📱 تواصل مع المطور", url="https://t.me/SeifTechnon")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_message, parse_mode="Markdown", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """الرد على أمر /help"""
    help_message = (
        "🔍 *دليل استخدام البوت*\n\n"
        "هذا البوت يقوم بتنزيل فيديوهات يوتيوب وإضافة ترجمة عربية تلقائية إليها. إليك كيفية استخدامه:\n\n"
        "1️⃣ *لتنزيل فيديو واحد:*\n"
        "أرسل رابط الفيديو من يوتيوب مباشرة\n\n"
        "2️⃣ *لدمج عدة فيديوهات:*\n"
        "أرسل عدة روابط، كل رابط في سطر منفصل (الحد الأقصى 5 فيديوهات)\n\n"
        "3️⃣ *أوامر متاحة:*\n"
        "/start - بدء استخدام البوت\n"
        "/help - عرض رسالة المساعدة\n"
        "/status - التحقق من حالة البوت\n\n"
        "⏱ *المدة المتوقعة:*\n"
        "تعتمد مدة المعالجة على طول الفيديوهات وعددها. يرجى التحلي بالصبر أثناء المعالجة."
    )
    await update.message.reply_text(help_message, parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة نقرات الأزرار التفاعلية"""
    query = update.callback_query
    await query.answer()
    if query.data == "help":
        help_message = (
            "🔍 *دليل استخدام البوت*\n\n"
            "هذا البوت يقوم بتنزيل فيديوهات يوتيوب وإضافة ترجمة عربية تلقائية إليها. إليك كيفية استخدامه:\n\n"
            "1️⃣ *لتنزيل فيديو واحد:*\n"
            "أرسل رابط الفيديو من يوتيوب مباشرة\n\n"
            "2️⃣ *لدمج عدة فيديوهات:*\n"
            "أرسل عدة روابط، كل رابط في سطر منفصل (الحد الأقصى 5 فيديوهات)\n\n"
            "⏱ *المدة المتوقعة:*\n"
            "تعتمد مدة المعالجة على طول الفيديوهات وعددها. يرجى التحلي بالصبر أثناء المعالجة."
        )
        await query.edit_message_text(text=help_message, parse_mode="Markdown")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """التحقق من حالة البوت"""
    await update.message.reply_text(
        "✅ البوت يعمل بشكل طبيعي\n"
        "🔄 وضع الاتصال: Webhook\n"
        "⏱ وقت الاستجابة: تقريباً 1-2 ثانية"
    )

async def extract_youtube_links(text: str) -> list:
    """استخراج روابط يوتيوب من النص"""
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
    """الحصول على معلومات الفيديو باستخدام yt-dlp"""
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
        logger.error(f"خطأ في الحصول على معلومات الفيديو: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise Exception(f"فشل في الوصول إلى معلومات الفيديو: {str(e)}")

async def download_video(video_url: str, output_dir: str, message_ref) -> str:
    """تنزيل فيديو من يوتيوب"""
    try:
        info = get_video_info(video_url)
        video_id = info['id']
        video_title = info['title']
        await message_ref.edit_text(f"⬇️ جاري تنزيل الفيديو:\n{video_title}\n\n⏳ يرجى الانتظار...")
        output_file = os.path.join(output_dir, f"{video_id}.mp4")
        ydl_opts = {
            'format': 'best[height<=720]/best',
            'merge_output_format': 'mp4',
            'outtmpl': output_file,
            'quiet': True,
            'socket_timeout': 60,
            'retries': 5,
        }
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        if not os.path.exists(output_file):
            raise Exception("لم يتم إنشاء ملف الفيديو بعد التنزيل")
        return output_file
    except Exception as e:
        logger.error(f"خطأ في تنزيل الفيديو: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise Exception(f"فشل في تنزيل الفيديو: {str(e)}")

async def generate_subtitles(video_file: str, output_dir: str, message_ref) -> str:
    """توليد ملف الترجمة باستخدام Whisper"""
    try:
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
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"خطأ في استخراج النص: {stderr.decode()}")
            raise Exception("فشل في استخراج النص من الفيديو")
        if not os.path.exists(srt_file):
            srt_files = [f for f in os.listdir(output_dir) if f.endswith('.srt') and f.startswith(base_name)]
            if srt_files:
                srt_file = os.path.join(output_dir, srt_files[0])
            else:
                raise Exception("لم يتم إنشاء ملف الترجمة")
        return srt_file
    except Exception as e:
        logger.error(f"خطأ في استخراج الترجمة: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise Exception(f"فشل في استخراج النص من الفيديو: {str(e)}")

async def burn_subtitles(video_file: str, subtitle_file: str, output_dir: str, message_ref) -> str:
    """حرق الترجمة في الفيديو"""
    try:
        await message_ref.edit_text("🔥 جاري دمج الترجمة مع الفيديو...\n\n⏳ يرجى الانتظار...")
        base_name = os.path.basename(video_file).split('.')[0]
        output_file = os.path.join(output_dir, f"{base_name}_subtitled.mp4")
        ffmpeg_cmd = [
            "ffmpeg", "-i", video_file,
            "-vf", f"subtitles={subtitle_file}:force_style='FontName=Arial,FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BackColour=&H000000,BorderStyle=1,Outline=1,Shadow=1,Alignment=2'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-y", output_file
        ]
        process = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"خطأ في حرق الترجمة: {stderr.decode()}")
            raise Exception("فشل في حرق الترجمة في الفيديو")
        return output_file
    except Exception as e:
        logger.error(f"خطأ في دمج الترجمة: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise Exception(f"فشل في دمج الترجمة مع الفيديو: {str(e)}")

async def merge_videos(video_files: list, output_dir: str, message_ref) -> str:
    """دمج عدة مقاطع فيديو في ملف واحد"""
    try:
        await message_ref.edit_text(f"🔄 جاري دمج {len(video_files)} فيديوهات في ملف واحد...\n\n⏳ يرجى الانتظار...")
        list_file = os.path.join(output_dir, "filelist.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for video_file in video_files:
                video_file = video_file.replace("'", "'\\''")
                f.write(f"file '{video_file}'\n")
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
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.error(f"خطأ في دمج الفيديوهات: {stderr.decode()}")
            raise Exception("فشل في دمج مقاطع الفيديو")
        return output_file
    except Exception as e:
        logger.error(f"خطأ في دمج الفيديوهات: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise Exception(f"فشل في دمج الفيديوهات: {str(e)}")

async def process_videos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة رسالة تحتوي على روابط فيديو"""
    user_id = update.effective_user.id  # معرف المستخدم لإرسال الإشعار
    try:
        message_text = update.message.text
        youtube_links = await extract_youtube_links(message_text)
        if not youtube_links:
            await update.message.reply_text(
                "❌ لم يتم العثور على روابط يوتيوب صالحة في رسالتك!\n\n"
                "يرجى إرسال روابط بتنسيق صحيح مثل:\n"
                "https://www.youtube.com/watch?v=abcdefghijk"
            )
            return
        if len(youtube_links) > 5:
            await update.message.reply_text(
                "⚠️ لقد تجاوزت الحد الأقصى المسموح به (5 فيديوهات).\n"
                f"سأقوم بمعالجة أول 5 فيديوهات فقط من أصل {len(youtube_links)}."
            )
            youtube_links = youtube_links[:5]
        status_message = await update.message.reply_text(
            f"🔍 تم العثور على {len(youtube_links)} روابط يوتيوب.\n"
            "⏳ جاري بدء المعالجة... يرجى الانتظار."
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            processed_videos = []
            for i, video_url in enumerate(youtube_links):
                try:
                    await status_message.edit_text(
                        f"⚙️ جاري معالجة الفيديو {i+1} من {len(youtube_links)}...\n\n"
                        f"🔗 {video_url}\n\n"
                        "⏳ يرجى الانتظار..."
                    )
                    video_file = await download_video(video_url, temp_dir, status_message)
                    subtitle_file = await generate_subtitles(video_file, temp_dir, status_message)
                    subtitled_video = await burn_subtitles(video_file, subtitle_file, temp_dir, status_message)
                    processed_videos.append(subtitled_video)
                except Exception as e:
                    logger.error(f"خطأ في معالجة الفيديو {i+1}: {str(e)}")
                    sentry_sdk.capture_exception(e)
                    await status_message.edit_text(
                        f"⚠️ حدث خطأ أثناء معالجة الفيديو {i+1}:\n{str(e)}\n\n"
                        "🔄 المتابعة مع الفيديوهات التالية..."
                    )
                    await asyncio.sleep(3)
            if len(processed_videos) == 0:
                await status_message.edit_text("❌ لم يتم معالجة أي فيديو بنجاح.")
                return
            await status_message.edit_text(
                f"✅ تمت معالجة {len(processed_videos)} من {len(youtube_links)} فيديوهات بنجاح.\n"
                "⏳ جاري إعداد الفيديو النهائي..."
            )
            final_video = await merge_videos(processed_videos, temp_dir, status_message) if len(processed_videos) > 1 else processed_videos[0]
            await status_message.edit_text("✅ اكتملت المعالجة! جاري إرسال الفيديو...")
            try:
                file_size_mb = os.path.getsize(final_video) / (1024 * 1024)
                if file_size_mb > 50:
                    await status_message.edit_text(
                        f"⚠️ الفيديو النهائي كبير جدًا ({file_size_mb:.1f} ميجابايت).\n"
                        "جاري تقسيمه لإرساله..."
                    )
                with open(final_video, "rb") as video_file:
                    await update.message.reply_video(
                        video=video_file,
                        caption=(
                            "🎬 تم معالجة الفيديو بنجاح!\n"
                            f"✅ عدد الفيديوهات المعالجة: {len(processed_videos)} من {len(youtube_links)}\n"
                            "🔤 تمت إضافة الترجمة باللغة العربية"
                        ),
                        supports_streaming=True,
                        width=1280,
                        height=720
                    )
                await status_message.delete()
                # إرسال إشعار إليك عند النجاح
                if TELEGRAM_CHAT_ID:
                    try:
                        await context.bot.send_message(
                            chat_id=TELEGRAM_CHAT_ID,
                            text=f"✅ تمت معالجة وإرسال فيديو بنجاح!\nالمستخدم: {user_id}\nعدد الفيديوهات: {len(processed_videos)} من {len(youtube_links)}"
                        )
                    except Exception as e:
                        logger.error(f"فشل إرسال إشعار للمدير: {str(e)}")
            except Exception as e:
                logger.error(f"خطأ في إرسال الفيديو: {str(e)}")
                sentry_sdk.capture_exception(e)
                await status_message.edit_text(
                    f"❌ تم معالجة الفيديو بنجاح، لكن حدث خطأ في إرساله:\n{str(e)}\n\n"
                    "قد يكون حجم الفيديو كبيرًا جدًا للإرسال عبر تليجرام."
                )
                # إرسال إشعار إليك عند فشل الإرسال
                if TELEGRAM_CHAT_ID:
                    try:
                        await context.bot.send_message(
                            chat_id=TELEGRAM_CHAT_ID,
                            text=f"⚠️ تنبيه إداري:\nفشل إرسال الفيديو للمستخدم {user_id}\nالخطأ: {str(e)}"
                        )
                    except Exception as e:
                        logger.error(f"فشل إرسال إشعار للمدير: {str(e)}")
    except Exception as e:
        logger.error(f"خطأ عام في معالجة الفيديوهات: {str(e)}")
        sentry_sdk.capture_exception(e)
        error_message = f"❌ حدث خطأ أثناء معالجة الفيديوهات: {str(e)}"
        try:
            if 'status_message' in locals():
                await status_message.edit_text(error_message)
            else:
                await update.message.reply_text(error_message)
        except Exception:
            logger.error("لم يتمكن من إرسال رسالة الخطأ إلى المستخدم")

def create_telegram_app():
    """إنشاء وتكوين تطبيق تليجرام"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_videos))
    application.add_error_handler(error_handler)
    return application

telegram_app = None

@app.before_serving
async def startup():
    """تنفيذ هذه الدالة عند بدء تشغيل التطبيق"""
    global telegram_app, telegram_initialized
    logger.info("بدء تشغيل البوت...")
    try:
        telegram_app = create_telegram_app()
        logger.info("✅ تم إنشاء تطبيق التليجرام")
        await telegram_app.initialize()
        logger.info("✅ تم تهيئة التطبيق")
        webhook_url = f"{WEBHOOK_URL}/webhook/{TELEGRAM_BOT_TOKEN}"
        logger.info(f"🔄 جاري تعيين الويب هوك: {webhook_url}")
        await telegram_app.bot.set_webhook(webhook_url)
        logger.info("✅ تم تعيين الويب هوك")
        telegram_initialized = True
        logger.info("🚀 بدء التشغيل بنجاح!")
        # إرسال إشعار إليك عند بدء التشغيل بنجاح
        if TELEGRAM_CHAT_ID:
            try:
                await telegram_app.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text="🚀 البوت بدأ التشغيل بنجاح!"
                )
            except Exception as e:
                logger.error(f"فشل إرسال إشعار بدء التشغيل للمدير: {str(e)}")
    except Exception as e:
        logger.error(f"❌ فشل التهيئة: {str(e)}")
        sentry_sdk.capture_exception(e)
        raise

@app.after_serving
async def shutdown():
    """تنفيذ هذه الدالة عند إيقاف التطبيق"""
    global telegram_app, telegram_initialized
    logger.info("إيقاف تشغيل البوت...")
    if telegram_app is not None:
        await telegram_app.bot.delete_webhook()
        await telegram_app.stop()
        await telegram_app.shutdown()
        # إرسال إشعار إليك عند إيقاف التشغيل
        if TELEGRAM_CHAT_ID:
            try:
                await telegram_app.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text="🛑 تم إيقاف تشغيل البوت."
                )
            except Exception as e:
                logger.error(f"فشل إرسال إشعار إيقاف التشغيل للمدير: {str(e)}")
    telegram_initialized = False
    logger.info("تم إيقاف تشغيل البوت بنجاح!")

if __name__ == "__main__":
    pass
