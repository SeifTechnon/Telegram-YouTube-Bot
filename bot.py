import os
import logging
import requests
import ffmpeg
from flask import Flask, request, jsonify
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from yt_dlp import YoutubeDL

# ✅ إعداد السجل (Logging) بمزيد من التفاصيل
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ✅ إعداد المتغيرات البيئية
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
RAILWAY_URL = os.getenv("RAILWAY_URL", "").strip()  # إزالة المسافات الزائدة

# ✅ طباعة القيم للتأكد من أنها مُعدة بشكل صحيح
logger.info(f"🔹 TELEGRAM_BOT_TOKEN = {TELEGRAM_BOT_TOKEN[:5]}... (تم إخفاء باقي التوكن لأمان أكثر)")
logger.info(f"🔹 TELEGRAM_CHAT_ID = {TELEGRAM_CHAT_ID}")
logger.info(f"🔹 RAILWAY_URL = {RAILWAY_URL}")

# 🔍 التأكد من أن جميع المتغيرات البيئية مضبوطة
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("❌ لم يتم تحديد TELEGRAM_BOT_TOKEN في المتغيرات البيئية!")
if not RAILWAY_URL:
    raise ValueError("❌ لم يتم تحديد RAILWAY_URL في المتغيرات البيئية!")

# ✅ تشغيل Flask لإنشاء Webhook
app = Flask(__name__)

# ✅ قائمة لتخزين روابط الفيديوهات للمستخدمين
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال أوامر بدء البوت"""
    logger.info(f"🟢 تم استلام أمر /start من المستخدم {update.message.from_user.id}")
    await update.message.reply_text("🔹 أرسل رابط فيديو من يوتيوب وسأقوم بتنزيله لك مع الترجمة العربية!")

def get_video_formats(url):
    """استرجاع قائمة الجودات والترميزات المتاحة للفيديو"""
    logger.info(f"🔍 جاري استرجاع قائمة الجودات لـ: {url}")
    try:
        ydl_opts = {'listformats': True}
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = [
                f"{fmt['format_id']} - {fmt['ext']} - {fmt.get('format_note', 'Unknown')} ({fmt['fps']} FPS)"
                for fmt in info.get('formats', []) if fmt.get('ext') in ['mp4', 'mkv']
            ]
        logger.info(f"✅ تم استرجاع {len(formats)} جودة متاحة")
        return formats
    except Exception as e:
        logger.error(f"❌ خطأ عند استرجاع قائمة الجودات: {e}")
        return ["❌ حدث خطأ في معالجة الرابط. تأكد من أنه رابط يوتيوب صالح."]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع رسالة المستخدم عند إرسال رابط يوتيوب"""
    logger.info(f"📩 تم استلام رسالة من المستخدم {update.message.from_user.id}: {update.message.text}")
    
    url = update.message.text
    
    # التحقق من صحة الرابط (تحقق بسيط)
    if not ('youtube.com' in url or 'youtu.be' in url):
        await update.message.reply_text("❌ الرابط غير صالح. يرجى إرسال رابط يوتيوب صحيح.")
        return
        
    await update.message.reply_text("⏳ جاري تحليل الرابط...")
    
    try:
        formats = get_video_formats(url)
        
        if len(formats) == 0:
            await update.message.reply_text("❌ لم يتم العثور على جودات متاحة للتنزيل.")
            return
            
        format_list = "\n".join(formats[:10])  # اعرض أول 10 جودات فقط لمنع رسائل طويلة جدًا
        
        await update.message.reply_text(f"🔽 اختر جودة الفيديو من القائمة التالية بإرسال رقم الجودة (مثال: 22):\n{format_list}")

        # حفظ الرابط لاستخدامه لاحقًا عند اختيار الجودة
        user_data[update.message.chat_id] = url
        
    except Exception as e:
        logger.error(f"❌ خطأ عند معالجة الرابط: {e}")
        await update.message.reply_text("❌ حدث خطأ عند معالجة الرابط. يرجى المحاولة مرة أخرى لاحقًا.")

def download_video(url, format_id):
    """تنزيل الفيديو مع الترجمة العربية"""
    logger.info(f"⬇️ جاري تنزيل الفيديو بجودة {format_id}")
    try:
        ydl_opts = {
            'format': format_id,
            'outtmpl': 'video.%(ext)s',
            'subtitleslangs': ['ar'],
            'writesubtitles': True,
            'writeautomaticsub': True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ext = info.get('ext', 'mp4')
            return f"video.{ext}", info.get('title', 'video')
    except Exception as e:
        logger.error(f"❌ فشل في تنزيل الفيديو: {e}")
        raise e

def burn_subtitles(video_path, subtitle_path, output_path):
    """حرق الترجمة داخل الفيديو"""
    logger.info(f"🔥 جاري حرق الترجمة في الفيديو")
    try:
        # التحقق من وجود ملف الترجمة
        if not os.path.exists(subtitle_path):
            logger.warning(f"⚠️ ملف الترجمة غير موجود: {subtitle_path}")
            # البحث عن ملفات ترجمة أخرى
            subtitle_files = [f for f in os.listdir() if f.endswith('.srt') and 'video' in f]
            if subtitle_files:
                subtitle_path = subtitle_files[0]
                logger.info(f"🔍 تم العثور على ملف ترجمة بديل: {subtitle_path}")
            else:
                logger.error("❌ لم يتم العثور على أي ملفات ترجمة")
                return video_path  # إرجاع مسار الفيديو الأصلي بدون حرق الترجمة

        ffmpeg.input(video_path).output(output_path, vf=f"subtitles={subtitle_path}").run()
        logger.info("✅ تم حرق الترجمة بنجاح")
        return output_path
    except Exception as e:
        logger.error(f"❌ فشل في حرق الترجمة: {e}")
        return video_path  # إرجاع مسار الفيديو الأصلي في حالة الفشل

async def handle_format_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع اختيار المستخدم للجودة"""
    format_id = update.message.text.strip()
    chat_id = update.message.chat_id
    url = user_data.get(chat_id)

    logger.info(f"🎯 المستخدم {chat_id} اختار الجودة: {format_id}")

    if not url:
        await update.message.reply_text("❌ لم أتمكن من العثور على الرابط، أعد إرساله.")
        return

    status_message = await update.message.reply_text("⏳ جارِ تنزيل الفيديو...")
    
    try:
        video_path, video_title = download_video(url, format_id)
        
        await status_message.edit_text("🔥 جارِ حرق الترجمة داخل الفيديو...")
        
        # افتراض اسم ملف الترجمة
        subtitle_path = f"{os.path.splitext(video_path)[0]}.ar.srt"
        output_path = f"output_{chat_id}.mp4"
        
        final_video_path = burn_subtitles(video_path, subtitle_path, output_path)
        
        await status_message.edit_text("📤 جارِ إرسال الفيديو...")
        
        await send_video(final_video_path, chat_id, video_title)
        
        # تنظيف الملفات بعد الإرسال
        cleanup_files([video_path, subtitle_path, output_path])
        
    except Exception as e:
        logger.error(f"❌ حدث خطأ أثناء معالجة الفيديو: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الفيديو: {str(e)}")

async def send_video(video_path, chat_id, video_title="فيديو يوتيوب"):
    """إرسال الفيديو النهائي إلى تيليجرام"""
    logger.info(f"📤 جاري إرسال الفيديو إلى المستخدم {chat_id}")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        if not os.path.exists(video_path):
            logger.error(f"❌ ملف الفيديو غير موجود: {video_path}")
            await bot.send_message(chat_id=chat_id, text="❌ حدث خطأ: ملف الفيديو غير موجود")
            return

        file_size = os.path.getsize(video_path) / (1024 * 1024)  # حجم الملف بالميجابايت
        
        if file_size > 50:
            await bot.send_message(
                chat_id=chat_id, 
                text=f"⚠️ حجم الفيديو كبير جدًا ({file_size:.1f} ميجابايت). تيليجرام يسمح فقط بإرسال ملفات حتى 50 ميجابايت. يرجى اختيار جودة أقل."
            )
            return
            
        with open(video_path, 'rb') as video:
            await bot.send_video(
                chat_id=chat_id, 
                video=video, 
                caption=f"🎬 {video_title}",
                supports_streaming=True
            )
        logger.info("✅ تم إرسال الفيديو بنجاح")
    except Exception as e:
        logger.error(f"❌ فشل إرسال الفيديو: {e}")
        await bot.send_message(chat_id=chat_id, text=f"❌ فشل في إرسال الفيديو: {str(e)}")

def cleanup_files(file_paths):
    """تنظيف الملفات بعد الاستخدام"""
    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"🧹 تم حذف الملف: {file_path}")
        except Exception as e:
            logger.error(f"❌ فشل في حذف الملف {file_path}: {e}")

# ✅ إنشاء تطبيق Telegram
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# إضافة معالجات الأوامر والرسائل
telegram_app.add_handler(CommandHandler("start", start))

# تغيير نمط التعامل مع الرسائل النصية للتأكد من أنها تعمل بشكل صحيح
telegram_app.add_handler(MessageHandler(filters.COMMAND, lambda update, context: logger.info(f"تم استلام أمر: {update.message.text}")))
telegram_app.add_handler(MessageHandler(filters.Regex(r'^\d+$'), handle_format_selection))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ✅ إضافة نقطة نهاية للصحة للتحقق من أن التطبيق يعمل
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "message": "Bot is running"}), 200

# ✅ إعداد Webhook بشكل أكثر تفصيلًا
@app.route("/webhook", methods=["POST"])
def webhook():
    """استقبال تحديثات Telegram وإرسالها إلى البوت"""
    try:
        logger.info("📩 تم استلام طلب webhook")
        json_data = request.get_json()
        logger.debug(f"📦 بيانات الطلب: {json_data}")
        
        update = Update.de_json(json_data, telegram_app.bot)
        telegram_app.update_queue.put(update)
        
        return "✅ Webhook received!", 200
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة طلب webhook: {e}")
        return jsonify({"error": str(e)}), 500

def set_webhook():
    """تسجيل Webhook مع Telegram"""
    webhook_url = f"{RAILWAY_URL}/webhook"
    logger.info(f"🔗 محاولة تسجيل Webhook على: {webhook_url}")
    
    try:
        # إلغاء أي webhook سابق أولاً
        delete_response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook")
        logger.info(f"🗑️ حالة حذف Webhook السابق: {delete_response.status_code} - {delete_response.json()}")
        
        # تعيين webhook جديد
        response = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            params={"url": webhook_url, "drop_pending_updates": "true"}
        )
        response_json = response.json()

        if response.status_code == 200 and response_json.get("ok"):
            logger.info("✅ تم تسجيل الـ Webhook بنجاح!")
        else:
            logger.error(f"❌ فشل تسجيل Webhook: {response_json}")
            
        # التحقق من معلومات Webhook
        info_response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo")
        logger.info(f"ℹ️ معلومات Webhook: {info_response.json()}")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ خطأ في الاتصال عند تسجيل Webhook: {e}")

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=8080)
