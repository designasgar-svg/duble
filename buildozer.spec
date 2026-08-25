[app]

# مشخصات اصلی برنامه
title = Subtitle Dubber
package.name = subtitledubber
package.domain = org.app

# سورس کد و فرمت فایل‌ها
source.dir = .
source.include_exts = py,html,css,js,png,jpg,ttf,srt

# نسخه برنامه
version = 0.1

# کتابخانه‌های پایتون مورد نیاز
requirements = python3==3.11,kivy,flask,flask-socketio,pysrt,deep-translator,edge-tts,pyjnius
# جهت صفحه
orientation = portrait

# تنظیمات و دسترسی‌های اندروید
fullscreen = 0
android.permissions = INTERNET, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.allow_backup = True

[buildozer]

# سطح لاگ برای نمایش جزئیات خطایابی
log_level = 2
warn_on_root = 1