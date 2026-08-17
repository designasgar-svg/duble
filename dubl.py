import asyncio
import os
import sys
import signal
from concurrent.futures import ThreadPoolExecutor
import edge_tts
from flask import Flask, render_template_string, request, send_from_directory
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

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>مترجم و دوبلور هوشمند زیرنویس</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        body { font-family: Tahoma, sans-serif; background: #121212; color: #fff; text-align: center; padding: 20px; margin: 0; user-select: none; }
        .container { max-width: 900px; margin: auto; background: #1e1e1e; padding: 20px; border-radius: 12px; }
        .form-group { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; text-align: right; }
        .form-group div { flex: 1; min-width: 200px; }
        label { display: block; margin-bottom: 5px; font-size: 13px; color: #ccc; }
        input[type="file"], select, button { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #333; background: #2a2a2a; color: #fff; box-sizing: border-box; }
        
        .panel-box { background: #252525; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #333; text-align: right; }
        .panel-title { font-weight: bold; margin-bottom: 12px; color: #ffca28; font-size: 15px; }

        .sync-box { background: #2d261e; border: 1px solid #ff9800; padding: 15px; border-radius: 8px; margin-bottom: 15px; text-align: right; }
        .sync-title { font-weight: bold; color: #ffb74d; margin-bottom: 10px; font-size: 15px; }
        .sync-buttons { display: flex; gap: 10px; margin-top: 10px; }
        .sync-btn { flex: 1; padding: 12px; font-size: 13px; font-weight: bold; border-radius: 6px; border: none; cursor: pointer; transition: 0.2s; }
        .sync-btn-delay { background: #d32f2f; color: #fff; }
        .sync-btn-delay:hover { background: #b71c1c; }
        .sync-btn-advance { background: #388e3c; color: #fff; }
        .sync-btn-advance:hover { background: #2e7d32; }
        .sync-info { margin-top: 10px; text-align: center; font-size: 14px; color: #ffcc80; font-weight: bold; }

        .volume-control-group { display: flex; flex-direction: column; gap: 12px; margin-top: 10px; background: #2a2a2a; padding: 12px; border-radius: 6px; border: 1px solid #333; }
        .volume-row { display: flex; align-items: center; gap: 10px; }
        .volume-row label { width: 130px; margin-bottom: 0; font-weight: bold; font-size: 13px; }
        .volume-row input[type="range"] { flex: 1; height: 6px; border-radius: 3px; cursor: pointer; }
        .volume-row span { width: 45px; text-align: left; font-size: 13px; font-weight: bold; color: #ffca28; }

        button.process-btn { background: #007bff; border: none; font-weight: bold; cursor: pointer; font-size: 16px; padding: 12px; }
        button.process-btn:hover { background: #0056b3; }
        button.fullscreen-btn { background: #ff9800; color: #000; border: none; font-weight: bold; cursor: pointer; font-size: 14px; padding: 10px; margin-top: 10px; }
        button.fullscreen-btn:hover { background: #e68a00; }
        button:disabled { background: #444; cursor: not-allowed; }
        
        .video-wrapper { position: relative; width: 100%; margin-top: 15px; background: #000; border-radius: 8px; overflow: hidden; }
        video { width: 100%; max-height: 440px; display: block; }
        
        .subtitle-overlay {
            position: absolute;
            bottom: 60px;
            left: 5%;
            right: 5%;
            text-align: center;
            color: #ffffff;
            font-size: 24px;
            font-weight: bold;
            text-shadow: 2px 2px 4px #000, -2px -2px 4px #000, 2px -2px 4px #000, -2px 2px 4px #000;
            background: rgba(0, 0, 0, 0.75);
            padding: 10px 16px;
            border-radius: 8px;
            pointer-events: none;
            display: none;
            line-height: 1.4;
            z-index: 2147483647;
        }

        .video-wrapper:-webkit-full-screen { width: 100vw; height: 100vh; display: flex; align-items: center; justify-content: center; }
        .video-wrapper:-moz-full-screen { width: 100vw; height: 100vh; display: flex; align-items: center; justify-content: center; }
        .video-wrapper:fullscreen {
            width: 100vw;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #000;
        }
        
        .video-wrapper:fullscreen video,
        .video-wrapper:-webkit-full-screen video {
            max-height: 100vh;
            width: 100%;
            height: 100%;
            object-fit: contain;
        }

        .video-wrapper:fullscreen .subtitle-overlay,
        .video-wrapper:-webkit-full-screen .subtitle-overlay {
            bottom: 80px;
            font-size: 34px;
            z-index: 2147483647;
        }

        #status { color: #17a2b8; margin: 12px 0; font-weight: bold; font-size: 15px; min-height: 22px; }
        #log { background: #000; color: #0f0; padding: 10px; border-radius: 6px; height: 100px; overflow-y: auto; text-align: left; font-family: monospace; font-size: 11px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h2>🎙️ پنل ترجمه و دوبله هوشمند زیرنویس</h2>
        
        <div class="form-group">
            <div>
                <label>۱. انتخاب فایل ویدیو:</label>
                <input type="file" id="videoFile" accept="video/*" onchange="loadVideo(event)">
            </div>
            <div>
                <label>۲. انتخاب فایل زیرنویس (.srt):</label>
                <input type="file" id="srtFile" accept=".srt">
            </div>
        </div>

        <div class="panel-box">
            <div class="panel-title">⚙️ تنظیمات زبان، ترجمه و دوبله</div>
            
            <div class="form-group">
                <div>
                    <label>📝 زبان زیرنویس (نمایش روی ویدیو):</label>
                    <select id="textLang">
                        <option value="fa" selected>فارسی (Persian)</option>
                        <option value="ro">رومانیایی (Romanian)</option>
                        <option value="en">انگلیسی (English)</option>
                        <option value="de">آلمانی (German)</option>
                        <option value="fr">فرانسوی (French)</option>
                        <option value="es">اسپانیایی (Spanish)</option>
                        <option value="tr">ترکی (Turkish)</option>
                        <option value="ru">روسی (Russian)</option>
                        <option value="ar">عربی (Arabic)</option>
                        <option value="none">بدون تغییر (متن اصلی زیرنویس)</option>
                    </select>
                </div>
                <div>
                    <label>🔊 زبان دوبله صوتی:</label>
                    <select id="audioLang">
                        <option value="ro" selected>رومانیایی (Romanian)</option>
                        <option value="fa">فارسی (Persian)</option>
                        <option value="en">انگلیسی (English)</option>
                        <option value="de">آلمانی (German)</option>
                        <option value="fr">فرانسوی (French)</option>
                        <option value="es">اسپانیایی (Spanish)</option>
                        <option value="tr">ترکی (Turkish)</option>
                        <option value="ru">روسی (Russian)</option>
                        <option value="ar">عربی (Arabic)</option>
                        <option value="none">بدون صدا (فقط زیرنویس)</option>
                    </select>
                </div>
                <div>
                    <label>👤 جنسیت صدای دوبله:</label>
                    <select id="voiceGender">
                        <option value="male" selected>👨 مرد</option>
                        <option value="female">👩 زن</option>
                    </select>
                </div>
            </div>

            <div class="volume-control-group">
                <div class="volume-row">
                    <label>🎬 صدای ویدیو اصلی:</label>
                    <input type="range" id="videoVolSlider" min="0" max="1" step="0.05" value="0.2">
                    <span id="videoVolVal">20%</span>
                </div>
                <div class="volume-row">
                    <label>🎙️ صدای دوبله:</label>
                    <input type="range" id="dubVolSlider" min="0" max="1" step="0.05" value="1.0">
                    <span id="dubVolVal">100%</span>
                </div>
            </div>
        </div>

        <div class="sync-box">
            <div class="sync-title">⏱️ همگام‌سازی و سینک سریع زیرنویس و صدا</div>
            <div class="sync-buttons">
                <button class="sync-btn sync-btn-delay" onclick="adjustSync(500)">
                    ⏩ اگر صدا/زیرنویس زودتر پخش میشه (تأخیر ۰٫۵ ثانیه)
                </button>
                <button class="sync-btn sync-btn-advance" onclick="adjustSync(-500)">
                    ⏪ اگر صدا/زیرنویس دیرتر پخش میشه (جلو انداختن ۰٫۵ ثانیه)
                </button>
            </div>
            <div class="sync-info" id="syncStatus">میزان جابه‌جایی فعلی: 0 ثانیه (0ms)</div>
        </div>

        <button id="processBtn" class="process-btn" onclick="startProcessing()">شروع پردازش، ترجمه و پخش 🚀</button>

        <div id="status">ویدیو و زیرنویس را انتخاب کنید.</div>
        
        <div class="video-wrapper" id="videoContainer">
            <div id="subOverlay" class="subtitle-overlay"></div>
            <video id="mainVideo" controls controlsList="nofullscreen" ondblclick="toggleCustomFullscreen()"></video>
        </div>

        <button class="fullscreen-btn" onclick="toggleCustomFullscreen()">📺 حالت تمام‌صفحه با زیرنویس (Fullscreen)</button>
        
        <audio id="audioPlayer" style="display:none;"></audio>
        
        <div id="log">--- گزارش سیستم ---</div>
    </div>

    <script>
        const socket = io();
        const video = document.getElementById('mainVideo');
        const videoContainer = document.getElementById('videoContainer');
        const audioPlayer = document.getElementById('audioPlayer');
        const logDiv = document.getElementById('log');
        const statusDiv = document.getElementById('status');
        const processBtn = document.getElementById('processBtn');
        const subOverlay = document.getElementById('subOverlay');

        const videoVolSlider = document.getElementById('videoVolSlider');
        const videoVolVal = document.getElementById('videoVolVal');
        const dubVolSlider = document.getElementById('dubVolSlider');
        const dubVolVal = document.getElementById('dubVolVal');
        const syncStatus = document.getElementById('syncStatus');
        
        let dubbingMap = {};
        let syncOffsetMs = 0;

        video.volume = parseFloat(videoVolSlider.value);
        audioPlayer.volume = parseFloat(dubVolSlider.value);

        function toggleCustomFullscreen() {
            const isFullscreen = document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement;
            if (!isFullscreen) {
                if (videoContainer.requestFullscreen) {
                    videoContainer.requestFullscreen();
                } else if (videoContainer.webkitRequestFullscreen) {
                    videoContainer.webkitRequestFullscreen();
                } else if (videoContainer.msRequestFullscreen) {
                    videoContainer.msRequestFullscreen();
                }
            } else {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                } else if (document.webkitExitFullscreen) {
                    document.webkitExitFullscreen();
                } else if (document.mozCancelFullScreen) {
                    document.mozCancelFullScreen();
                }
            }
        }

        videoVolSlider.addEventListener('input', function() {
            video.volume = parseFloat(this.value);
            videoVolVal.innerText = Math.round(video.volume * 100) + '%';
        });

        dubVolSlider.addEventListener('input', function() {
            audioPlayer.volume = parseFloat(this.value);
            dubVolVal.innerText = Math.round(audioPlayer.volume * 100) + '%';
        });

        function adjustSync(deltaMs) {
            syncOffsetMs += deltaMs;
            const seconds = (syncOffsetMs / 1000).toFixed(1);
            syncStatus.innerText = `میزان جابه‌جایی فعلی: ${seconds > 0 ? '+' + seconds : seconds} ثانیه (${syncOffsetMs}ms)`;
            appendLog(`⏱️ سینک آپدیت شد: ${seconds} ثانیه`);
            
            const currentTimeMs = (video.currentTime * 1000) - syncOffsetMs;
            for (let id in dubbingMap) {
                let item = dubbingMap[id];
                item.played = item.end_ms < currentTimeMs;
            }
        }

        function appendLog(text) {
            logDiv.innerHTML += text + "<br>";
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        function loadVideo(event) {
            const file = event.target.files[0];
            if (file) {
                video.src = URL.createObjectURL(file);
                video.volume = parseFloat(videoVolSlider.value);
                statusDiv.innerText = "ویدیو بارگذاری شد. حالا فایل زیرنویس را انتخاب کنید.";
            }
        }

        socket.on('status_update', data => {
            statusDiv.innerText = data.msg;
            appendLog(data.msg);
        });

        socket.on('chunk_ready', item => {
            dubbingMap[item.id] = item;
            if (Object.keys(dubbingMap).length === 3) {
                statusDiv.innerText = "▶️ آماده پخش! می‌توانید فیلم را شروع کنید.";
                appendLog("💡 آماده‌سازی اولیه انجام شد. پخش ویدیو آزاد است.");
            }
        });

        socket.on('processing_finished', () => {
            statusDiv.innerText = "✅ پردازش زیرنویس و ترجمه به پایان رسید!";
            appendLog("پایان کل پردازش.");
            processBtn.disabled = false;
        });

        video.ontimeupdate = function() {
            const currentTimeMs = (video.currentTime * 1000) - syncOffsetMs;
            let currentSubFound = false;

            const keys = Object.keys(dubbingMap);
            for (let i = 0; i < keys.length; i++) {
                let item = dubbingMap[keys[i]];
                
                if (item.start_ms > currentTimeMs + 1000) break;

                if (currentTimeMs >= item.start_ms && currentTimeMs <= (item.end_ms + 300)) {
                    if (item.display_text) {
                        subOverlay.innerText = item.display_text;
                        subOverlay.style.display = "block";
                    }
                    currentSubFound = true;

                    if (!item.played) {
                        item.played = true;
                        if (item.audio_url) {
                            audioPlayer.src = item.audio_url;
                            audioPlayer.currentTime = 0;
                            audioPlayer.volume = parseFloat(dubVolSlider.value);
                            audioPlayer.play().catch(() => {});
                        }
                    }
                    break;
                }
            }

            if (!currentSubFound) {
                subOverlay.style.display = "none";
            }
        };

        video.onseeking = function() {
            audioPlayer.pause();
            subOverlay.style.display = "none";
            const currentTimeMs = (video.currentTime * 1000) - syncOffsetMs;
            for (let id in dubbingMap) {
                dubbingMap[id].played = dubbingMap[id].end_ms < currentTimeMs;
            }
        };

        async function startProcessing() {
            const srtInput = document.getElementById('srtFile');
            const voiceGender = document.getElementById('voiceGender').value;
            const textLang = document.getElementById('textLang').value;
            const audioLang = document.getElementById('audioLang').value;

            if (!srtInput.files[0]) {
                alert("لطفاً فایل زیرنویس SRT را انتخاب کنید.");
                return;
            }

            processBtn.disabled = true;
            logDiv.innerHTML = "";
            dubbingMap = {};

            statusDiv.innerText = "⏳ در حال آنالیز، ترجمه و ساخت صدا...";

            const srtText = await srtInput.files[0].text();
            const formData = new FormData();
            formData.append('srt_data', srtText);
            formData.append('gender', voiceGender);
            formData.append('text_lang', textLang);
            formData.append('audio_lang', audioLang);

            fetch('/process', { method: 'POST', body: formData });
        }
    </script>
</body>
</html>
"""

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
            # نادیده گرفتن خطاهای خروج از مفسر هنگام Ctrl+C
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
    return render_template_string(HTML_TEMPLATE)

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