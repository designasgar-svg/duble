import asyncio
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
import edge_tts
from flask import Flask, render_template_string, request, send_from_directory
from flask_socketio import SocketIO, emit
import numpy as np
import pysrt
import imageio_ffmpeg
from deep_translator import GoogleTranslator

app = Flask(__name__)
app.config["SECRET_KEY"] = "independent_sub_audio_secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

STATIC_AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "dub_audio")
os.makedirs(STATIC_AUDIO_DIR, exist_ok=True)

# دریافت خودکار مسیر ffmpeg داخلی پایتون
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

# نقشه صداهای زن و مرد برای زبان‌های مختلف
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
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>مترجم و دوبلور هوشمند (مستقل)</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        body { font-family: Tahoma, sans-serif; background: #121212; color: #fff; text-align: center; padding: 20px; margin: 0; user-select: none; -webkit-user-select: none; }
        .container { max-width: 900px; margin: auto; background: #1e1e1e; padding: 20px; border-radius: 12px; }
        .form-group { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; text-align: right; }
        .form-group div { flex: 1; min-width: 200px; }
        label { display: block; margin-bottom: 5px; font-size: 13px; color: #ccc; }
        input[type="file"], select, button { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #333; background: #2a2a2a; color: #fff; box-sizing: border-box; }
        
        .panel-box { background: #252525; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #333; text-align: right; }
        .panel-title { font-weight: bold; margin-bottom: 12px; color: #ffca28; font-size: 15px; display: flex; align-items: center; gap: 8px; }

        .switch-container { display: flex; align-items: center; justify-content: space-between; background: #2a2a2a; padding: 10px 15px; border-radius: 6px; margin-top: 10px; border: 1px solid #333; }
        .switch { position: relative; display: inline-block; width: 46px; height: 24px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #555; transition: .3s; border-radius: 24px; }
        .slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 3px; background-color: white; transition: .3s; border-radius: 50%; }
        input:checked + .slider { background-color: #28a745; }
        input:checked + .slider:before { transform: translateX(22px); }

        button { background: #007bff; border: none; font-weight: bold; cursor: pointer; font-size: 15px; }
        button:hover { background: #0056b3; }
        button:disabled { background: #444; cursor: not-allowed; }
        
        .video-wrapper { position: relative; width: 100%; margin-top: 15px; }
        video { width: 100%; max-height: 440px; border-radius: 8px; background: #000; touch-action: manipulation; }
        
        /* نمایش زیرنویس ترجمه‌شده روی ویدیو */
        .subtitle-overlay {
            position: absolute;
            bottom: 65px;
            left: 5%;
            right: 5%;
            text-align: center;
            color: #ffffff;
            font-size: 22px;
            font-weight: bold;
            text-shadow: 2px 2px 4px #000, -2px -2px 4px #000, 2px -2px 4px #000, -2px 2px 4px #000;
            background: rgba(0, 0, 0, 0.65);
            padding: 8px 14px;
            border-radius: 8px;
            pointer-events: none;
            display: none;
            line-height: 1.4;
        }

        .speed-badge {
            position: absolute;
            top: 15px;
            right: 15px;
            background: rgba(0, 0, 0, 0.8);
            color: #ffcc00;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: bold;
            display: none;
            pointer-events: none;
            border: 1px solid #ffcc00;
            box-shadow: 0 0 10px rgba(255, 204, 0, 0.5);
        }

        #status { color: #17a2b8; margin: 12px 0; font-weight: bold; font-size: 15px; min-height: 22px; }
        #log { background: #000; color: #0f0; padding: 10px; border-radius: 6px; height: 100px; overflow-y: auto; text-align: left; font-family: monospace; font-size: 11px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h2>🎙️ پنل ترجمه و دوبله مستقل ویدیو</h2>
        
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

        <!-- پنل تنظیمات مستقل متن و صدا -->
        <div class="panel-box">
            <div class="panel-title">⚙️ تنظیمات زبان متن زیرنویس و صدای دوبله</div>
            
            <div class="form-group">
                <div>
                    <label>📝 زبان زیرنویس (نمایش روی تصویر):</label>
                    <select id="textLang">
                        <option value="fa" selected>فارسی (Persian)</option>
                        <option value="ro">رومانیایی (Romanian)</option>
                        <option value="en">انگلیسی (English)</option>
                        <option value="de">آلمانی (German)</option>
                        <option value="fr">فرانسوی (French)</option>
                        <option value="tr">ترکی (Turkish)</option>
                        <option value="none">بدون تغییر (متن اصلی زیرنویس)</option>
                    </select>
                </div>
                <div>
                    <label>🔊 زبان دوبله صوتی (صداگذاری):</label>
                    <select id="audioLang">
                        <option value="ro" selected>رومانیایی (Romanian)</option>
                        <option value="fa">فارسی (Persian)</option>
                        <option value="en">انگلیسی (English)</option>
                        <option value="de">آلمانی (German)</option>
                        <option value="fr">فرانسوی (French)</option>
                        <option value="tr">ترکی (Turkish)</option>
                        <option value="none">بدون صدا (فقط زیرنویس)</option>
                    </select>
                </div>
            </div>

            <div class="switch-container">
                <span>تشخیص هوشمند جنسیت گوینده (AI) برای انتخاب صدای زن/مرد</span>
                <label class="switch">
                    <input type="checkbox" id="genderSwitch" checked>
                    <span class="slider"></span>
                </label>
            </div>
        </div>

        <button id="processBtn" onclick="startProcessing()">شروع پردازش، ترجمه و پخش 🚀</button>

        <div id="status">ویدیو و زیرنویس را انتخاب کنید.</div>
        
        <div class="video-wrapper">
            <div id="speedBadge" class="speed-badge">⏩ 2X Speed</div>
            <div id="subOverlay" class="subtitle-overlay"></div>
            <video id="mainVideo" controls></video>
        </div>
        
        <audio id="audioPlayer" style="display:none;"></audio>
        
        <div id="log">--- گزارش سیستم ---</div>
    </div>

    <script>
        const socket = io();
        const video = document.getElementById('mainVideo');
        const audioPlayer = document.getElementById('audioPlayer');
        const logDiv = document.getElementById('log');
        const statusDiv = document.getElementById('status');
        const processBtn = document.getElementById('processBtn');
        const speedBadge = document.getElementById('speedBadge');
        const subOverlay = document.getElementById('subOverlay');
        
        let dubbingMap = {};
        let currentRate = 1.0;

        function appendLog(text) {
            logDiv.innerHTML += text + "<br>";
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        function loadVideo(event) {
            const file = event.target.files[0];
            if (file) {
                video.src = URL.createObjectURL(file);
                statusDiv.innerText = "ویدیو بارگذاری شد. حالا زیرنویس را انتخاب کنید.";
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
                appendLog("💡 آماده‌سازی اولیه انجام شد. پخش فیلم آزاد است.");
            }
        });

        socket.on('processing_finished', () => {
            statusDiv.innerText = "✅ تمام زیرنویس‌ها و صداهای فیلم با موفقیت پردازش شدند!";
            appendLog("پایان کل پردازش فیلم.");
            processBtn.disabled = false;
        });

        video.ontimeupdate = function() {
            const currentTimeMs = video.currentTime * 1000;
            let currentSubFound = false;

            for (let id in dubbingMap) {
                let item = dubbingMap[id];
                if (currentTimeMs >= item.start_ms && currentTimeMs <= (item.end_ms + 300)) {
                    // ۱. نمایش متن زیرنویس بر اساس زبان انتخابی متن
                    if (item.display_text) {
                        subOverlay.innerText = item.display_text;
                        subOverlay.style.display = "block";
                    }
                    currentSubFound = true;

                    // ۲. پخش صدای دوبله بر اساس زبان انتخابی صدا
                    if (!item.played) {
                        item.played = true;
                        if (item.audio_url) {
                            audioPlayer.src = item.audio_url;
                            audioPlayer.currentTime = 0;
                            audioPlayer.playbackRate = currentRate;
                            audioPlayer.play().catch(() => {});
                        }
                        statusDiv.innerText = `گویش (${item.gender === 'female' ? '👩 زن' : '👨 مرد'}): ${item.display_text}`;
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
            const currentTimeMs = video.currentTime * 1000;
            for (let id in dubbingMap) {
                dubbingMap[id].played = dubbingMap[id].end_ms < currentTimeMs;
            }
        };

        // --- مدیریت سرعت پخش ۲ برابر ---
        function setSpeed(rate) {
            currentRate = rate;
            video.playbackRate = rate;
            audioPlayer.playbackRate = rate;
            speedBadge.style.display = (rate > 1.0) ? "block" : "none";
        }

        video.addEventListener('touchstart', () => setSpeed(2.0), { passive: true });
        video.addEventListener('touchend', () => setSpeed(1.0));
        video.addEventListener('touchcancel', () => setSpeed(1.0));

        video.addEventListener('mousedown', (e) => { if (e.button === 0) setSpeed(2.0); });
        video.addEventListener('mouseup', () => setSpeed(1.0));
        video.addEventListener('mouseleave', () => setSpeed(1.0));

        async function startProcessing() {
            const videoInput = document.getElementById('videoFile');
            const srtInput = document.getElementById('srtFile');
            const isGenderDetectionOn = document.getElementById('genderSwitch').checked;
            const textLang = document.getElementById('textLang').value;
            const audioLang = document.getElementById('audioLang').value;

            if (!videoInput.files[0] || !srtInput.files[0]) {
                alert("لطفاً هم ویدیو و هم فایل زیرنویس SRT را انتخاب کنید.");
                return;
            }

            processBtn.disabled = true;
            logDiv.innerHTML = "";
            dubbingMap = {};

            statusDiv.innerText = "⏳ در حال آنالیز، ترجمه جداگانه متن/صدا و آماده‌سازی...";

            const srtText = await srtInput.files[0].text();
            const formData = new FormData();
            formData.append('video', videoInput.files[0]);
            formData.append('srt_data', srtText);
            formData.append('gender_detect', isGenderDetectionOn);
            formData.append('text_lang', textLang);
            formData.append('audio_lang', audioLang);

            fetch('/process', { method: 'POST', body: formData });
        }
    </script>
</body>
</html>
"""

def detect_gender_fast(video_path, start_ms, end_ms):
    try:
        if not os.path.exists(video_path):
            return "male"

        start_sec = max(0, (start_ms / 1000.0))
        duration_sec = (end_ms - start_ms) / 1000.0

        if duration_sec < 0.25:
            return "male"

        sample_duration = min(duration_sec, 2.5)

        cmd = [
            FFMPEG_PATH, "-y",
            "-ss", str(start_sec),
            "-t", str(sample_duration),
            "-i", video_path,
            "-vn", "-ac", "1", "-ar", "16000",
            "-f", "s16le", "pipe:1"
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw_audio, _ = process.communicate()

        if not raw_audio or len(raw_audio) < 1600:
            return "male"

        audio = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0

        rms = np.sqrt(np.mean(audio**2))
        if rms < 0.01:
            return "male"

        audio = audio / np.max(np.abs(audio))

        autocorr = np.correlate(audio, audio, mode='full')
        autocorr = autocorr[len(autocorr) // 2:]

        sr = 16000
        min_lag = int(sr / 280)
        max_lag = int(sr / 80)

        if max_lag >= len(autocorr):
            return "male"

        peak_lag = min_lag + np.argmax(autocorr[min_lag:max_lag])
        if peak_lag == 0:
            return "male"

        pitch = sr / peak_lag
        return "female" if 140 <= pitch <= 280 else "male"

    except Exception as e:
        return "male"

def process_single_sub(sub_info, video_path, gender_detect, text_lang, audio_lang):
    i, orig_text, start_ms, end_ms = sub_info
    
    # ۱. ترجمه متن روی تصویر (نمایشی)
    display_text = orig_text
    if text_lang and text_lang != "none":
        try:
            display_text = GoogleTranslator(source='auto', target=text_lang).translate(orig_text)
        except Exception as e:
            print(f"Sub Translation Error (line {i}): {e}")
            display_text = orig_text

    # ۲. ترجمه متن برای تولید صدای دوبله
    audio_text = orig_text
    if audio_lang and audio_lang != "none":
        if audio_lang == text_lang:
            audio_text = display_text  # صرفه‌جویی در درخواست ترجمه
        else:
            try:
                audio_text = GoogleTranslator(source='auto', target=audio_lang).translate(orig_text)
            except Exception as e:
                print(f"Audio Translation Error (line {i}): {e}")
                audio_text = orig_text

    # ۳. تشخیص جنسیت
    gender = detect_gender_fast(video_path, start_ms, end_ms) if gender_detect else "male"
    
    # ۴. تولید فایل صوتی فقط در صورت انتخاب زبان صوتی
    audio_url = None
    if audio_lang and audio_lang != "none":
        voices = VOICE_MAPPING.get(audio_lang, VOICE_MAPPING["ro"])
        voice = voices["female"] if gender == "female" else voices["male"]

        audio_filename = f"audio_{start_ms}.mp3"
        audio_out_path = os.path.join(STATIC_AUDIO_DIR, audio_filename)

        async def make_tts():
            communicate = edge_tts.Communicate(audio_text, voice)
            await communicate.save(audio_out_path)

        try:
            asyncio.run(make_tts())
            audio_url = f"/static/dub_audio/{audio_filename}"
        except Exception as e:
            print(f"TTS Generation Error (line {i}): {e}")

    item = {
        "id": i,
        "display_text": display_text,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "gender": gender,
        "audio_url": audio_url,
        "played": False
    }
    
    socketio.emit('chunk_ready', item)
    return item

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/static/dub_audio/<filename>')
def serve_audio(filename):
    return send_from_directory(STATIC_AUDIO_DIR, filename)

@app.route('/process', methods=['POST'])
def process_video_and_srt():
    video_file = request.files.get('video')
    srt_data = request.form.get('srt_data')
    gender_detect = request.form.get('gender_detect') == 'true'
    text_lang = request.form.get('text_lang')
    audio_lang = request.form.get('audio_lang')

    temp_dir = tempfile.mkdtemp()
    video_path = os.path.join(temp_dir, "temp_video.mp4")
    video_file.save(video_path)

    def run_background_process():
        for f in os.listdir(STATIC_AUDIO_DIR):
            os.remove(os.path.join(STATIC_AUDIO_DIR, f))

        subs = pysrt.from_string(srt_data)
        sub_tasks = []

        for i, sub in enumerate(subs):
            text = sub.text_without_tags.strip()
            if not text:
                continue

            start_ms = (sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds) * 1000 + sub.start.milliseconds
            end_ms = (sub.end.hours * 3600 + sub.end.minutes * 60 + sub.end.seconds) * 1000 + sub.end.milliseconds
            sub_tasks.append((i, text, start_ms, end_ms))

        socketio.emit('status_update', {'msg': f'شروع پردازش موازی {len(sub_tasks)} خط زیرنویس...'})

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(process_single_sub, task, video_path, gender_detect, text_lang, audio_lang)
                for task in sub_tasks
            ]
            for _ in futures:
                pass

        shutil.rmtree(temp_dir, ignore_errors=True)
        socketio.emit('processing_finished', {})

    socketio.start_background_task(run_background_process)
    return {"status": "ok"}

if __name__ == '__main__':
    print("سرور فعال شد: http://127.0.0.1:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)