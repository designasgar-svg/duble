import asyncio
from io import BytesIO
import chardet
import edge_tts
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import pysrt

app = Flask(__name__)
app.config["SECRET_KEY"] = "sync_video_srt_secret"
socketio = SocketIO(app, cors_allowed_origins="*")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>پخش‌کننده ویدیو با دوبله هوشمند آنلاین</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        body { font-family: Tahoma, sans-serif; background: #121212; color: #fff; text-align: center; padding: 20px; margin: 0; }
        .container { max-width: 900px; margin: auto; background: #1e1e1e; padding: 20px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.6); }
        .form-group { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
        .form-group div { flex: 1; min-width: 200px; text-align: right; }
        label { display: block; margin-bottom: 5px; font-size: 13px; color: #ccc; }
        input, select, button { width: 100%; padding: 10px; border-radius: 6px; border: 1px solid #333; background: #2a2a2a; color: #fff; box-sizing: border-box; }
        button { background: #007bff; border: none; font-weight: bold; cursor: pointer; transition: 0.2s; }
        button:hover { background: #0056b3; }
        video { width: 100%; max-height: 480px; border-radius: 8px; background: #000; margin-top: 15px; }
        #status { color: #28a745; margin: 10px 0; font-weight: bold; font-size: 14px; }
        #log { background: #000; color: #0f0; padding: 10px; border-radius: 6px; height: 100px; overflow-y: auto; text-align: left; font-family: monospace; font-size: 11px; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <h2>🎬 پخش‌کننده ویدیو همراه با دوبله هوشمند زیرنویس</h2>
        
        <div class="form-group">
            <div>
                <label>۱. انتخاب فایل ویدیو (MP4 / WebM):</label>
                <input type="file" id="videoFile" accept="video/*" onchange="loadVideo(event)">
            </div>
            <div>
                <label>۲. انتخاب فایل زیرنویس (.srt):</label>
                <input type="file" id="srtFile" accept=".srt">
            </div>
            <div>
                <label>۳. گوینده:</label>
                <select id="voice">
                    <option value="ro-RO-EmilNeural">مردانه (Emil Neural)</option>
                    <option value="ro-RO-AlinaNeural">زنانه (Alina Neural)</option>
                </select>
            </div>
        </div>

        <button onclick="startProcessing()">شروع پردازش و همگام‌سازی 🚀</button>

        <div id="status">ویدیو و زیرنویس را انتخاب کنید.</div>

        <!-- پخش‌کننده ویدیو اصلی -->
        <video id="mainVideo" controls></video>
        
        <!-- پخش‌کننده مخفی صدا برای گوینده -->
        <audio id="audioPlayer" style="display:none;"></audio>

        <div id="log">--- وضعیت پردازش صوتی ---</div>
    </div>

    <script>
        const socket = io();
        const video = document.getElementById('mainVideo');
        const audioPlayer = document.getElementById('audioPlayer');
        const logDiv = document.getElementById('log');
        const statusDiv = document.getElementById('status');
        
        let audioChunks = []; // ذخیره همه چانک‌های صوتی بر اساس زمان

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

        socket.on('status', function(data) {
            statusDiv.innerText = data.msg;
            appendLog(data.msg);
        });

        socket.on('audio_chunk', function(data) {
            const blob = new Blob([data.audio], { type: 'audio/mp3' });
            const url = URL.createObjectURL(blob);
            
            audioChunks.push({
                url: url,
                text: data.text,
                start_ms: data.start_ms,
                end_ms: data.end_ms,
                played: false
            });

            appendLog(`[آماده شد] ${data.start_ms}ms تا ${data.end_ms}ms | ${data.text}`);
        });

        // همگام‌سازی مداوم صدا با زمان واقعی ویدیو
        video.ontimeupdate = function() {
            const currentTimeMs = video.currentTime * 1000;

            for (let chunk of audioChunks) {
                // اگر زمان ویدیو به زمان شروع زیرنویس رسیده و هنوز پخش نشده باشد
                if (currentTimeMs >= chunk.start_ms && currentTimeMs <= chunk.end_ms && !chunk.played) {
                    chunk.played = true;
                    audioPlayer.src = chunk.url;
                    audioPlayer.play();
                    statusDiv.innerText = "گویش: " + chunk.text;
                    break;
                }
            }
        };

        // ریست کردن وضعیت پخش صدا در صورت عقب/جلو کردن فیلم (Seek)
        video.onseeking = function() {
            const currentTimeMs = video.currentTime * 1000;
            audioChunks.forEach(chunk => {
                chunk.played = chunk.start_ms < currentTimeMs;
            });
        };

        function startProcessing() {
            const srtInput = document.getElementById('srtFile');
            const voice = document.getElementById('voice').value;

            if (!srtInput.files[0]) {
                alert("لطفاً فایل زیرنویس SRT را انتخاب کنید.");
                return;
            }

            audioChunks = [];
            logDiv.innerHTML = "";

            const reader = new FileReader();
            reader.onload = function(e) {
                socket.emit('start_stream', {
                    srt_data: e.target.result,
                    voice: voice
                });
            };
            reader.readAsArrayBuffer(srtInput.files[0]);
        }
    </script>
</body>
</html>
"""


def parse_srt(file_bytes):
    encoding = chardet.detect(file_bytes)["encoding"] or "utf-8"
    content = file_bytes.decode(encoding, errors="ignore")
    return pysrt.from_string(content)


async def generate_adaptive_audio(text, voice, allowed_duration_ms):
    """ساخت صوت با تنظیم سرعت هوشمند (rate)"""
    words = text.split()
    word_count = len(words)

    if word_count == 0:
        return b""

    # تخمین زمان عادی خواندن (هر کلمه حدود ۳۵۰ میلی‌ثانیه)
    estimated_time_ms = word_count * 350

    # اگر متن از مهلت زمانی زیرنویس طولانی‌تر باشد، سرعت خواندن افزایش می‌یابد
    if estimated_time_ms > allowed_duration_ms and allowed_duration_ms > 0:
        speed_increase = int(
            ((estimated_time_ms - allowed_duration_ms) / allowed_duration_ms)
            * 100
        )
        speed_increase = min(speed_increase, 50)  # حداکثر ۵۰٪ افزایش سرعت
        rate_str = f"+{speed_increase}%"
    else:
        rate_str = "+0%"

    communicate = edge_tts.Communicate(text, voice, rate=rate_str)
    audio_bytes = bytearray()

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes.extend(chunk["data"])

    return bytes(audio_bytes)


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@socketio.on("start_stream")
def handle_stream(data):
    file_bytes = bytes(data["srt_data"])
    voice = data["voice"]

    try:
        subs = parse_srt(file_bytes)
        emit(
            "status",
            {
                "msg": f"زیرنویس دریافت شد ({len(subs)} خط). در حال ساخت صداها..."
            },
        )

        for sub in subs:
            text = sub.text_without_tags.strip()
            if not text:
                continue

            start_ms = (
                sub.start.hours * 3600
                + sub.start.minutes * 60
                + sub.start.seconds
            ) * 1000 + sub.start.milliseconds
            end_ms = (
                sub.end.hours * 3600 + sub.end.minutes * 60 + sub.end.seconds
            ) * 1000 + sub.end.milliseconds

            allowed_duration_ms = end_ms - start_ms

            # ساخت صوت هماهنگ با زمان
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            audio_data = loop.run_until_complete(
                generate_adaptive_audio(text, voice, allowed_duration_ms)
            )
            loop.close()

            if audio_data:
                emit(
                    "audio_chunk",
                    {
                        "audio": audio_data,
                        "text": text,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                    },
                )
                socketio.sleep(0.01)

        emit(
            "status",
            {
                "msg": "تمام صداها تولید شدند. آماده پخش همزمان با ویدیو هستید!"
            },
        )

    except Exception as e:
        emit("status", {"msg": f"خطا: {str(e)}"})


if __name__ == "__main__":
    print("سرور فعال شد: http://127.0.0.1:5000")
    socketio.run(app, port=5000, debug=False)