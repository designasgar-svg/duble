import asyncio
import os
import sys
import signal
import time
import traceback
import edge_tts
from flask import Flask, render_template, request, send_from_directory, jsonify
from flask_socketio import SocketIO
import pysrt
from googletrans import Translator

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

translator = Translator()

def translate_safe_chunk(text_list, target_lang):
    """ترجمه آرایه‌ای بدون ارسال درخواست‌های تک‌تک"""
    if not target_lang or target_lang == "none" or not text_list:
        return text_list

    try:
        translations = translator.translate(text_list, dest=target_lang)
        result = []
        for t, orig in zip(translations, text_list):
            if t and hasattr(t, 'text') and t.text and t.text.strip():
                result.append(t.text)
            else:
                result.append(orig)
        return result
    except Exception as e:
        print(f"[!] خطای شبکه در ترجمه این دسته: {e}")
        return text_list

def process_single_sub(sub_info, gender, audio_lang):
    if sys.is_finalizing():
        return None

    i, display_text, audio_text, start_ms, end_ms = sub_info
    audio_url = None

    # پاک‌سازی متون
    clean_audio_text = (audio_text or "").strip()
    clean_display_text = (display_text or "").strip()

    if not clean_audio_text:
        clean_audio_text = clean_display_text

    # تنها در صورتی که متن معتبر وجود داشته باشد TTS اجرا می‌شود
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
                asyncio.run(make_tts())
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
        srt_data = request.form.get('srt_data')
        gender = request.form.get('gender', 'male')
        text_lang = request.form.get('text_lang', 'fa')
        audio_lang = request.form.get('audio_lang', 'ro')

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
                except Exception as srt_err:
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

                chunk_size = 50

                for chunk_start in range(0, total_subs, chunk_size):
                    chunk_raw = raw_sub_data[chunk_start:chunk_start + chunk_size]
                    chunk_orig_texts = [item[1] for item in chunk_raw]

                    progress = min(100, int(((chunk_start + len(chunk_raw)) / total_subs) * 100))
                    socketio.emit('status_update', {'msg': f'در حال پردازش سریع ({progress}%)...'})

                    display_texts = translate_safe_chunk(chunk_orig_texts, text_lang)
                    if audio_lang == text_lang:
                        audio_texts = display_texts
                    else:
                        audio_texts = translate_safe_chunk(chunk_orig_texts, audio_lang)

                    for idx, (i, orig_text, start_ms, end_ms) in enumerate(chunk_raw):
                        d_text = display_texts[idx] if idx < len(display_texts) else orig_text
                        a_text = audio_texts[idx] if idx < len(audio_texts) else orig_text
                        
                        sub_info = (i, d_text, a_text, start_ms, end_ms)
                        process_single_sub(sub_info, gender, audio_lang)

                    time.sleep(0.1)

                socketio.emit('processing_finished', {})
                print("[✔] پردازش با موفقیت به پایان رسید.")

            except Exception as bg_err:
                traceback.print_exc()

        import threading
        t = threading.Thread(target=run_background_process, daemon=True)
        t.start()
        return jsonify({"status": "ok"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
