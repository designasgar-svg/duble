import os
import sys
import shutil
import importlib.util
import subprocess
import re

print("=" * 60)
print("        ANDROID BUILD PREFLIGHT CHECK")
print("=" * 60)

errors = []
warnings = []


def ok(msg):
    print(f"[OK]      {msg}")


def error(msg):
    print(f"[ERROR]   {msg}")
    errors.append(msg)


def warning(msg):
    print(f"[WARNING] {msg}")
    warnings.append(msg)


def check_command(name):
    path = shutil.which(name)
    if path:
        ok(f"{name}: {path}")
        return True
    else:
        error(f"{name} پیدا نشد")
        return False


def check_module(name):
    try:
        spec = importlib.util.find_spec(name)

        if spec is not None:
            ok(f"Python module: {name}")
            return True

        error(f"Python module پیدا نشد: {name}")
        return False

    except Exception as e:
        error(f"{name}: {e}")
        return False


# --------------------------------------------------
# Python
# --------------------------------------------------

print("\n[1] PYTHON")

print("Python version:", sys.version)

if sys.version_info >= (3, 8):
    ok("Python version قابل قبول است")
else:
    error("Python باید حداقل 3.8 باشد")


# --------------------------------------------------
# Build tools
# --------------------------------------------------

print("\n[2] BUILD TOOLS")

check_command("buildozer")
check_command("java")
check_command("javac")
check_command("git")
check_command("cython")


# --------------------------------------------------
# Python packages
# --------------------------------------------------

print("\n[3] PYTHON PACKAGES")

modules = [
    "kivy",
    "flask",
    "flask_socketio",
    "pysrt",
    "deep_translator",
    "edge_tts",
    "jnius",
]

for module in modules:
    check_module(module)


# --------------------------------------------------
# Local project files
# --------------------------------------------------

print("\n[4] PROJECT FILES")

required_files = [
    "main.py",
    "duble.py",
    "buildozer.spec",
]

for filename in required_files:
    if os.path.exists(filename):
        ok(filename)
    else:
        error(f"فایل پیدا نشد: {filename}")


# --------------------------------------------------
# Templates
# --------------------------------------------------

print("\n[5] WEB FILES")

if os.path.exists("templates/index.html"):
    ok("templates/index.html")
elif os.path.exists("index.html"):
    warning("index.html در templates نیست")
else:
    error("index.html پیدا نشد")


# --------------------------------------------------
# Import duble
# --------------------------------------------------

print("\n[6] DUBLE IMPORT TEST")

try:
    import duble
    ok("duble.py با موفقیت import شد")

    if hasattr(duble, "app"):
        ok("duble.app موجود است")
    else:
        error("duble.app پیدا نشد")

    if hasattr(duble, "socketio"):
        ok("duble.socketio موجود است")
    else:
        error("duble.socketio پیدا نشد")

except Exception as e:
    error(f"import duble شکست خورد: {type(e).__name__}: {e}")


# --------------------------------------------------
# Buildozer spec
# --------------------------------------------------

print("\n[7] BUILDOZER SPEC")

spec_file = "buildozer.spec"

if os.path.exists(spec_file):

    text = open(spec_file, "r", encoding="utf-8").read()

    requirements_match = re.search(
        r"^\s*requirements\s*=\s*(.+)$",
        text,
        re.MULTILINE
    )

    if requirements_match:

        requirements = [
            x.strip()
            for x in requirements_match.group(1).split(",")
            if x.strip()
        ]

        print("Requirements:")
        for req in requirements:
            print("   -", req)

        if "kivy" in requirements:
            warning(
                "kivy در requirements است؛ "
                "اگر برنامه WebView است، احتمالاً لازم نیست."
            )

        if "edge-tts" in requirements:
            warning(
                "edge-tts در requirements است؛ "
                "سازگاری آن با python-for-android باید جداگانه بررسی شود."
            )

        if "flask-socketio" in requirements:
            warning(
                "flask-socketio استفاده شده؛ "
                "باید runtime آن روی Android/WebView تست شود."
            )

    else:
        error("خط requirements در buildozer.spec پیدا نشد")

else:
    error("buildozer.spec پیدا نشد")


# --------------------------------------------------
# Android config
# --------------------------------------------------

print("\n[8] ANDROID CONFIG")

if os.path.exists(spec_file):

    if "android.api = 33" in text:
        ok("android.api = 33")

    if "android.minapi = 24" in text:
        ok("android.minapi = 24")

    if "android.ndk = 25b" in text:
        warning(
            "NDK روی 25b قفل شده. "
            "نسخه NDK باید با نسخه python-for-android/Buildozer شما سازگار باشد."
        )

    if "arm64-v8a" in text:
        ok("arm64-v8a فعال است")


# --------------------------------------------------
# Android SDK environment
# --------------------------------------------------

print("\n[9] ANDROID ENVIRONMENT")

for env in [
    "ANDROIDSDK",
    "ANDROIDNDK",
    "ANDROID_HOME",
]:
    value = os.environ.get(env)

    if value:
        ok(f"{env} = {value}")
    else:
        warning(f"{env} تنظیم نشده")


# --------------------------------------------------
# Final result
# --------------------------------------------------

print("\n" + "=" * 60)

if errors:
    print("❌ BUILD فعلاً توصیه نمی‌شود")
    print()
    print(f"تعداد ERROR: {len(errors)}")
    print(f"تعداد WARNING: {len(warnings)}")

    print("\nERROR ها:")
    for e in errors:
        print(" -", e)

else:
    print("✅ خطای واضحی در Preflight پیدا نشد")

    if warnings:
        print()
        print(f"تعداد WARNING: {len(warnings)}")

print("=" * 60)