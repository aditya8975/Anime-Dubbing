"""
AniDub Studio — System Check
Run this before first launch to verify all dependencies.
"""
import sys, shutil, subprocess

print("\n🔍 AniDub Studio — System Check")
print("=" * 40)

ok = True

def check(label, fn):
    global ok
    try:
        result = fn()
        print(f"  ✓ {label}" + (f": {result}" if result else ""))
    except Exception as e:
        print(f"  ✗ {label}: {e}")
        ok = False

def python_ver():
    v = sys.version_info
    assert v >= (3, 8), f"Python 3.8+ required, got {v.major}.{v.minor}"
    return f"Python {v.major}.{v.minor}.{v.micro}"

def ffmpeg_ver():
    for name in ["ffmpeg", "ffprobe"]:
        found = shutil.which(name)
        if not found:
            raise FileNotFoundError(f"{name} not found — run: winget install Gyan.FFmpeg")
    r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    return r.stdout.splitlines()[0] if r.returncode == 0 else "found"

def pkg(name):
    __import__(name.replace("-", "_"))

check("Python",       python_ver)
check("ffmpeg",       ffmpeg_ver)
check("Flask",        lambda: pkg("flask"))
check("Flask-CORS",   lambda: pkg("flask_cors"))
check("Groq",         lambda: pkg("groq"))
check("gTTS",         lambda: pkg("gtts"))
check("pydub",        lambda: pkg("pydub"))
check("python-dotenv",lambda: pkg("dotenv"))

# Optional
print("\n  Optional:")
try:
    import demucs
    print("  ✓ Demucs (vocal separation): available")
except ImportError:
    print("  ℹ  Demucs: not installed — pip install demucs  (optional, enables vocal isolation)")

try:
    import pyttsx3
    print("  ✓ pyttsx3 (offline TTS fallback): available")
except ImportError:
    print("  ℹ  pyttsx3: not installed — pip install pyttsx3  (optional offline fallback)")

print("=" * 40)
if ok:
    print("\n✅ All required checks passed — run: python app.py\n")
else:
    print("\n❌ Some checks failed. Fix the issues above, then re-run this script.\n")
    print("   Install all requirements: pip install -r requirements.txt\n")
    sys.exit(1)