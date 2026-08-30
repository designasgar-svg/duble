import asyncio
import os
import sys
import signal
import time
import traceback
import threading
import webbrowser

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
from mtranslate import translate

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

def safe_single_translate(text, target_lang):
    """ترجمه تک‌به‌تک و کاملاً ضد خطا"""
    if not target_lang or target_lang == "none" or not text or not str(text).strip():
        return str(text) if text else ""
    try:
        res = translate(text, target_lang)
        if res and isinstance(res, str) and res.strip():
            return res.strip()
    except Exception as e:
        print(f"[!] خطای شبکه در ترجمه: {e}")
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
        data = request.get_json(silent=True) or request.form
        srt_data = data.get('srt_data')
        gender = data.get('gender', 'male')
        text_lang = data.get('text_lang', 'fa')
        audio_lang = data.get('audio_lang', 'ro')

        if not srt_data:
            return jsonify({"status": "error", "message": "اطلاعات زیرنویس دریافت نشد"}), 400

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
                    socketio.emit('status_update', {'msg': '❌ فرمت فایل نامعتبر است.'})
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
                    socketio.emit('status_update', {'msg': '❌ محتوای متنی یافت نشد.'})
                    return

                for idx, (i, orig_text, start_ms, end_ms) in enumerate(raw_sub_data):
                    progress = min(100, int(((idx + 1) / total_subs) * 100))
                    socketio.emit('status_update', {'msg': f'در حال پردازش ({progress}%)...'})

                    d_text = safe_single_translate(orig_text, text_lang)
                    a_text = d_text if audio_lang == text_lang else safe_single_translate(orig_text, audio_lang)

                    sub_info = (i, d_text, a_text, start_ms, end_ms)
                    process_single_sub(sub_info, gender, audio_lang)
                    
                    time.sleep(0.02)  # وقفه کوتاه جهت جلوگیری از مسدودی API

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

    # بررسی اجرای برنامه در ویندوز/دسکتاپ یا Termux
    use_native_gui = False
    if HAS_WEBVIEW:
        try:
            # بررسی اولیه جهت حصول اطمینان از امکان ساخت پنجره
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
        # اگر سیستم‌عامل دسکتاپ باشد و pywebview کار کند
        server_thread = threading.Thread(
            target=lambda: socketio.run(app, host='127.0.0.1', port=5000, debug=False, use_reloader=False),
            daemon=True
        )
        server_thread.start()
        webview.start()
    else:
        # اگر محیط Termux باشد، مرورگر گوشی را باز می‌کند
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        socketio.run(app, host='127.0.0.1', port=5000, debug=False, use_reloader=False)
