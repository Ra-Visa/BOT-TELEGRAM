import subprocess
import os
import logging
import threading
import time
import requests
import shutil
from pathlib import Path
from flask import Flask
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, filters, CallbackContext
from yt_dlp import YoutubeDL
import schedule

# ធ្វើបច្ចុប្បន្នភាព yt-dlp ជានិច្ច
subprocess.run(["pip", "install", "--upgrade", "yt-dlp"], check=True)

# ផ្ទុក environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# ប្រើ /tmp សម្រាប់ Render.com
DOWNLOAD_FOLDER = '/tmp/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

# ============ ប្រព័ន្ធគ្រប់គ្រងទំហំផ្ទុក ============
# អថេរសម្រាប់រាប់ពេលវេលា
last_full_cleanup = time.time()
CLEANUP_INTERVAL = 6 * 60 * 60  # 6 ម៉ោង (គិតជាវិនាទី)

def check_disk_space():
    """ពិនិត្យទំហំផ្ទុកដែលនៅសល់"""
    try:
        stat = shutil.disk_usage('/tmp')
        free_mb = stat.free / (1024 * 1024)
        total_mb = stat.total / (1024 * 1024)
        used_mb = stat.used / (1024 * 1024)
        
        logging.info(f"💾 Disk space - Total: {total_mb:.0f}MB, Used: {used_mb:.0f}MB, Free: {free_mb:.0f}MB")
        
        return free_mb
    except Exception as e:
        logging.error(f"Error checking disk space: {e}")
        return 0

def force_clean_mp3_files():
    """លុបឯកសារ MP3 ទាំងអស់ក្នុង folder (មិនលុបឯកសារផ្សេង)"""
    global last_full_cleanup
    try:
        if not os.path.exists(DOWNLOAD_FOLDER):
            os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
            return
        
        files_deleted = 0
        space_freed = 0
        
        # លុបតែឯកសារ .mp3 ប៉ុណ្ណោះ
        for file_path in Path(DOWNLOAD_FOLDER).glob('*.mp3'):
            if file_path.is_file():
                file_size = os.path.getsize(file_path)
                os.remove(file_path)
                files_deleted += 1
                space_freed += file_size
                logging.info(f"🧹 Deleted MP3: {file_path.name} ({file_size/1024/1024:.1f}MB)")
        
        # កត់ត្រាចំនួនឯកសារផ្សេងទៀត (មិនលុប)
        other_files = list(Path(DOWNLOAD_FOLDER).glob('*'))
        other_files = [f for f in other_files if f.is_file() and not f.name.endswith('.mp3')]
        if other_files:
            logging.info(f"📁 Keeping {len(other_files)} non-MP3 files (not deleted)")
        
        if files_deleted > 0:
            logging.info(f"✅ SCHEDULED CLEANUP: Deleted {files_deleted} MP3 files, freed {space_freed/1024/1024:.1f}MB")
        else:
            logging.info("✅ SCHEDULED CLEANUP: No MP3 files to delete")
        
        # កត់ត្រាពេលវេលាលុបចុងក្រោយ
        last_full_cleanup = time.time()
        
    except Exception as e:
        logging.error(f"Error in force clean: {e}")

def clean_old_mp3_files():
    """លុបតែឯកសារ MP3 ចាស់ៗ (លើសពី 30 នាទី)"""
    global last_full_cleanup
    
    try:
        # ពិនិត្យមើលថាតើដល់ពេលត្រូវលុបទាំងអស់ឬនៅ
        current_time = time.time()
        time_since_last_cleanup = current_time - last_full_cleanup
        
        # បើដល់ 6 ម៉ោងហើយ លុប MP3 ទាំងអស់
        if time_since_last_cleanup >= CLEANUP_INTERVAL:
            logging.info(f"⏰ {time_since_last_cleanup/3600:.1f} hours since last cleanup. Running scheduled MP3 cleanup...")
            force_clean_mp3_files()
            return
        
        # បើមិនទាន់ដល់ពេលទេ លុបតែ MP3 ចាស់ៗ (លើសពី 30 នាទី)
        if not os.path.exists(DOWNLOAD_FOLDER):
            return
        
        current_time = time.time()
        files_deleted = 0
        space_freed = 0
        
        # លុបតែឯកសារ .mp3 ដែលចាស់ជាង 30 នាទី
        for file_path in Path(DOWNLOAD_FOLDER).glob('*.mp3'):
            if file_path.is_file():
                file_age = current_time - os.path.getmtime(file_path)
                file_size = os.path.getsize(file_path)
                
                # លុបតែ MP3 ដែលចាស់ជាង 30 នាទី
                if file_age > 30 * 60:  # 30 នាទី
                    os.remove(file_path)
                    files_deleted += 1
                    space_freed += file_size
                    logging.info(f"🧹 Deleted old MP3: {file_path.name} ({file_size/1024/1024:.1f}MB)")
        
        if files_deleted > 0:
            logging.info(f"✅ Cleaned {files_deleted} old MP3 files, freed {space_freed/1024/1024:.1f}MB")
            
    except Exception as e:
        logging.error(f"Error cleaning MP3 files: {e}")

def schedule_cleanup():
    """កំណត់ពេលវេលាលុប MP3 ដោយស្វ័យប្រវត្តិ"""
    # លុប MP3 ទាំងអស់រៀងរាល់ 6 ម៉ោងម្តង
    schedule.every(6).hours.do(force_clean_mp3_files)
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # ពិនិត្យរៀងរាល់ 1 នាទី

# ចាប់ផ្តើមការកំណត់ពេលវេលាក្នុង thread ដាច់ដោយឡែក
cleanup_thread = threading.Thread(target=schedule_cleanup)
cleanup_thread.daemon = True
cleanup_thread.start()

# លុប MP3 ទាំងអស់ម្តងពេលចាប់ផ្តើមកម្មវិធី
force_clean_mp3_files()
# ============================================

# ============ KEEP ALIVE ============
app = Flask(__name__)

@app.route('/')
def home():
    free_mb = check_disk_space()
    return f"🤖 Telegram Bot is running! Free space: {free_mb:.0f}MB"

@app.route('/ping')
def ping():
    return "pong"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

def self_ping():
    time.sleep(60)
    while True:
        try:
            # សម្អាត MP3 ចាស់ៗ និងពិនិត្យពេលវេលា
            clean_old_mp3_files()
            check_disk_space()
            
            # ប្រើ Render URL
            render_url = os.environ.get('RENDER_URL', 'http://localhost:8080')
            requests.get(f"{render_url}/ping", timeout=10)
            logging.info("✅ Self-ping successful")
        except Exception as e:
            logging.error(f"❌ Self-ping failed: {e}")
        time.sleep(300)  # 5 នាទី

def keep_alive():
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    ping_thread = threading.Thread(target=self_ping)
    ping_thread.daemon = True
    ping_thread.start()
    
    logging.info("🟢 Keep-alive system started")
# ==========================================

# ============ មុខងារទាញយក ============
def download_audio_with_retry(url, max_retries=3):
    """ទាញយកជាមួយការសាកល្បងច្រើនដង"""
    for attempt in range(max_retries):
        try:
            # សម្អាត MP3 ចាស់ៗមុនពេលទាញយក
            clean_old_mp3_files()
            
            # ពិនិត្យទំហំផ្ទុក
            free_mb = check_disk_space()
            if free_mb < 50:  # បើនៅតិចជាង 50MB
                logging.warning(f"⚠️ Low disk space: {free_mb:.0f}MB. Running force cleanup...")
                force_clean_mp3_files()
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',  # 128kbps ដើម្បីសន្សំទំហំ
                }],
                'noplaylist': True,
                'quiet': True,
            }

            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                audio_file = ydl.prepare_filename(info_dict)
                mp3_file_path = audio_file.rsplit('.', 1)[0] + '.mp3'
                
                file_size = os.path.getsize(mp3_file_path) / (1024 * 1024)
                logging.info(f"✅ Downloaded: {file_size:.1f}MB - {info_dict.get('title', 'Unknown')}")
                
                return info_dict, mp3_file_path
                
        except Exception as e:
            logging.error(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            else:
                raise e
# ==========================================

# ============ Telegram Handlers ============
def start(update: Update, context: CallbackContext) -> None:
    """Handler for /start command"""
    welcome_message = """
<b>𝗞𝗜𝗥𝗔𝗞 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗 𝗠𝗣𝟯 - 𝗕𝗢𝗧</b>

សួស្តី! ជម្រាបសួរមកកាន់ KIRAK Download MP3 Bot

📥 <b>របៀបប្រើប្រាស់:</b>
គ្រាន់តែផ្ញើតំណ YouTube មកខ្ញុំ

🌐 <b>គាំទ្រ:</b> YouTube, YouTube Shorts, YouTube Music
🎧 <b>គុណភាព:</b> MP3 128kbps (ដើម្បីសន្សំទំហំ)

📞 <b>សម្រាប់ជំនួយ:</b> @kirak_itadori
"""
    
    photo_url = "https://i.ibb.co/dJ6c0ctk/IMG-20260130-081334-718.jpg"
    
    try:
        context.bot.send_photo(
            chat_id=update.message.chat_id,
            photo=photo_url,
            caption=welcome_message,
            parse_mode='HTML'
        )
        logging.info(f"✅ Welcome sent to user {update.message.chat_id}")
    except Exception as e:
        logging.error(f"Photo error: {str(e)[:100]}")
        update.message.reply_text(welcome_message, parse_mode='HTML')

def download_audio(update: Update, context: CallbackContext) -> None:
    """Handler for YouTube links"""
    if update.message.text and update.message.text.startswith('/'):
        return
    
    chat_id = update.message.chat_id
    user_message = update.message.text.strip() if update.message.text else ""

    if user_message and ('youtube.com' in user_message or 'youtu.be' in user_message):
        try:
            update.message.reply_text("📥 កំពុងទាញយក... សូមរង់ចាំសិន!")
            
            # ទាញយក MP3
            info_dict, mp3_file_path = download_audio_with_retry(user_message)
            
            update.message.reply_text("✅ ទាញយករួច! កំពុងផ្ញើ MP3...")
            
            # ផ្ញើឲ្យអ្នកប្រើ
            with open(mp3_file_path, 'rb') as audio:
                context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    title=info_dict.get('title', 'Audio')[:64],
                    performer=info_dict.get('uploader', 'Unknown')[:64],
                    duration=info_dict.get('duration', 0)
                )
            
            # លុប MP3 ចេញពី server ភ្លាមៗ
            if os.path.exists(mp3_file_path):
                os.remove(mp3_file_path)
                logging.info(f"🗑️ Deleted MP3 after sending: {os.path.basename(mp3_file_path)}")

        except Exception as e:
            logging.error(f"Download error: {str(e)}")
            update.message.reply_text(
                "❌ មានកំហុស! សូមព្យាយាមម្តងទៀត\n\n"
                "សូមប្រាកដថា:\n"
                "• តំណ YouTube ត្រឹមត្រូវ\n"
                "• វីដេអូអាចចូលមើលបាន"
            )

    elif user_message:
        update.message.reply_text(
            "⚠️ សូមផ្ញើតំណ YouTube\n\n"
            "ឧទាហរណ៍:\n"
            "• https://youtu.be/xxxx\n"
            "• https://youtube.com/watch?v=xxxx"
        )
# ==========================================

def main() -> None:
    if not TOKEN:
        logging.error("❌ ERROR: សូមបន្ថែម TELEGRAM_BOT_TOKEN ក្នុងឯកសារ .env")
        return
    
    logging.info(f"🚀 Starting Telegram bot with token: {TOKEN[:10]}...")
    
    # ពិនិត្យទំហំផ្ទុកពេលចាប់ផ្ដើម
    logging.info("🚀 Starting bot...")
    check_disk_space()
    force_clean_mp3_files()
    
    # ចាប់ផ្តើម keep-alive system
    keep_alive()
    
    # ចាប់ផ្តើម Telegram bot ជាមួយ Updater (កំណែ 20.x)
    updater = Updater(token=TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # បន្ថែម handlers (កែ Filters ជា filters)
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_audio))
    
    # ចាប់ផ្តើម bot
    logging.info("🤖 Bot is now running and waiting for messages...")
    updater.start_polling()
    
    # រង់ចាំឲ្យ bot ដំណើរការ
    updater.idle()

if __name__ == '__main__':
    main()
