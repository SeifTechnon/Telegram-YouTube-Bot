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
if TELEGRAM_BOT_TOKEN:
    logger.info(f"🔹 TELEGRAM_BOT_TOKEN = {TELEGRAM_BOT_TOKEN[:5]}... (تم إخفاء باقي التوكن لأمان أكثر)")
else:
    logger.error("❌ TELEGRAM_BOT_TOKEN غير محدد!")

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
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        logger.info(f"🟢 تم استلام أمر /start من المستخدم {user_id} (@{username})")
        
        # رسالة ترحيبية أكثر تفصيلاً
        welcome_message = (
            f"👋 مرحباً بك {username} في بوت تنزيل فيديوهات يوتيوب مع الترجمة!\n\n"
            "🎬 *كيفية الاستخدام:*\n"
            "1️⃣ أرسل رابط فيديو يوتيوب\n"
            "2️⃣ اختر جودة التنزيل من القائمة\n"
            "3️⃣ انتظر حتى يتم تنزيل الفيديو ومعالجته\n\n"
            "🔍 جاهز لبدء تنزيل أول فيديو؟ أرسل الرابط الآن!"
        )
        
        await update.message.reply_text(welcome_message, parse_mode="Markdown")
        
        # تنظيف أي بيانات سابقة للمستخدم
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
            "• لتنزيل فيديو: أرسل رابط يوتيوب مباشرة\n"
            "• للمساعدة: أرسل /help\n\n"
            "ℹ️ لتنزيل فيديو مع الترجمة العربية، ما عليك سوى إرسال رابط يوتيوب واتباع التعليمات."
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة أمر /help: {e}")
        await update.message.reply_text("❌ حدث خطأ في عرض المساعدة. يرجى المحاولة مرة أخرى.")

def get_video_formats(url):
    """استرجاع قائمة الجودات والترميزات المتاحة للفيديو"""
    logger.info(f"🔍 جاري استرجاع قائمة الجودات لـ: {url}")
    try:
        ydl_opts = {'listformats': True}
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # استخراج معلومات الفيديو الأساسية
            title = info.get('title', 'فيديو بدون عنوان')
            duration = info.get('duration')
            duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "غير معروف"
            
            # تصفية القائمة للتركيز على الجودات المفيدة للمستخدم
            formats = [
                f"{fmt['format_id']} - {fmt['ext']} - {fmt.get('format_note', 'Unknown')} ({fmt.get('fps', 'N/A')} FPS)"
                for fmt in info.get('formats', []) 
                if fmt.get('ext') in ['mp4', 'mkv'] and fmt.get('vcodec', 'none') != 'none'
            ]
            
            # ترتيب القائمة حسب معرف التنسيق للسهولة
            formats.sort(key=lambda x: x.split(' - ')[0])
            
            logger.info(f"✅ تم استرجاع {len(formats)} جودة متاحة لفيديو: {title}")
            return formats, title, duration_str
    except Exception as e:
        logger.error(f"❌ خطأ عند استرجاع قائمة الجودات: {e}")
        return ["❌ حدث خطأ في معالجة الرابط. تأكد من أنه رابط يوتيوب صالح."], "خطأ", "غير معروف"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع رسالة المستخدم عند إرسال رابط يوتيوب"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        url = update.message.text.strip()
        
        logger.info(f"📩 تم استلام رسالة من المستخدم {user_id} (@{username}): {url}")
        
        # التحقق من صحة الرابط (تحقق أكثر شمولية)
        valid_domains = ['youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com']
        if not any(domain in url for domain in valid_domains):
            await update.message.reply_text("❌ الرابط غير صالح. يرجى إرسال رابط يوتيوب صحيح.")
            return
            
        status_message = await update.message.reply_text("⏳ جاري تحليل الرابط... قد يستغرق ذلك بضع ثوانٍ.")
        
        formats, video_title, duration = get_video_formats(url)
        
        if not formats or (isinstance(formats, list) and len(formats) == 0):
            await status_message.edit_text("❌ لم يتم العثور على جودات متاحة للتنزيل.")
            return
            
        if isinstance(formats, list) and formats[0].startswith("❌"):
            await status_message.edit_text(formats[0])
            return
        
        # إنشاء قائمة منسقة تحتوي على الجودات المتاحة
        format_info = (
            f"🎬 *{video_title}*\n"
            f"⏱️ المدة: {duration}\n\n"
            "🔽 *اختر جودة الفيديو بإرسال الرقم المناسب:*\n"
        )
        
        # تحديد عدد الجودات المعروضة لتجنب رسائل طويلة جداً
        max_formats = 10
        format_list = "\n".join([f"{i+1}. {fmt}" for i, fmt in enumerate(formats[:max_formats])])
        
        if len(formats) > max_formats:
            format_list += f"\n...وأكثر من ذلك ({len(formats) - max_formats} جودات إضافية)"
        
        await status_message.edit_text(f"{format_info}{format_list}", parse_mode="Markdown")

        # حفظ الرابط ومعلومات الجودات لاستخدامها لاحقًا عند اختيار الجودة
        user_data[update.message.chat_id] = {
            'url': url,
            'formats': formats,
            'title': video_title
        }
        
    except Exception as e:
        logger.error(f"❌ خطأ عند معالجة الرابط: {e}")
        await update.message.reply_text(f"❌ حدث خطأ عند معالجة الرابط: {str(e)}\nيرجى المحاولة مرة أخرى لاحقًا.")

def download_video(url, format_id, chat_id):
    """تنزيل الفيديو مع الترجمة العربية"""
    logger.info(f"⬇️ جاري تنزيل الفيديو بجودة {format_id}")
    try:
        # استخدام معرف المحادثة في اسم الملف لمنع التداخل بين المستخدمين
        output_filename = f"video_{chat_id}"
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': f'{output_filename}.%(ext)s',
            'subtitleslangs': ['ar'],
            'writesubtitles': True,
            'writeautomaticsub': True,
            # إضافة خيارات لمحاولة الحصول على الترجمة التلقائية إذا لم تكن متوفرة
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
            
            # البحث عن ملفات الترجمة المتاحة
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
        # التحقق من وجود ملف الترجمة
        if not subtitle_path or not os.path.exists(subtitle_path):
            logger.warning(f"⚠️ ملف الترجمة غير موجود: {subtitle_path}")
            return video_path  # إرجاع مسار الفيديو الأصلي بدون حرق الترجمة

        # تكوين خيارات أفضل لحرق الترجمة
        ffmpeg_options = {
            'vf': f"subtitles='{subtitle_path}':force_style='FontSize=18,Alignment=2,BorderStyle=3,Outline=2,Shadow=1,MarginV=25'"
        }
        
        # تنفيذ عملية حرق الترجمة
        ffmpeg.input(video_path).output(output_path, **ffmpeg_options).run()
        
        logger.info("✅ تم حرق الترجمة بنجاح")
        return output_path
    except Exception as e:
        logger.error(f"❌ فشل في حرق الترجمة: {e}")
        return video_path  # إرجاع مسار الفيديو الأصلي في حالة الفشل

async def handle_format_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع اختيار المستخدم للجودة"""
    try:
        # تحقق مما إذا كان الإدخال رقمًا
        user_input = update.message.text.strip()
        if not user_input.isdigit():
            # تحقق مما إذا كان المستخدم أرسل معرف تنسيق مباشرة (مثل "22")
            if not any(user_input == fmt.split(' - ')[0] for fmt in user_data.get(update.message.chat_id, {}).get('formats', [])):
                return  # ليس اختيارًا للجودة، ربما رسالة نصية عادية
        
        chat_id = update.message.chat_id
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        
        # الحصول على بيانات المستخدم المخزنة
        user_info = user_data.get(chat_id)
        if not user_info:
            await update.message.reply_text("❌ لم أتمكن من العثور على معلومات الفيديو. يرجى إرسال الرابط مرة أخرى.")
            return

        url = user_info.get('url')
        video_title = user_info.get('title', 'فيديو يوتيوب')
        formats = user_info.get('formats', [])
        
        # تحديد معرف التنسيق المطلوب
        format_index = int(user_input) - 1
        if 0 <= format_index < len(formats):
            # إذا أرسل المستخدم رقم الخيار (1, 2, 3, ...)
            format_id = formats[format_index].split(' - ')[0]
        else:
            # إذا أرسل المستخدم معرف التنسيق مباشرة
            format_id = user_input

        logger.info(f"🎯 المستخدم {user_id} (@{username}) اختار الجودة: {format_id} للفيديو: {video_title}")

        # إرسال رسالة حالة وتحديثها أثناء التقدم
        status_message = await update.message.reply_text(
            f"⏳ جارِ تنزيل الفيديو بجودة {format_id}...\n"
            "سيستغرق ذلك بعض الوقت حسب حجم الفيديو."
        )
        
        # تنزيل الفيديو وإعداده
        video_path, video_title, subtitle_path = download_video(url, format_id, chat_id)
        
        await status_message.edit_text(
            f"⏳ تم تنزيل الفيديو بنجاح: {video_title}\n"
            f"🔤 ترجمة: {'✅ متوفرة' if subtitle_path else '❌ غير متوفرة'}\n"
            "🔥 جارِ معالجة الفيديو..."
        )
        
        # إعداد مسارات الملفات
        output_path = f"output_{chat_id}.mp4"
        
        # محاولة حرق الترجمة إذا كانت متوفرة
        if subtitle_path:
            final_video_path = burn_subtitles(video_path, subtitle_path, output_path)
        else:
            final_video_path = video_path
        
        await status_message.edit_text("📤 جارِ إرسال الفيديو... يرجى الانتظار.")
        
        # إرسال الفيديو للمستخدم
        result = await send_video(final_video_path, chat_id, video_title)
        
        if result:
            await status_message.edit_text("✅ تم إرسال الفيديو بنجاح!")
        
        # تنظيف الملفات بعد الإرسال
        cleanup_files([video_path, subtitle_path, output_path, final_video_path])
        
        # تنظيف بيانات المستخدم
        if chat_id in user_data:
            del user_data[chat_id]
            
    except Exception as e:
        logger.error(f"❌ حدث خطأ أثناء معالجة الفيديو: {e}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الفيديو: {str(e)}\nيرجى المحاولة مرة أخرى.")

async def send_video(video_path, chat_id, video_title="فيديو يوتيوب"):
    """إرسال الفيديو النهائي إلى تيليجرام"""
    logger.info(f"📤 جاري إرسال الفيديو إلى المستخدم {chat_id}")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        if not os.path.exists(video_path):
            logger.error(f"❌ ملف الفيديو غير موجود: {video_path}")
            await bot.send_message(chat_id=chat_id, text="❌ حدث خطأ: ملف الفيديو غير موجود")
            return False

        file_size = os.path.getsize(video_path) / (1024 * 1024)  # حجم الملف بالميجابايت
        
        if file_size > 50:
            await bot.send_message(
                chat_id=chat_id, 
                text=f"⚠️ حجم الفيديو كبير جدًا ({file_size:.1f} ميجابايت). تيليجرام يسمح فقط بإرسال ملفات حتى 50 ميجابايت. يرجى اختيار جودة أقل."
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

# إضافة معالج للأخطاء غير المعالجة
async def error_handler(update, context):
    """معالجة الأخطاء غير المتوقعة"""
    logger.error(f"🚨 خطأ غير معالج: {context.error}")
    
    if update and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ حدث خطأ غير متوقع أثناء معالجة طلبك. يرجى المحاولة مرة أخرى لاحقًا."
        )

# ✅ إنشاء تطبيق Telegram
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# إضافة معالجات الأوامر والرسائل (بترتيب صحيح)
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(MessageHandler(filters.Regex(r'^(\d+)$'), handle_format_selection))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# إضافة معالج للأخطاء
telegram_app.add_error_handler(error_handler)

# ✅ إضافة نقطة نهاية للصحة للتحقق من أن التطبيق يعمل
@app.route("/", methods=["GET"])
def health_check():
    """نقطة نهاية للتحقق من صحة البوت"""
    return jsonify({
        "status": "ok", 
        "message": "Bot is running",
        "version": "1.1.0",
        "webhook_url": f"{RAILWAY_URL}/webhook"
    }), 200

# ✅ إعداد Webhook بشكل أكثر تفصيلًا
@app.route("/webhook", methods=["POST"])
def webhook():
    """استقبال تحديثات Telegram وإرسالها إلى البوت"""
    try:
        logger.info("📩 تم استلام طلب webhook")
        json_data = request.get_json()
        
        # تسجيل بعض المعلومات المهمة فقط من الطلب للتصحيح
        if json_data and 'update_id' in json_data:
            update_id = json_data.get('update_id')
            message = json_data.get('message', {})
            user = message.get('from', {})
            user_id = user.get('id')
            username = user.get('username', 'غير متوفر')
            text = message.get('text', '')
            
            logger.info(f"📦 تحديث جديد: ID={update_id}, من: {user_id} (@{username}), النص: {text[:20]}...")
        
        update = Update.de_json(json_data, telegram_app.bot)
        telegram_app.update_queue.put(update)
        
        return "✅ Webhook received!", 200
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة طلب webhook: {e}")
        return jsonify({"error": str(e)}), 500

# ✅ تسجيل Webhook مع تكرار المحاولات
def set_webhook(max_retries=3):
    """تسجيل Webhook مع Telegram مع محاولات متكررة"""
    webhook_url = f"{RAILWAY_URL}/webhook"
    logger.info(f"🔗 محاولة تسجيل Webhook على: {webhook_url}")
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"🔄 محاولة {attempt}/{max_retries} لتسجيل Webhook")
            
            # إلغاء أي webhook سابق أولاً
            delete_response = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook",
                timeout=10
            )
            logger.info(f"🗑️ حالة حذف Webhook السابق: {delete_response.status_code} - {delete_response.json()}")
            
            # تعيين webhook جديد
            response = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
                params={"url": webhook_url, "drop_pending_updates": "true", "max_connections": 100},
                timeout=10
            )
            response_json = response.json()

            if response.status_code == 200 and response_json.get("ok"):
                logger.info("✅ تم تسجيل الـ Webhook بنجاح!")
                
                # التحقق من معلومات Webhook بعد التسجيل
                info_response = requests.get(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo",
                    timeout=10
                )
                webhook_info = info_response.json()
                logger.info(f"ℹ️ معلومات Webhook: {webhook_info}")
                
                # تأكد من أن عنوان URL المسجل هو الصحيح
                if webhook_info.get("result", {}).get("url") == webhook_url:
                    return True
                else:
                    logger.warning("⚠️ عنوان URL المسجل لا يتطابق مع العنوان المطلوب!")
            else:
                logger.error(f"❌ فشل تسجيل Webhook (محاولة {attempt}/{max_retries}): {response_json}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ خطأ في الاتصال عند تسجيل Webhook (محاولة {attempt}/{max_retries}): {e}")
        
        # انتظار قبل إعادة المحاولة
        if attempt < max_retries:
            logger.info(f"⏳ الانتظار قبل إعادة محاولة تسجيل Webhook...")
            import time
            time.sleep(5)
    
    logger.error("❌ فشلت جميع محاولات تسجيل Webhook!")
    return False

if __name__ == "__main__":
    # محاولة تسجيل Webhook قبل بدء تشغيل خادم Flask
    webhook_registered = set_webhook(max_retries=3)
    
    if webhook_registered:
        logger.info("🚀 تم تسجيل Webhook بنجاح وجاري بدء تشغيل الخادم...")
    else:
        logger.warning("⚠️ بدء تشغيل الخادم مع فشل تسجيل Webhook!")
    
    # بدء تشغيل خادم Flask
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
