import os
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from yt_dlp import YoutubeDL
import ffmpeg

# إعداد المتغيرات من GitHub Secrets
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# تفعيل سجل الأحداث
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# قائمة لتخزين روابط الفيديوهات للمستخدمين
user_data = {}

def start(update: Update, context: CallbackContext):
    update.message.reply_text("🔹 أرسل رابط فيديو من يوتيوب وسأقوم بتنزيله لك مع الترجمة العربية!")

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

def handle_message(update: Update, context: CallbackContext):
    """التعامل مع رسالة المستخدم عند إرسال رابط يوتيوب"""
    url = update.message.text
    formats = get_video_formats(url)
    format_list = "\n".join(formats)

    update.message.reply_text(f"🔽 اختر جودة الفيديو من القائمة التالية:\n{format_list}")

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

def handle_format_selection(update: Update, context: CallbackContext):
    """التعامل مع اختيار المستخدم للجودة"""
    format_id = update.message.text
    chat_id = update.message.chat_id
    url = user_data.get(chat_id)

    if url:
        update.message.reply_text("⏳ جارِ تنزيل الفيديو...")
        download_video(url, format_id)
        
        update.message.reply_text("🔥 جارِ حرق الترجمة داخل الفيديو...")
        burn_subtitles("video.mp4", "video.ar.srt", "output.mp4")

        update.message.reply_text("📤 جارِ إرسال الفيديو...")
        send_video("output.mp4", chat_id)
    else:
        update.message.reply_text("❌ لم أتمكن من العثور على الرابط، أعد إرساله.")

def send_video(video_path, chat_id):
    """إرسال الفيديو النهائي إلى تيليجرام"""
    from telegram import Bot
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    bot.send_video(chat_id=chat_id, video=open(video_path, 'rb'))

# تشغيل البوت
updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
dp = updater.dispatcher

dp.add_handler(CommandHandler("start", start))
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
dp.add_handler(MessageHandler(Filters.regex(r'^\d+$'), handle_format_selection))

updater.start_polling()
updater.idle()
