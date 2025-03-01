import os
import logging
import asyncio
import requests
from quart import Quart, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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

# تسجيل Webhook مع Telegram
def set_webhook(max_retries=3):
    """تسجيل Webhook مع Telegram مع محاولات متكررة"""
    # تحسين: استخدام المتغير البيئي بشكل صحيح، وإضافة السلاش في نهاية URL إذا لم يكن موجودًا
    base_url = os.getenv('RAILWAY_STATIC_URL', os.getenv('RAILWAY_PUBLIC_DOMAIN', ''))
    
    # إذا كانت هناك قيمة للـ RAILWAY_PUBLIC_DOMAIN، أضف البروتوكول
    if base_url and not base_url.startswith(('http://', 'https://')):
        base_url = f"https://{base_url}"
    
    # تأكد من انتهاء العنوان بـ /
    if base_url and not base_url.endswith('/'):
        base_url += '/'
    
    webhook_url = f"{base_url}webhook"
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
                logger.info(f"✅ تم تسجيل الـ Webhook بنجاح على {webhook_url}!")
                return True
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

# معالج أمر start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال أوامر بدء البوت"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        logger.info(f"🟢 تم استلام أمر /start من المستخدم {user_id} (@{username})")

        welcome_message = (
            f"👋 مرحباً بك {username} في البوت الخاص بنا!\n\n"
            "هذا البوت يرسل رسالة ترحيبية فقط عند إرسال الأمر /start."
        )

        await update.message.reply_text(welcome_message)
        logger.info(f"✅ تم إرسال رسالة الترحيب إلى المستخدم {user_id}")

    except Exception as e:
        logger.error(f"❌ خطأ في معالجة أمر /start: {e}")
        try:
            await update.message.reply_text("❌ حدث خطأ في بدء البوت. يرجى المحاولة مرة أخرى.")
        except Exception as reply_error:
            logger.error(f"❌ خطأ في إرسال رسالة الخطأ: {reply_error}")

# معالج الرسائل النصية
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال الرسائل النصية"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username or "مستخدم"
        text = update.message.text
        logger.info(f"📩 تم استلام رسالة من المستخدم {user_id} (@{username}): {text[:20]}...")

        await update.message.reply_text(f"استلمت رسالتك: {text}")

    except Exception as e:
        logger.error(f"❌ خطأ في معالجة الرسالة: {e}")
        try:
            await update.message.reply_text("❌ حدث خطأ في معالجة الرسالة. يرجى المحاولة مرة أخرى.")
        except Exception as reply_error:
            logger.error(f"❌ خطأ في إرسال رسالة الخطأ: {reply_error}")

# إنشاء تطبيق Telegram
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# إضافة معالجات الأوامر والرسائل
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# نقطة نهاية للتحقق من صحة البوت
@app.route("/", methods=["GET"])
async def root():
    return jsonify({
        "status": "ok",
        "message": "Bot is running",
        "version": "1.0.0",
    }), 200

# نقطة نهاية للتحقق من صحة التطبيق
@app.route("/health", methods=["GET"])
async def health_check():
    return jsonify({"status": "ok", "message": "Bot is healthy"}), 200

# نقطة نهاية لاستقبال تحديثات Webhook
@app.route("/webhook", methods=["POST"])
async def webhook():
    """استقبال تحديثات Telegram وإرسالها إلى البوت"""
    try:
        logger.info("📩 تم استلام طلب webhook")
        json_data = await request.get_json()

        # سجل البيانات الواردة للتشخيص
        logger.info(f"📦 بيانات Webhook: {json_data}")

        if json_data and 'update_id' in json_data:
            update_id = json_data.get('update_id')
            message = json_data.get('message', {})
            user = message.get('from', {})
            user_id = user.get('id')
            username = user.get('username', 'غير متوفر')
            text = message.get('text', '')

            logger.info(f"📦 تحديث جديد: ID={update_id}, من: {user_id} (@{username}), النص: {text[:20]}...")

            # تحويل البيانات إلى كائن Update
            update = Update.de_json(json_data, telegram_app.bot)
            
            # معالجة التحديث مباشرة
            await telegram_app.process_update(update)
            
            return "✅ Webhook processed!", 200
        else:
            logger.warning("⚠️ بيانات webhook غير صالحة أو مفقودة")
            return "⚠️ Invalid webhook data", 400
            
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة طلب webhook: {e}")
        return jsonify({"error": str(e)}), 500

async def start_bot():
    """بدء تشغيل البوت"""
    try:
        # بدء تشغيل تطبيق Telegram
        await telegram_app.initialize()
        logger.info("✅ تم تهيئة تطبيق Telegram بنجاح")
        
        # تسجيل Webhook
        webhook_registered = set_webhook(max_retries=3)
        
        if webhook_registered:
            logger.info("🚀 تم تسجيل Webhook بنجاح وجاري بدء تشغيل الخادم...")
        else:
            logger.warning("⚠️ بدء تشغيل الخادم مع فشل تسجيل Webhook!")
            
        # معلومات تشخيصية حول البوت
        bot_info = await telegram_app.bot.get_me()
        logger.info(f"🤖 معلومات البوت: {bot_info.to_dict()}")
        
        # تشغيل الخادم
        PORT = int(os.environ.get("PORT", 8080))
        return PORT
        
    except Exception as e:
        logger.error(f"❌ خطأ في بدء تشغيل البوت: {e}")
        raise

@app.before_serving
async def before_serving():
    """تنفيذ قبل بدء خدمة الخادم"""
    try:
        port = await start_bot()
        logger.info(f"🌐 جاري تشغيل الخادم على المنفذ {port}...")
    except Exception as e:
        logger.error(f"❌ خطأ في تهيئة البوت: {e}")

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=PORT)