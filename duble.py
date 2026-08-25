import asyncio
import os
import sys
import signal
import re
from concurrent.futures import ThreadPoolExecutor
import edge_tts
from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit
import pysrt
from deep_translator import GoogleTranslator

# مدیریت خروج آنی با Ctrl+C
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

def translate_batch(text_list, target_lang):
    if not target_lang or target_lang == "none" or not text_list:
        return text_list

    translated_results = []
    chunk_size = 20
    delimiter = " ||| "

    for i in range(0, len(text_list), chunk_size):
        chunk = text_list[i:i + chunk_size]
        combined_text = delimiter.join(chunk)

        try:
            translated_combined = GoogleTranslator(source='auto', target=target_lang).translate(combined_text)
            # استفاده از Regex برای جدا کردن خطوط حتی در صورت فاصله انداختن گوگل
            translated_chunk = re.split(r'\s*\|\|\|\s*', translated_combined)

            if len(translated_chunk) == len(chunk):
                translated_results.extend([t.strip() for t in translated_chunk])
            else:
                print(f"[!] عدم تطابق خطوط ترجمه (درخواست: {len(chunk)}، دریافت: {len(translated_chunk)})")
                translated_results.extend(chunk)
        except Exception as e:
            print(f"[!] خطای ترجمه گوگل: {e}")
            translated_results.extend(chunk)

    return translated_results

def process_single_sub(sub_info, gender, audio_lang):
    if sys.is_finalizing():
        return None

    i, display_text, audio_text, start_ms, end_ms = sub_info
    audio_url = None

    if audio_lang and audio_lang != "none":
        voices = VOICE_MAPPING.get(audio_lang, VOICE_MAPPING["en"])
        voice = voices["female"] if gender == "female" else voices["male"]

        audio_filename = f"audio_{start_ms}.mp3"
        audio_out_path = os.path.join(STATIC_AUDIO_DIR, audio_filename)

        # تابع ساخت صدا با تلاش مجدد (Retry)
        async def make_tts_with_retry():
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    communicate = edge_tts.Communicate(audio_text, voice)
                    await communicate.save(audio_out_path)
                    return True
                except Exception as err:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1) # ۱ ثانیه صبر قبل از تلاش مجدد
                    else:
                        raise err

        try:
            if not sys.is_finalizing():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(make_tts_with_retry())
                loop.close()
                audio_url = f"/static/dub_audio/{audio_filename}"
                print(f"[+] فایل ساخته شد: {audio_filename}")
        except Exception as e:
            print(f"[!] خطای ساخت صدا در زیرنویس {i}: {type(e).__name__} - {e}")

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
    except Exception as e:
        print(f"[!] خطای ارسال به سوکت: {e}")
        
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
        raw_sub_data = []
        orig_texts = []

        for i, sub in enumerate(subs):
            text = sub.text_without_tags.strip()
            if not text:
                continue
            start_ms = (sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds) * 1000 + sub.start.milliseconds
            end_ms = (sub.end.hours * 3600 + sub.end.minutes * 60 + sub.end.seconds) * 1000 + sub.end.milliseconds
            
            raw_sub_data.append((i, text, start_ms, end_ms))
            orig_texts.append(text)

        try:
            socketio.emit('status_update', {'msg': f'در حال ترجمه یکجای {len(orig_texts)} خط زیرنویس...'})
        except Exception:
            pass

        display_texts = translate_batch(orig_texts, text_lang)
        if audio_lang == text_lang:
            audio_texts = display_texts
        else:
            audio_texts = translate_batch(orig_texts, audio_lang)

        sub_tasks = []
        for idx, (i, orig_text, start_ms, end_ms) in enumerate(raw_sub_data):
            d_text = display_texts[idx] if idx < len(display_texts) else orig_text
            a_text = audio_texts[idx] if idx < len(audio_texts) else orig_text
            sub_tasks.append((i, d_text, a_text, start_ms, end_ms))

        try:
            socketio.emit('status_update', {'msg': 'ترجمه انجام شد. در حال ساخت صداهای دوبله...'})
        except Exception:
            pass

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(process_single_sub, task, gender, audio_lang)
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
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)