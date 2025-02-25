import os
import logging
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from yt_dlp import YoutubeDL
import ffmpeg

# إعداد المتغيرات من GitHub Secrets
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# تفعيل سجل الأحداث
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# قائمة لتخزين روابط الفيديوهات للمستخدمين
user_data = {}

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("🔹 أرسل رابط فيديو من يوتيوب وسأقوم بتنزيله لك مع الترجمة العربية!")

def get_video_formats(url):
    """استرجاع قائمة الجودات والترميزات المتاحة للفيديو"""
    ydl_opts = {'listformats': True}
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = [
            f"{fmt['format_id']} - {fmt['ext']} - {fmt.get('format_note', 'Unknown')} ({fmt['fps']} FPS)"
            for fmt in info.get('formats', []) if fmt.get('ext') in ['mp4', 'mkv']
        ]
    return formats

async def handle_message(update: Update, context: CallbackContext):
    """التعامل مع رسالة المستخدم عند إرسال رابط يوتيوب"""
    url = update.message.text
    formats = get_video_formats(url)
    format_list = "\n".join(formats)

    await update.message.reply_text(f"🔽 اختر جودة الفيديو من القائمة التالية:\n{format_list}")

    # حفظ الرابط لاستخدامه لاحقًا عند اختيار الجودة
    user_data[update.message.chat_id] = url

def download_video(url, format_id):
    """تنزيل الفيديو مع الترجمة العربية"""
    ydl_opts = {
        'format': format_id,
        'outtmpl': 'video.%(ext)s',
        'subtitleslangs': ['ar'],
        'writesubtitles': True,
        'writeautomaticsub': True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def burn_subtitles(video_path, subtitle_path, output_path):
    """حرق الترجمة داخل الفيديو"""
    ffmpeg.input(video_path).output(output_path, vf=f"subtitles={subtitle_path}").run()

async def handle_format_selection(update: Update, context: CallbackContext):
    """التعامل مع اختيار المستخدم للجودة"""
    format_id = update.message.text
    chat_id = update.message.chat_id
    url = user_data.get(chat_id)

    if url:
        await update.message.reply_text("⏳ جارِ تنزيل الفيديو...")
        download_video(url, format_id)
        
        await update.message.reply_text("🔥 جارِ حرق الترجمة داخل الفيديو...")
        burn_subtitles("video.mp4", "video.ar.srt", "output.mp4")

        await update.message.reply_text("📤 جارِ إرسال الفيديو...")
        await send_video("output.mp4", chat_id)
    else:
        await update.message.reply_text("❌ لم أتمكن من العثور على الرابط، أعد إرساله.")

async def send_video(video_path, chat_id):
    """إرسال الفيديو النهائي إلى تيليجرام"""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await bot.send_video(chat_id=chat_id, video=open(video_path, 'rb'))

# تشغيل البوت باستخدام النظام الجديد
app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(MessageHandler(filters.Regex(r'^\d+$'), handle_format_selection))

app.run_polling()
