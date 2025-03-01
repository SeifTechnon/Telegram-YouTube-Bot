import os
import logging
import requests  # <-- تمت إضافة المكتبة هنا
from quart import Quart, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# إعداد السجل (Logging)
logging.basicConfig(
    filename="logs.txt",
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

        await update.message.reply_text(welcome_message, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"❌ خطأ في معالجة أمر /start: {e}")
        await update.message.reply_text("❌ حدث خطأ في بدء البوت. يرجى المحاولة مرة أخرى.")

telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

telegram_app.add_handler(CommandHandler("start", start))

@app.route("/", methods=["GET"])
async def health_check():
    """نقطة نهاية للتحقق من صحة البوت"""
    return jsonify({
        "status": "ok",
        "message": "Bot is running",
        "version": "1.0.0",
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

        # تحويل البيانات إلى كائن Update
        update = Update.de_json(json_data, telegram_app.bot)
        await telegram_app.update_queue.put(update)

        return "✅ Webhook received!", 200
    except Exception as e:
        logger.error(f"❌ خطأ في معالجة طلب webhook: {e}")
        return jsonify({"error": str(e)}), 500

def set_webhook(max_retries=3):
    """تسجيل Webhook مع Telegram مع محاولات متكررة"""
    webhook_url = f"{os.getenv('RAILWAY_URL', '').strip()}/webhook"
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

if __name__ == "__main__":
    webhook_registered = set_webhook(max_retries=3)

    if webhook_registered:
        logger.info("🚀 تم تسجيل Webhook بنجاح وجاري بدء تشغيل الخادم...")
    else:
        logger.warning("⚠️ بدء تشغيل الخادم مع فشل تسجيل Webhook!")

    PORT = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=PORT)