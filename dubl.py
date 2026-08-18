import asyncio
import os
import sys
import signal
from concurrent.futures import ThreadPoolExecutor
import edge_tts
from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit
import pysrt
from deep_translator import GoogleTranslator

# مدیریت خروج آنی و سریع با Ctrl+C
def signal_handler(sig, frame):
    print("\n[!] توقف سریع برنامه توسط کاربر...")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)

app = Flask(__name__)
app.config["SECRET_KEY"] = "independent_sub_audio_secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

STATIC_AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "dub_audio")
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

def process_single_sub(sub_info, gender, text_lang, audio_lang):
    if sys.is_finalizing():
        return None

    i, orig_text, start_ms, end_ms = sub_info
    
    display_text = orig_text
    if text_lang and text_lang != "none":
        try:
            display_text = GoogleTranslator(source='auto', target=text_lang).translate(orig_text)
        except Exception:
            pass

    audio_text = orig_text
    if audio_lang and audio_lang != "none":
        if audio_lang == text_lang:
            audio_text = display_text
        else:
            try:
                audio_text = GoogleTranslator(source='auto', target=audio_lang).translate(orig_text)
            except Exception:
                pass

    audio_url = None
    if audio_lang and audio_lang != "none":
        voices = VOICE_MAPPING.get(audio_lang, VOICE_MAPPING["en"])
        voice = voices["female"] if gender == "female" else voices["male"]

        audio_filename = f"audio_{start_ms}.mp3"
        audio_out_path = os.path.join(STATIC_AUDIO_DIR, audio_filename)

        async def make_tts():
            communicate = edge_tts.Communicate(audio_text, voice)
            await communicate.save(audio_out_path)

        try:
            if not sys.is_finalizing():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(make_tts())
                loop.close()
                audio_url = f"/static/dub_audio/{audio_filename}"
        except Exception:
            pass

    item = {
        "id": i,
        "display_text": display_text,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "audio_url": audio_url,
        "played": False
    }
    
    try:
        socketio.emit('chunk_ready', item)
    except Exception:
        pass
        
    return item

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/dub_audio/<filename>')
def serve_audio(filename):
    return send_from_directory(STATIC_AUDIO_DIR, filename)

@app.route('/process', methods=['POST'])
def process_srt():
    srt_data = request.form.get('srt_data')
    gender = request.form.get('gender')
    text_lang = request.form.get('text_lang')
    audio_lang = request.form.get('audio_lang')

    def run_background_process():
        for f in os.listdir(STATIC_AUDIO_DIR):
            try:
                os.remove(os.path.join(STATIC_AUDIO_DIR, f))
            except Exception:
                pass

        subs = pysrt.from_string(srt_data)
        sub_tasks = []

        for i, sub in enumerate(subs):
            text = sub.text_without_tags.strip()
            if not text:
                continue

            start_ms = (sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds) * 1000 + sub.start.milliseconds
            end_ms = (sub.end.hours * 3600 + sub.end.minutes * 60 + sub.end.seconds) * 1000 + sub.end.milliseconds
            sub_tasks.append((i, text, start_ms, end_ms))

        try:
            socketio.emit('status_update', {'msg': f'شروع ترجمه و پردازش {len(sub_tasks)} خط زیرنویس...'})
        except Exception:
            pass

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(process_single_sub, task, gender, text_lang, audio_lang)
                for task in sub_tasks
            ]
            for future in futures:
                if sys.is_finalizing():
                    break
                try:
                    res = future.result()
                    if res is None:
                        break
                except Exception:
                    break

        try:
            socketio.emit('processing_finished', {})
        except Exception:
            pass

    import threading
    t = threading.Thread(target=run_background_process, daemon=True)
    t.start()
    return {"status": "ok"}

if __name__ == '__main__':
    print("سرور فعال شد: http://127.0.0.1:5000 (برای توقف Ctrl+C را بزنید)")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)