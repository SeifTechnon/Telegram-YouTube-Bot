import os
import logging
import requests
import ffmpeg
from quart import Quart, request, jsonify
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from yt_dlp import YoutubeDL
import whisper

# إعداد السجل (Logging) بمزيد من التفاصيل
logging.basicConfig(
    filename="logs.txt",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# إعداد المتغيرات البيئية
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RAILWAY_URL = os.getenv("RAILWAY_URL", "").strip()

# طباعة القيم للتأكد من أنها مُعدة بشكل صحيح
if TELEGRAM_BOT_TOKEN:
    logger.info(f"🔹 TELEGRAM_BOT_TOKEN = {TELEGRAM_BOT_TOKEN[:5]}... (تم إخفاء باقي التوكن لأمان أكثر)")
else:
    logger.error("❌ TELEGRAM_BOT_TOKEN غير محدد!")

logger.info(f"🔹 TELEGRAM_CHAT_ID = {TELEGRAM_CHAT_ID}")
logger.info(f"🔹 RAILWAY_URL = {RAILWAY_URL}")

# التأكد من أن جميع المتغيرات البيئية مضبوطة
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ لم يتم تحديد TELEGRAM_BOT_TOKEN في المتغيرات البيئية!")
if not RAILWAY_URL:
    raise ValueError("❌ لم يتم تحديد RAILWAY_URL في المتغيرات البيئية!")

# تشغيل Quart لإنشاء Webhook
app = Quart(__name__)

# قائمة لتخزين روابط الفيديوهات للمستخدمين
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال أوامر بدء البوت"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        logger.info(f"🟢 تم استلام أمر /start من المستخدم {user_id} (@{username})")

        welcome_message = (
            f"👋 مرحباً بك {username} في بوت تنزيل فيديوهات يوتيوب مع الترجمة!\n\n"
            "🎬 *كيفية الاستخدام:*\n"
            "1️⃣ أرسل روابط فيديوهات يوتيوب متعددة\n"
            "2️⃣ انتظر حتى يتم تنزيل الفيديوهات ومعالجتها\n"
            "3️⃣ سيتم دمج الفيديوهات في فيديو واحد وإرساله لك\n\n"
            "🔍 جاهز لبدء تنزيل أول فيديو؟ أرسل الروابط الآن!"
        )

        await update.message.reply_text(welcome_message, parse_mode="Markdown")

        if update.message.chat_id in user_data:
            del user_data[update.message.chat_id]

    except Exception as e:
        logger.error(f"❌ خطأ في معالجة أمر /start: {e}")
        await update.message.reply_text("❌ حدث خطأ في بدء البوت. يرجى المحاولة مرة أخرى.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /help"""
    try:
        help_text = (
            "📚 *دليل المساعدة:*\n\n"
            "• للبدء: أرسل /start\n"
            "• لتنزيل فيديو: أرسل روابط يوتيوب مباشرة\n"
            "• للمساعدة: أرسل /help\n\n"
            "ℹ️ لتنزيل فيديو مع الترجمة العربية، ما عليك سوى إرسال روابط يوتيوب واتباع التعليمات."
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة أمر /help: {e}")
        await update.message.reply_text("❌ حدث خطأ في عرض المساعدة. يرجى المحاولة مرة أخرى.")

def download_video(url, format_id, chat_id):
    """تنزيل الفيديو مع الترجمة العربية"""
    logger.info(f"⬇️ جاري تنزيل الفيديو بجودة {format_id}")
    try:
        output_filename = f"video_{chat_id}"

        ydl_opts = {
            'format': format_id,
            'outtmpl': f'{output_filename}.%(ext)s',
            'subtitleslangs': ['ar'],
            'writesubtitles': True,
            'writeautomaticsub': True,
            'postprocessors': [{
                'key': 'FFmpegSubtitlesConvertor',
                'format': 'srt',
            }],
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get('ext', 'mp4')
            video_path = f"{output_filename}.{ext}"
            video_title = info.get('title', 'فيديو')

            subtitle_files = [f for f in os.listdir() if f.startswith(output_filename) and f.endswith('.srt')]
            subtitle_path = subtitle_files[0] if subtitle_files else None

            if not subtitle_path:
                logger.warning(f"⚠️ لم يتم العثور على ملفات ترجمة للفيديو {video_title}")
            else:
                logger.info(f"✅ تم العثور على ملف الترجمة: {subtitle_path}")

            return video_path, video_title, subtitle_path
    except Exception as e:
        logger.error(f"❌ فشل في تنزيل الفيديو: {e}")
        raise e

def burn_subtitles(video_path, subtitle_path, output_path):
    """حرق الترجمة داخل الفيديو"""
    logger.info(f"🔥 جاري حرق الترجمة في الفيديو: {video_path}")
    try:
        if not subtitle_path or not os.path.exists(subtitle_path):
            logger.warning(f"⚠️ ملف الترجمة غير موجود: {subtitle_path}")
            return video_path

        ffmpeg_options = {
            'vf': f"subtitles='{subtitle_path}':force_style='FontSize=18,Alignment=2,BorderStyle=3,Outline=2,Shadow=1,MarginV=25'"
        }

        ffmpeg.input(video_path).output(output_path, **ffmpeg_options).run()

        logger.info("✅ تم حرق الترجمة بنجاح")
        return output_path
    except Exception as e:
        logger.error(f"❌ فشل في حرق الترجمة: {e}")
        return video_path

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع رسالة المستخدم عند إرسال روابط يوتيوب"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        urls = update.message.text.strip().split()

        logger.info(f"📩 تم استلام رسالة من المستخدم {user_id} (@{username}): {urls}")

        valid_domains = ['youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com']
        if not all(any(domain in url for domain in valid_domains) for url in urls):
            await update.message.reply_text("❌ أحد الروابط غير صالح. يرجى إرسال روابط يوتيوب صحيحة.")
            return

        status_message = await update.message.reply_text("⏳ جاري تحليل الروابط... قد يستغرق ذلك بضع ثوانٍ.")

        video_paths = []
        for url in urls:
            video_path, video_title, subtitle_path = download_video(url, '136', user_id)
            output_path = f"output_{user_id}.mp4"
            final_video_path = burn_subtitles(video_path, subtitle_path, output_path)
            video_paths.append(final_video_path)

        await status_message.edit_text("⏳ جاري دمج الفيديوهات...")

        merged_video_path = f"merged_video_{user_id}.mp4"
        merge_videos(video_paths, merged_video_path)

        await status_message.edit_text("📤 جارِ إرسال الفيديو المدمج...")

        result = await send_video(merged_video_path, update.message.chat_id, "فيديو مدمج")

        if result:
            await status_message.edit_text("✅ تم إرسال الفيديو المدمج بنجاح!")

        cleanup_files(video_paths + [merged_video_path])

        if update.message.chat_id in user_data:
            del user_data[update.message.chat_id]

    except Exception as e:
        logger.error(f"❌ حدث خطأ أثناء معالجة الروابط: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الروابط: {str(e)}\nيرجى المحاولة مرة أخرى لاحقًا.")

def merge_videos(video_paths, output_path):
    """دمج الفيديوهات في فيديو واحد"""
    logger.info(f"🎬 جاري دمج الفيديوهات في ملف واحد: {output_path}")
    try:
        inputs = [ffmpeg.input(video_path) for video_path in video_paths]
        ffmpeg.concat(*inputs, v=1, a=1).output(output_path).run()
        logger.info("✅ تم دمج الفيديوهات بنجاح")
    except Exception as e:
        logger.error(f"❌ فشل في دمج الفيديوهات: {e}")
        raise e

async def send_video(video_path, chat_id, video_title="فيديو يوتيوب"):
    """إرسال الفيديو النهائي إلى تيليجرام"""
    logger.info(f"📤 جاري إرسال الفيديو إلى المستخدم {chat_id}")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        if not os.path.exists(video_path):
            logger.error(f"❌ ملف الفيديو غير موجود: {video_path}")
            await bot.send_message(chat_id=chat_id, text="❌ حدث خطأ: ملف الفيديو غير موجود")
            return False

        file_size = os.path.getsize(video_path) / (1024 * 1024)

        if file_size > 50:
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ حجم الفيديو كبير جدًا ({file_size:.1f} ميجابايت). تيليجرام يسمح فقط بإرسال ملفات حتى 50 ميجابايت."
            )
            return False

        with open(video_path, 'rb') as video:
            await bot.send_video(
                chat_id=chat_id,
                video=video,
                caption=f"🎬 {video_title} | تم التحميل بواسطة بوت تنزيل يوتيوب 🤖",
                supports_streaming=True
            )
        logger.info("✅ تم إرسال الفيديو بنجاح")
        return True
    except Exception as e:
        logger.error(f"❌ فشل إرسال الفيديو: {e}")
        await bot.send_message(chat_id=chat_id, text=f"❌ فشل في إرسال الفيديو: {str(e)}")
        return False

def cleanup_files(file_paths):
    """تنظيف الملفات بعد الاستخدام"""
    for file_path in file_paths:
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"🧹 تم حذف الملف: {file_path}")
        except Exception as e:
            logger.error(f"❌ فشل في حذف الملف {file_path}: {e}")

async def error_handler(update, context):
    """معالجة الأخطاء غير المتوقعة"""
    logger.error(f"🚨 خطأ غير معالج: {context.error}")

    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ حدث خطأ غير متوقع أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقًا."
        )

telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

telegram_app.add_error_handler(error_handler)

@app.route("/", methods=["GET"])
async def health_check():
    """نقطة نهاية للتحقق من صحة البوت"""
    return jsonify({
        "status": "ok",
        "message": "Bot is running",
        "version": "1.1.0",
        "webhook_url": f"{RAILWAY_URL}/webhook"
    }), 200

@app.route("/health", methods=["GET"])
async def health_check_endpoint():
    """نقطة نهاية للتحقق من صحة التطبيق"""
    return jsonify({"status": "ok", "message": "Bot is healthy"}), 200

@app.route("/webhook", methods=["POST"])
async def webhook():
    """استقبال تحديثات Telegram وإرسالها إلى البوت"""
    try:
        logger.info("📩 تم استلام طلب webhook")
        json_data = await request.get_json()

        if json_data and 'update_id' in json_data:
            update_id = json_data.get('update_id')
            message = json_data.get('message', {})
            user = message.get('from', {})
            user_id = user.get('id')
            username = user.get('username', 'غير متوفر')
            text = message.get('text', '')

            logger.info(f"📦 تحديث جديد: ID={update_id}, من: {user_id} (@{username}), النص: {text[:20]}...")

        # إصلاح مشكلة `is_bot`
        if 'from' in json_data.get('message', {}):
            json_data['message']['from']['is_bot'] = False  # <-- إضافة حقل `is_bot`

        # تحويل البيانات إلى كائن Update
        update = Update.de_json(json_data, telegram_app.bot)
        await telegram_app.update_queue.put(update)  # <-- تم إضافة await هنا

        return "✅ Webhook received!", 200
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة طلب webhook: {e}")
        return jsonify({"error": str(e)}), 500

def set_webhook(max_retries=3):
    """تسجيل Webhook مع Telegram مع محاولات متكررة"""
    webhook_url = f"{RAILWAY_URL}/webhook"
    logger.info(f"🔗 محاولة تسجيل Webhook على: {webhook_url}")

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"🔄 محاولة {attempt}/{max_retries} لتسجيل Webhook")

            delete_response = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook",
                timeout=10
            )
            logger.info(f"🗑️ حالة حذف Webhook السابق: {delete_response.status_code} - {delete_response.json()}")

            response = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
                params={"url": webhook_url, "drop_pending_updates": "true", "max_connections": 100},
                timeout=10
            )
            response_json = response.json()

            if response.status_code == 200 and response_json.get("ok"):
                logger.info("✅ تم تسجيل الـ Webhook بنجاح!")

                info_response = requests.get(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo",
                    timeout=10
                )
                webhook_info = info_response.json()
                logger.info(f"ℹ️ معلومات Webhook: {webhook_info}")

                if webhook_info.get("result", {}).get("url") == webhook_url:
                    return True
                else:
                    logger.warning("⚠️ عنوان URL المسجل لا يتطابق مع العنوان المطلوب!")
            else:
                logger.error(f"❌ فشل تسجيل Webhook (محاولة {attempt}/{max_retries}): {response_json}")

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ خطأ في الاتصال عند تسجيل Webhook (محاولة {attempt}/{max_retries}): {e}")

        if attempt < max_retries:
            logger.info(f"⏳ الانتظار قبل إعادة محاولة تسجيل Webhook...")
            import time
            time.sleep(5)

    logger.error("❌ فشلت جميع محاولات تسجيل Webhook!")
    return False

if __name__ == "__main__":
    webhook_registered = set_webhook(max_retries=3)

    if webhook_registered:
        logger.info("🚀 تم تسجيل Webhook بنجاح وجاري بدء تشغيل الخادم...")
    else:
        logger.warning("⚠️ بدء تشغيل الخادم مع فشل تسجيل Webhook!")

    PORT = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=PORT)