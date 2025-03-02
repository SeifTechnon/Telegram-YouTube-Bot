import os
import logging
import asyncio
from quart import Quart, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from yt_dlp import YoutubeDL
import whisper
import ffmpeg

# إعداد السجل (Logging)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# إعداد المتغيرات البيئية
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# التأكد من أن جميع المتغيرات البيئية مضبوطة
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ لم يتم تحديد TELEGRAM_BOT_TOKEN في المتغيرات البيئية!")

# تشغيل Quart لإنشاء Webhook
app = Quart(__name__)

# تهيئة Whisper لإنشاء الترجمة
whisper_model = whisper.load_model("base")

# معالج أمر start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال أوامر بدء البوت"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        logger.info(f"🟢 تم استلام أمر /start من المستخدم {user_id} (@{username})")

        welcome_message = (
            "👋 مرحبًا بك في بوت تنزيل فيديوهات يوتيوب مع الترجمة!\n\n"
            "🎬 *كيفية الاستخدام:*\n"
            "1️⃣ أرسل روابط فيديوهات يوتيوب (واحد أو أكثر).\n"
            "2️⃣ سيقوم البوت بتنزيل الفيديوهات وإضافة الترجمة العربية إليها.\n"
            "3️⃣ إذا أرسلت أكثر من رابط، سيقوم البوت بدمج الفيديوهات في فيديو واحد.\n"
            "4️⃣ سيرسل لك البوت الفيديو النهائي مباشرة.\n\n"
            "🔍 جاهز لبدء التنزيل؟ أرسل الروابط الآن!"
        )

        await update.message.reply_text(welcome_message, parse_mode="Markdown")
        logger.info(f"✅ تم إرسال رسالة الترحيب إلى المستخدم {user_id}")

    except Exception as e:
        logger.error(f"❌ خطأ في معالجة أمر /start: {e}")
        await update.message.reply_text("❌ حدث خطأ في بدء البوت. يرجى المحاولة مرة أخرى.")

# تنزيل الفيديو وإضافة الترجمة
def download_and_translate(url, output_filename):
    """تنزيل الفيديو وإضافة الترجمة"""
    try:
        # تنزيل الفيديو
        ydl_opts = {
            'format': '136',  # جودة 720p
            'outtmpl': f'{output_filename}.%(ext)s',
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_path = ydl.prepare_filename(info)
            logger.info(f"✅ تم تنزيل الفيديو: {video_path}")

        # إنشاء الترجمة باستخدام Whisper
        logger.info("🎙️ جاري إنشاء الترجمة...")
        result = whisper_model.transcribe(video_path, language="ar")
        subtitle_path = f"{output_filename}.srt"
        with open(subtitle_path, "w", encoding="utf-8") as f:
            for segment in result['segments']:
                start_time = segment['start']
                end_time = segment['end']
                text = segment['text']
                f.write(f"{start_time} --> {end_time}\n{text}\n\n")
        logger.info(f"✅ تم إنشاء الترجمة: {subtitle_path}")

        # حرق الترجمة في الفيديو
        output_video_path = f"{output_filename}_with_subtitles.mp4"
        ffmpeg.input(video_path).output(
            output_video_path,
            vf=f"subtitles={subtitle_path}:force_style='FontSize=18,Alignment=2'"
        ).run()
        logger.info(f"✅ تم حرق الترجمة في الفيديو: {output_video_path}")

        return output_video_path

    except Exception as e:
        logger.error(f"❌ فشل في تنزيل الفيديو أو إضافة الترجمة: {e}")
        raise e

# دمج الفيديوهات
def merge_videos(video_paths, output_path):
    """دمج الفيديوهات في فيديو واحد"""
    try:
        inputs = [ffmpeg.input(video) for video in video_paths]
        ffmpeg.concat(*inputs, v=1, a=1).output(output_path).run()
        logger.info(f"✅ تم دمج الفيديوهات في: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"❌ فشل في دمج الفيديوهات: {e}")
        raise e

# معالج الرسائل النصية (لتنزيل الفيديوهات)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع روابط يوتيوب"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        urls = update.message.text.strip().split()

        logger.info(f"📩 تم استلام روابط من المستخدم {user_id} (@{username}): {urls}")

        # التحقق من صحة الروابط
        valid_domains = ['youtube.com', 'youtu.be']
        if not all(any(domain in url for domain in valid_domains) for url in urls):
            await update.message.reply_text("❌ أحد الروابط غير صالح. يرجى إرسال روابط يوتيوب صحيحة.")
            return

        # إرسال رسالة "انتظر"
        await update.message.reply_text("⏳ جاري معالجة الروابط... قد يستغرق ذلك بضع دقائق.")

        # تنزيل الفيديوهات وإضافة الترجمة
        video_paths = []
        for i, url in enumerate(urls):
            output_filename = f"video_{user_id}_{i}"
            video_path = download_and_translate(url, output_filename)
            video_paths.append(video_path)

        # إذا كان هناك أكثر من فيديو، قم بدمجهم
        if len(video_paths) > 1:
            merged_video_path = f"merged_video_{user_id}.mp4"
            merge_videos(video_paths, merged_video_path)
            final_video_path = merged_video_path
        else:
            final_video_path = video_paths[0]

        # إرسال الفيديو النهائي
        await update.message.reply_video(video=open(final_video_path, "rb"), caption="🎬 الفيديو النهائي مع الترجمة العربية")
        logger.info(f"✅ تم إرسال الفيديو إلى المستخدم {user_id}")

    except Exception as e:
        logger.error(f"❌ حدث خطأ أثناء معالجة الروابط: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الروابط: {str(e)}\nيرجى المحاولة مرة أخرى لاحقًا.")

# إنشاء تطبيق Telegram
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# إضافة معالجات الأوامر والرسائل
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# نقطة نهاية لاستقبال تحديثات Webhook
@app.route("/webhook", methods=["POST"])
async def webhook():
    """استقبال تحديثات Telegram وإرسالها إلى البوت"""
    try:
        json_data = await request.get_json()
        update = Update.de_json(json_data, telegram_app.bot)
        await telegram_app.process_update(update)
        return "✅ Webhook processed!", 200
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة طلب webhook: {e}")
        return jsonify({"error": str(e)}), 500

# بدء تشغيل البوت
if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=PORT)