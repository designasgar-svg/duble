import asyncio
import os
import sys
import signal
import time
import traceback
import threading
import webbrowser
import subprocess
import json
import tempfile

# ۱. رفع خطای sys.argv در Termux قبل از import کردن webview
if not sys.argv or sys.argv[0] is None:
    sys.argv = [""]

try:
    import webview
    HAS_WEBVIEW = True
except Exception:
    HAS_WEBVIEW = False

import edge_tts
from flask import Flask, render_template, request, send_from_directory, jsonify
from flask_socketio import SocketIO
import pysrt
from translatepy import Translator

def signal_handler(sig, frame):
    print("\n[!] توقف برنامه...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

app = Flask(__name__)
app.config["SECRET_KEY"] = "independent_sub_audio_secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_AUDIO_DIR = os.path.join(BASE_DIR, "static", "dub_audio")
os.makedirs(STATIC_AUDIO_DIR, exist_ok=True)
@app.route('/check_video_sub', methods=['POST'])
def check_video_sub():
    """بررسی فایل ویدیو برای یافتن زیرنویس‌های داخلی (Embedded Subtitles)"""
    if 'videoFile' not in request.files:
        return jsonify({"has_sub": False, "message": "فایل ویدیویی دریافت نشد."})
    
    file = request.files['videoFile']
    if file.filename == '':
        return jsonify({"has_sub": False, "message": "فایلی انتخاب نشده است."})

    try:
        # ذخیره موقت ویدیو برای بررسی با ffprobe
        temp_dir = tempfile.gettempdir()
        temp_video_path = os.path.join(temp_dir, file.filename)
        file.save(temp_video_path)

        cmd = [
            "ffprobe", 
            "-v", "quiet", 
            "-print_format", "json", 
            "-show_streams", 
            temp_video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        # پیدا کردن استریم‌های زیرنویس
        subtitle_streams = [s for s in data.get("streams", []) if s.get("codec_type") == "subtitle"]
        
        has_sub = len(subtitle_streams) > 0
        lang = "نامشخص"
        if has_sub:
            # تلاش برای پیدا کردن زبان اولین زیرنویس داخلی
            tags = subtitle_streams[0].get("tags", {})
            lang = tags.get("language", "معمولی")

        # پاکسازی فایل موقت ویدیو
        try:
            os.remove(temp_video_path)
        except:
            pass

        if has_sub:
            return jsonify({
                "has_sub": True, 
                "message": f"✅ ویدیو دارای زیرنویس داخلی (زبان: {lang}) است!"
            })
        else:
            return jsonify({
                "has_sub": False, 
                "message": "ℹ️ این ویدیو زیرنویس داخلی چسبیده ندارد. لطفاً فایل SRT جداگانه انتخاب کنید."
            })

    except Exception as e:
        print(f"[!] خطای بررسی زیرنویس ویدیو: {e}")
        return jsonify({"has_sub": False, "message": "خطا در بررسی فایل ویدیو (ممکن است ابزار ffprobe روی سیستم نصب نباشد)."}), 500

VOICE_MAPPING = {
    "ro": {"female": "ro-RO-AlinaNeural", "male": "ro-RO-EmilNeural"},
    "fa": {"female": "fa-IR-DilaraNeural", "male": "fa-IR-FaridNeural"},
    "en": {"female": "en-US-JennyNeural", "male": "en-US-GuyNeural"},
    "de": {"female": "de-DE-KatjaNeural", "male": "de-DE-KillianNeural"},
    "fr": {"female": "fr-FR-DeniseNeural", "male": "fr-FR-HenriNeural"},
    "es": {"female": "es-ES-ElviraNeural", "male": "es-ES-AlvaroNeural"},
    "it": {"female": "it-IT-ElsaNeural", "male": "it-IT-DiegoNeural"},
    "tr": {"female": "tr-TR-EmelNeural", "male": "tr-TR-AhmetNeural"},
    "ru": {"female": "ru-RU-SvetlanaNeural", "male": "ru-RU-DmitryNeural"},
    "ar": {"female": "ar-SA-ZariyahNeural", "male": "ar-SA-HamedNeural"},
    "zh": {"female": "zh-CN-XiaoxiaoNeural", "male": "zh-CN-YunjianNeural"}
}

# راه‌اندازی مترجم قدرتمند با قابلیت سوییچ خودکار بین موتورها
translator = Translator()

def safe_single_translate(text, target_lang):
    """ترجمه امن و ضد خطا با translatepy"""
    if not target_lang or target_lang == "none" or not text or not str(text).strip():
        return str(text) if text else ""
    try:
        res = translator.translate(text, destination_language=target_lang)
        if res and str(res).strip():
            return str(res).strip()
    except Exception as e:
        print(f"[!] خطای ترجمه: {e}")
    return str(text).strip()

def process_single_sub(sub_info, gender, audio_lang):
    if sys.is_finalizing():
        return None

    i, display_text, audio_text, start_ms, end_ms = sub_info
    audio_url = None

    clean_audio_text = str(audio_text).strip() if audio_text is not None else ""
    clean_display_text = str(display_text).strip() if display_text is not None else ""

    if not clean_audio_text:
        clean_audio_text = clean_display_text

    if audio_lang and audio_lang != "none" and clean_audio_text:
        voices = VOICE_MAPPING.get(audio_lang, VOICE_MAPPING["en"])
        voice = voices["female"] if gender == "female" else voices["male"]

        audio_filename = f"audio_{start_ms}_{i}.mp3"
        audio_out_path = os.path.join(STATIC_AUDIO_DIR, audio_filename)

        async def make_tts():
            communicate = edge_tts.Communicate(clean_audio_text, voice)
            await communicate.save(audio_out_path)

        try:
            if not sys.is_finalizing():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(make_tts())
                loop.close()

                if os.path.exists(audio_out_path) and os.path.getsize(audio_out_path) > 0:
                    audio_url = f"/static/dub_audio/{audio_filename}"
        except Exception as e:
            print(f"[!] خطای ساخت صدا در خط {i+1}: {e}")

    item = {
        "id": i,
        "display_text": clean_display_text,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "audio_url": audio_url,
        "played": False
    }

    try:
        socketio.emit('chunk_ready', item)
    except Exception as e:
        print(f"[!] خطای ارسال سوکت: {e}")

    return item

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/dub_audio/<filename>')
def serve_audio(filename):
    return send_from_directory(STATIC_AUDIO_DIR, filename)

@app.route('/process', methods=['POST'])
def process_srt():
    try:
        data = request.form
        srt_data = data.get('srt_data')
        gender = data.get('gender', 'male')
        text_lang = data.get('text_lang', 'fa')
        audio_lang = data.get('audio_lang', 'ro')

        video_file = request.files.get('video_file_obj')

        # اگر فایل SRT مستقیم ارسال نشده بود، اما ویدیو ارسال شده بود، سعی کن از ویدیو زیرنویس استخراج کنی
        if not srt_data and video_file and video_file.filename != '':
            try:
                temp_dir = tempfile.gettempdir()
                temp_vid_path = os.path.join(temp_dir, f"extract_{video_file.filename}")
                video_file.save(temp_vid_path)

                temp_srt_path = os.path.join(temp_dir, "extracted_sub.srt")
                
                # دستور ffmpeg برای استخراج اولین استریم زیرنویس ویدیو به فرمت srt
                # (اگر زیرنویس مبتنی بر متن باشد مثل ass یا srt)
                extract_cmd = [
                    "ffmpeg", "-y",
                    "-i", temp_vid_path,
                    "-map", "0:s:0", # انتخاب اولین استریم زیرنویس
                    temp_srt_path
                ]
                
                res = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=15)
                
                if res.returncode == 0 and os.path.exists(temp_srt_path) and os.path.getsize(temp_srt_path) > 0:
                    with open(temp_srt_path, 'r', encoding='utf-8', errors='ignore') as f_srt:
                        srt_data = f_srt.read()
                
                # پاکسازی فایل‌های موقت
                for p in [temp_vid_path, temp_srt_path]:
                    if os.path.exists(p):
                        try: os.remove(p)
                        except: pass
            except Exception as e:
                print(f"[!] خطا در استخراج خودکار زیرنویس از ویدیو: {e}")

        if not srt_data:
            return jsonify({"status": "error", "message": "زیرنویسی یافت نشد. لطفاً فایل SRT جداگانه آپلود کنید یا ویدیویی دارای زیرنویس داخلی انتخاب کنید."}), 400

        def run_background_process():
            try:
                for f in os.listdir(STATIC_AUDIO_DIR):
                    try:
                        os.remove(os.path.join(STATIC_AUDIO_DIR, f))
                    except Exception:
                        pass

                try:
                    subs = pysrt.from_string(srt_data)
                except Exception:
                    socketio.emit('status_update', {'msg': '❌ فرمت زیرنویس نامعتبر است.'})
                    return

                raw_sub_data = []
                for i, sub in enumerate(subs):
                    text = sub.text_without_tags.strip()
                    if not text:
                        continue
                    start_ms = (sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds) * 1000 + sub.start.milliseconds
                    end_ms = (sub.end.hours * 3600 + sub.end.minutes * 60 + sub.end.seconds) * 1000 + sub.end.milliseconds
                    raw_sub_data.append((i, text, start_ms, end_ms))

                total_subs = len(raw_sub_data)
                if total_subs == 0:
                    socketio.emit('status_update', {'msg': '❌ محتوای متنی در زیرنویس یافت نشد.'})
                    return

                for idx, (i, orig_text, start_ms, end_ms) in enumerate(raw_sub_data):
                    progress = min(100, int(((idx + 1) / total_subs) * 100))
                    socketio.emit('status_update', {'msg': f'در حال پردازش ({progress}%)...'})

                    d_text = safe_single_translate(orig_text, text_lang)
                    a_text = d_text if audio_lang == text_lang else safe_single_translate(orig_text, audio_lang)

                    sub_info = (i, d_text, a_text, start_ms, end_ms)
                    process_single_sub(sub_info, gender, audio_lang)
                    
                    time.sleep(0.05)

                socketio.emit('processing_finished', {})
                print("[✔] پردازش با موفقیت به پایان رسید.")

            except Exception as bg_err:
                traceback.print_exc()

        t = threading.Thread(target=run_background_process, daemon=True)
        t.start()
        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"[!] خطای مسیر process: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
if __name__ == '__main__':
    url = 'http://127.0.0.1:5000'
    print(f"\n[+] سرور اجرا شد. در حال باز کردن برنامه روی: {url}\n")

    use_native_gui = False
    if HAS_WEBVIEW:
        try:
            webview.create_window(
                title='مترجم و دوبلور هوشمند زیرنویس',
                url=url,
                width=1000,
                height=800,
                resizable=True
            )
            use_native_gui = True
        except Exception:
            use_native_gui = False

    if use_native_gui:
        server_thread = threading.Thread(
            target=lambda: socketio.run(app, host='127.0.0.1', port=5000, debug=False, use_reloader=False),
            daemon=True
        )
        server_thread.start()
        webview.start()
    else:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        socketio.run(app, host='127.0.0.1', port=5000, debug=False, use_reloader=False)
