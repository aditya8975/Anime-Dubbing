# """
# Anime Dubbing Studio — Production Backend v2.1
# =============================================
# Fixes applied over v2.0:
#  1. Cross-platform FFmpeg detection (Windows + Mac + Linux)
#  2. Audio chunking for Groq Whisper 25MB limit (anime episodes ~46MB)
#  3. pydub-based audio assembly (replaces broken ffmpeg filter_complex)
#  4. asyncio.new_event_loop() in threads (Windows ProactorEventLoop fix)
#  5. Flask upload size limit raised to 4GB
#  6. MKV→MP4 re-encode fallback when stream copy fails
#  7. Translation ID matching by position (LLM renumbering protection)
#  8. Empty transcription guard with clear error
#  9. Rate-limited TTS with proper retry/backoff
# 10. Whisper file size guard + automatic chunking
# 11. [FIX v2.1] .env file loading via python-dotenv
# 18. [FIX v2.3] Replaced edge-tts (blocked by ISPs) with gTTS (Google) + pyttsx3 offline chain
# 12. [FIX v2.1] edge-tts retry loop actually retries the call (was sleeping, not retrying)
# 13. [FIX v2.1] edge-tts error detection fixed (aiohttp errors, not "rate_limit" string)
# 14. [FIX v2.1] Jitter added to retry backoff to avoid thundering herd
# 15. [FIX v2.1] Per-segment failure logged clearly; partial success allowed
# 16. [FIX v2.1] edge-tts network errors caught broadly and retried correctly
# 17. [FIX v2.1] Groq TTS also retries on transient errors, not just rate limits
# """

# import os
# import sys
# import uuid
# import json
# import time
# import random
# import asyncio
# import shutil
# import subprocess
# import threading
# import io
# from pathlib import Path
# from flask import Flask, request, jsonify, send_file, Response
# from flask_cors import CORS
# from groq import Groq
# from pydub import AudioSegment

# # ── Load .env if present ───────────────────────────────────────────────────────
# try:
#     from dotenv import load_dotenv
#     load_dotenv(Path(__file__).parent / ".env")
# except ImportError:
#     pass  # python-dotenv not installed — rely on real env vars

# # ── App Setup ──────────────────────────────────────────────────────────────────
# app = Flask(__name__)
# CORS(app)
# app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB upload limit

# BASE_DIR   = Path(__file__).parent
# UPLOAD_DIR = BASE_DIR / "uploads"
# OUTPUT_DIR = BASE_DIR / "outputs"
# TEMP_DIR   = BASE_DIR / "temp"

# for d in [UPLOAD_DIR, OUTPUT_DIR, TEMP_DIR]:
#     d.mkdir(exist_ok=True)

# # ── FFmpeg Detection ───────────────────────────────────────────────────────────
# def _find_binary(name: str) -> str:
#     """Find ffmpeg/ffprobe on PATH or common Windows install dirs."""
#     # 1. PATH
#     found = shutil.which(name)
#     if found:
#         return found

#     # 2. Windows common locations
#     if sys.platform == "win32":
#         candidates = [
#             rf"C:\ffmpeg\bin\{name}.exe",
#             rf"C:\Program Files\ffmpeg\bin\{name}.exe",
#             rf"C:\Program Files (x86)\ffmpeg\bin\{name}.exe",
#             rf"C:\ProgramData\chocolatey\bin\{name}.exe",
#             os.path.join(os.path.expanduser("~"), rf"scoop\apps\ffmpeg\current\bin\{name}.exe"),
#         ]
#         for p in candidates:
#             if os.path.exists(p):
#                 return p

#     # 3. Bundled next to script
#     local = BASE_DIR / (name + (".exe" if sys.platform == "win32" else ""))
#     if local.exists():
#         return str(local)

#     raise FileNotFoundError(
#         f"'{name}' not found. Install FFmpeg:\n"
#         "  Mac:     brew install ffmpeg\n"
#         "  Ubuntu:  sudo apt install ffmpeg\n"
#         "  Windows: winget install ffmpeg   (then restart terminal)"
#     )


# # Resolve once at startup — fail fast with a clear message
# try:
#     FFMPEG  = _find_binary("ffmpeg")
#     FFPROBE = _find_binary("ffprobe")
#     print(f"[startup] ffmpeg  : {FFMPEG}")
#     print(f"[startup] ffprobe : {FFPROBE}")
# except FileNotFoundError as e:
#     print(f"\n{'='*60}\n❌ STARTUP FAILED\n{e}\n{'='*60}\n")
#     sys.exit(1)

# # ── Job Store ──────────────────────────────────────────────────────────────────
# jobs: dict[str, dict] = {}
# jobs_lock = threading.Lock()

# def job_update(job_id: str, **kwargs):
#     with jobs_lock:
#         if job_id in jobs:
#             jobs[job_id].update(kwargs)

# def job_log(job_id: str, msg: str):
#     with jobs_lock:
#         if job_id in jobs:
#             jobs[job_id].setdefault("logs", []).append(msg)
#     print(f"[{job_id[:8]}] {msg}")

# # ── Async runner for threads ───────────────────────────────────────────────────
# def run_async(coro):
#     """Run a coroutine from any thread (safe on Windows ProactorEventLoop)."""
#     loop = asyncio.new_event_loop()
#     try:
#         return loop.run_until_complete(coro)
#     finally:
#         loop.close()

# # ── Language Maps ──────────────────────────────────────────────────────────────
# LANG_TO_CODE = {
#     "Japanese": "ja", "Korean": "ko", "Chinese": "zh",
#     "English": "en",  "Hindi": "hi",  "Spanish": "es",
#     "French": "fr",   "German": "de", "Portuguese": "pt",
#     "Arabic": "ar",   "Thai": "th",   "Vietnamese": "vi",
#     "Indonesian": "id","Tamil": "ta", "Telugu": "te",
#     "Bengali": "bn",  "Urdu": "ur",   "Turkish": "tr",
#     "Russian": "ru",  "Italian": "it","Dutch": "nl",
# }

# # ── Voice Maps ─────────────────────────────────────────────────────────────────
# # Groq Orpheus voices (English only — replaces deprecated playai-tts)
# # Model: canopylabs/orpheus-v1-english
# # Confirmed voices: austin, daniel, troy, autumn, diana, hannah
# GROQ_VOICES = {
#     "male_hero":     "troy",
#     "male_cool":     "austin",
#     "male_villain":  "daniel",
#     "male_wise":     "daniel",
#     "female_hero":   "diana",
#     "female_gentle": "autumn",
#     "female_villain":"hannah",
#     "narrator":      "austin",
# }

# # edge-tts voices for multilingual (Hindi, Spanish, etc.)
# EDGE_VOICES = {
#     "hi": {"male_hero":"hi-IN-MadhurNeural","male_cool":"hi-IN-MadhurNeural",
#            "male_villain":"hi-IN-MadhurNeural","male_wise":"hi-IN-MadhurNeural",
#            "female_hero":"hi-IN-SwaraNeural","female_gentle":"hi-IN-SwaraNeural",
#            "female_villain":"hi-IN-SwaraNeural","narrator":"hi-IN-MadhurNeural","default":"hi-IN-SwaraNeural"},
#     "en": {"male_hero":"en-US-GuyNeural","male_cool":"en-US-ChristopherNeural",
#            "female_hero":"en-US-JennyNeural","female_gentle":"en-US-AriaNeural",
#            "narrator":"en-US-GuyNeural","default":"en-US-AriaNeural"},
#     "es": {"male_hero":"es-ES-AlvaroNeural","female_hero":"es-ES-ElviraNeural","default":"es-ES-AlvaroNeural"},
#     "pt": {"male_hero":"pt-BR-AntonioNeural","female_hero":"pt-BR-FranciscaNeural","default":"pt-BR-AntonioNeural"},
#     "fr": {"male_hero":"fr-FR-HenriNeural","female_hero":"fr-FR-DeniseNeural","default":"fr-FR-HenriNeural"},
#     "de": {"male_hero":"de-DE-ConradNeural","female_hero":"de-DE-KatjaNeural","default":"de-DE-ConradNeural"},
#     "ko": {"male_hero":"ko-KR-InJoonNeural","female_hero":"ko-KR-SunHiNeural","default":"ko-KR-InJoonNeural"},
#     "ja": {"male_hero":"ja-JP-KeitaNeural","female_hero":"ja-JP-NanamiNeural","default":"ja-JP-KeitaNeural"},
#     "zh": {"male_hero":"zh-CN-YunxiNeural","female_hero":"zh-CN-XiaoxiaoNeural","default":"zh-CN-YunxiNeural"},
#     "ar": {"male_hero":"ar-SA-HamedNeural","female_hero":"ar-SA-ZariyahNeural","default":"ar-SA-HamedNeural"},
#     "tr": {"male_hero":"tr-TR-AhmetNeural","female_hero":"tr-TR-EmelNeural","default":"tr-TR-AhmetNeural"},
#     "ru": {"male_hero":"ru-RU-DmitryNeural","female_hero":"ru-RU-SvetlanaNeural","default":"ru-RU-DmitryNeural"},
#     "it": {"male_hero":"it-IT-DiegoNeural","female_hero":"it-IT-IsabellaNeural","default":"it-IT-DiegoNeural"},
#     "id": {"male_hero":"id-ID-ArdiNeural","female_hero":"id-ID-GadisNeural","default":"id-ID-ArdiNeural"},
#     "th": {"male_hero":"th-TH-NiwatNeural","female_hero":"th-TH-PremwadeeNeural","default":"th-TH-NiwatNeural"},
#     "vi": {"male_hero":"vi-VN-NamMinhNeural","female_hero":"vi-VN-HoaiMyNeural","default":"vi-VN-NamMinhNeural"},
#     "ta": {"default":"ta-IN-ValluvarNeural"},
#     "bn": {"default":"bn-IN-BashkarNeural"},
#     "nl": {"default":"nl-NL-MaartenNeural","female_hero":"nl-NL-ColetteNeural"},
# }

# def get_edge_voice(lang_code: str, profile: str) -> str:
#     vmap = EDGE_VOICES.get(lang_code, {})
#     return vmap.get(profile, vmap.get("default", "en-US-AriaNeural"))


# # ═══════════════════════════════════════════════════════════════════════════════
# #  STEP 1 — EXTRACT AUDIO
# # ═══════════════════════════════════════════════════════════════════════════════

# def step_extract_audio(job_id: str, video_path: Path) -> Path:
#     """Extract 16kHz mono WAV from video. Always succeeds or raises with clear error."""
#     job_log(job_id, "🎬 Extracting audio from video...")
#     audio_path = TEMP_DIR / f"{job_id}_audio.wav"

#     cmd = [
#         FFMPEG, "-y",
#         "-i", str(video_path),
#         "-vn",                   # no video
#         "-acodec", "pcm_s16le",  # 16-bit PCM
#         "-ar", "16000",          # 16kHz for Whisper
#         "-ac", "1",              # mono
#         str(audio_path)
#     ]
#     result = subprocess.run(cmd, capture_output=True, text=True)
#     if result.returncode != 0 or not audio_path.exists():
#         raise RuntimeError(
#             f"FFmpeg audio extraction failed (code {result.returncode}).\n"
#             f"Stderr: {result.stderr[-1000:]}"
#         )

#     size_mb = audio_path.stat().st_size / (1024 * 1024)
#     job_log(job_id, f"✅ Audio extracted: {size_mb:.1f} MB")
#     return audio_path


# # ═══════════════════════════════════════════════════════════════════════════════
# #  STEP 2 — TRANSCRIBE (with auto-chunking for >25MB files)
# # ═══════════════════════════════════════════════════════════════════════════════

# WHISPER_LIMIT_MB = 24.0   # Groq limit is 25MB, use 24MB to be safe
# CHUNK_SECONDS    = 270    # 4.5-minute chunks (~9MB each at 16kHz mono)

# def _transcribe_single(client: Groq, audio_path: Path, lang_code: str) -> list[dict]:
#     """Transcribe one audio file (must be < 25MB). Returns segment list."""
#     with open(audio_path, "rb") as f:
#         resp = client.audio.transcriptions.create(
#             file=(audio_path.name, f, "audio/wav"),
#             model="whisper-large-v3-turbo",
#             language=lang_code,
#             response_format="verbose_json",
#             timestamp_granularities=["segment"],
#         )

#     segs = []
#     raw = getattr(resp, "segments", []) or []
#     for s in raw:
#         text = str(getattr(s, "text", "")).strip()
#         if text:
#             segs.append({
#                 "id":    len(segs),
#                 "start": float(getattr(s, "start", 0)),
#                 "end":   float(getattr(s, "end",   0)),
#                 "text":  text,
#             })

#     # Fallback if no segments but text exists
#     if not segs and getattr(resp, "text", "").strip():
#         segs = [{"id": 0, "start": 0.0, "end": 9999.0, "text": resp.text.strip()}]

#     return segs


# def step_transcribe(job_id: str, audio_path: Path, src_lang: str, api_key: str) -> list[dict]:
#     """Transcribe audio. Auto-chunks files > 24MB to respect Groq limit."""
#     lang_code = LANG_TO_CODE.get(src_lang, "ja")
#     client    = Groq(api_key=api_key)

#     size_mb = audio_path.stat().st_size / (1024 * 1024)
#     job_log(job_id, f"🎤 Transcribing ({src_lang}, {size_mb:.1f} MB) with Groq Whisper...")

#     if size_mb <= WHISPER_LIMIT_MB:
#         # Small enough — send directly
#         segs = _transcribe_single(client, audio_path, lang_code)
#     else:
#         # Split into chunks, transcribe each, offset timestamps
#         job_log(job_id, f"   File is {size_mb:.1f} MB → chunking into {CHUNK_SECONDS}s pieces...")
#         chunk_pattern = TEMP_DIR / f"{job_id}_chunk_%04d.wav"
#         r = subprocess.run([
#             FFMPEG, "-y", "-i", str(audio_path),
#             "-f", "segment",
#             "-segment_time", str(CHUNK_SECONDS),
#             "-acodec", "pcm_s16le",
#             str(chunk_pattern)
#         ], capture_output=True, text=True)
#         if r.returncode != 0:
#             raise RuntimeError(f"Audio chunking failed: {r.stderr[-500:]}")

#         chunk_files = sorted(TEMP_DIR.glob(f"{job_id}_chunk_*.wav"))
#         if not chunk_files:
#             raise RuntimeError("Audio chunking produced no files")

#         job_log(job_id, f"   Transcribing {len(chunk_files)} chunks...")
#         segs = []
#         chunk_offset = 0.0

#         for i, chunk in enumerate(chunk_files):
#             job_log(job_id, f"   Chunk {i+1}/{len(chunk_files)}...")
#             chunk_segs = _transcribe_single(client, chunk, lang_code)
#             # Offset timestamps by chunk start time
#             for s in chunk_segs:
#                 s["id"]    = len(segs)
#                 s["start"] += chunk_offset
#                 s["end"]   += chunk_offset
#                 segs.append(s)
#             # Get actual chunk duration for next offset
#             probe = subprocess.run([
#                 FFPROBE, "-v", "quiet", "-print_format", "json",
#                 "-show_format", str(chunk)
#             ], capture_output=True, text=True)
#             try:
#                 chunk_offset += float(json.loads(probe.stdout)["format"]["duration"])
#             except Exception:
#                 chunk_offset += CHUNK_SECONDS
#             try:
#                 chunk.unlink()
#             except Exception:
#                 pass
#             time.sleep(0.3)  # brief pause between API calls

#     if not segs:
#         raise RuntimeError(
#             "Transcription returned no text. Check that the video has clear audio "
#             "and the correct source language is selected."
#         )

#     job_log(job_id, f"✅ Transcribed {len(segs)} dialogue segments")
#     return segs


# # ═══════════════════════════════════════════════════════════════════════════════
# #  STEP 3 — TRANSLATE
# # ═══════════════════════════════════════════════════════════════════════════════

# STYLE_GUIDE = {
#     "natural":   "Match approximate speech duration. Use natural spoken language. Prioritize lip-sync — prefer shorter phrasings that fit the original timing.",
#     "literal":   "Stay as close to the original meaning as possible. Minimal adaptation. Direct translation.",
#     "localized": "Culturally adapt references, idioms, and honorifics for the target audience. Make it feel native.",
#     "broadcast": "Formal, clear broadcast tone. Neutral enunciation. No slang or contractions.",
# }

# def step_translate(job_id: str, segments: list[dict], src_lang: str,
#                    tgt_lang: str, style: str, api_key: str) -> list[dict]:
#     """Translate segments with Groq LLaMA. Matches output back to input by position."""
#     job_log(job_id, f"🌐 Translating {src_lang} → {tgt_lang} [{style}]...")
#     client     = Groq(api_key=api_key)
#     guide      = STYLE_GUIDE.get(style, STYLE_GUIDE["natural"])
#     batch_size = 25  # smaller batches = more reliable JSON
#     results    = []

#     total_batches = (len(segments) + batch_size - 1) // batch_size

#     for bi in range(0, len(segments), batch_size):
#         batch = segments[bi : bi + batch_size]
#         bn    = bi // batch_size + 1
#         job_log(job_id, f"   Batch {bn}/{total_batches} ({len(batch)} lines)...")

#         # Minimal input — only what the model needs
#         input_data = [{"idx": i, "text": s["text"]} for i, s in enumerate(batch)]

#         prompt = (
#             f"Translate the following {src_lang} anime dialogue to {tgt_lang}.\n\n"
#             f"Style: {guide}\n\n"
#             "Rules:\n"
#             "- Return ONLY a JSON array. No markdown, no explanation.\n"
#             "- Same number of items as input, same order.\n"
#             "- Each item: {\"idx\": <same as input>, \"translated\": \"<translation>\"}\n"
#             "- Preserve character voice, emotions, and energy.\n\n"
#             f"Input:\n{json.dumps(input_data, ensure_ascii=False)}\n\n"
#             "JSON array:"
#         )

#         translated_batch = None
#         for attempt in range(4):
#             try:
#                 resp = client.chat.completions.create(
#                     model="llama-3.3-70b-versatile",
#                     messages=[
#                         {"role": "system", "content":
#                             f"You are an expert anime dubbing translator. "
#                             f"Translate {src_lang} → {tgt_lang}. "
#                             "Return only valid JSON arrays."},
#                         {"role": "user", "content": prompt}
#                     ],
#                     temperature=0.25,
#                     max_tokens=4096,
#                 )
#                 raw = resp.choices[0].message.content.strip()
#                 # Strip markdown code fences if present
#                 if "```" in raw:
#                     raw = raw.split("```")[1]
#                     if raw.startswith("json"):
#                         raw = raw[4:]
#                 raw = raw.strip().rstrip(",")
#                 # Extract JSON array even if there's leading/trailing noise
#                 start = raw.find("[")
#                 end   = raw.rfind("]") + 1
#                 if start >= 0 and end > start:
#                     raw = raw[start:end]
#                 parsed = json.loads(raw)
#                 if isinstance(parsed, list):
#                     translated_batch = parsed
#                     break
#             except Exception as e:
#                 if attempt < 3:
#                     time.sleep(1.5 * (attempt + 1))
#                 else:
#                     job_log(job_id, f"⚠️ Batch {bn} translation failed: {e} — using original text")

#         # Map results back to segments by position (idx), not by LLM-assigned id
#         for i, seg in enumerate(batch):
#             translation = seg["text"]  # fallback
#             if translated_batch:
#                 # Match by idx field (position-based, immune to LLM renumbering)
#                 for item in translated_batch:
#                     if isinstance(item, dict) and item.get("idx") == i:
#                         t = str(item.get("translated", "")).strip()
#                         if t:
#                             translation = t
#                         break
#                 else:
#                     # Fallback: use position if idx matching fails
#                     if i < len(translated_batch):
#                         t = str(translated_batch[i].get("translated", "")).strip()
#                         if t:
#                             translation = t

#             results.append({
#                 **seg,
#                 "translated": translation,
#             })

#     job_log(job_id, f"✅ Translation complete ({len(results)} segments)")
#     return results


# # ═══════════════════════════════════════════════════════════════════════════════
# #  STEP 4 — TTS GENERATION  (v2.1: fixed retry logic)
# # ═══════════════════════════════════════════════════════════════════════════════

# # ── TTS Engine Chain: gTTS (Google) → pyttsx3 (offline) ─────────────────────
# # edge-tts was replaced because speech.platform.bing.com is blocked by many
# # ISPs (especially in India). gTTS uses Google's servers (never blocked),
# # and pyttsx3 works 100% offline as a last resort.

# # Lang code map for gTTS (uses BCP-47 like "hi", "es", "en" — mostly same)
# GTTS_LANG_MAP = {
#     "hi": "hi", "en": "en", "es": "es", "pt": "pt", "fr": "fr",
#     "de": "de", "ko": "ko", "ja": "ja", "zh": "zh", "ar": "ar",
#     "tr": "tr", "ru": "ru", "it": "it", "id": "id", "th": "th",
#     "vi": "vi", "nl": "nl", "ta": "ta", "bn": "bn", "te": "te",
#     "ur": "ur",
# }

# def _tts_gtts(text: str, lang_code: str, out_path: Path, slow: bool = False) -> bool:
#     """Google TTS via gTTS. Fast, free, works on any network. Returns True on success."""
#     try:
#         from gtts import gTTS
#         tts = gTTS(text=text, lang=GTTS_LANG_MAP.get(lang_code, "en"), slow=slow)
#         tts.save(str(out_path))
#         return out_path.exists() and out_path.stat().st_size > 512
#     except Exception:
#         return False


# def _tts_pyttsx3(text: str, out_path: Path) -> bool:
#     """Offline TTS via pyttsx3. Works with zero internet. English-only quality."""
#     try:
#         import pyttsx3, wave, struct
#         engine = pyttsx3.init()
#         engine.setProperty("rate", 165)
#         # pyttsx3 can only save to .wav
#         wav_path = out_path.with_suffix(".wav")
#         engine.save_to_file(text, str(wav_path))
#         engine.runAndWait()
#         if wav_path.exists() and wav_path.stat().st_size > 512:
#             # Convert WAV → MP3 via pydub
#             AudioSegment.from_wav(str(wav_path)).export(str(out_path), format="mp3")
#             wav_path.unlink(missing_ok=True)
#             return out_path.exists() and out_path.stat().st_size > 512
#         return False
#     except Exception:
#         return False


# def _tts_multilingual(job_id: str, seg_id: int, text: str, lang_code: str,
#                        out_path: Path, max_attempts: int = 3) -> bool:
#     """
#     TTS engine chain for all languages (including English fallback):
#       1. gTTS  — Google TTS (free, supports 30+ languages, needs internet)
#       2. pyttsx3 — system TTS (offline, English only, last resort)
#     Returns True on success.
#     """
#     # Try gTTS first (works on all networks that allow Google)
#     for attempt in range(max_attempts):
#         try:
#             if out_path.exists():
#                 out_path.unlink()
#         except Exception:
#             pass
#         if _tts_gtts(text, lang_code, out_path):
#             return True
#         if attempt < max_attempts - 1:
#             wait = 1.5 * (attempt + 1) + random.uniform(0, 0.5)
#             job_log(job_id, f"   Seg {seg_id}: gTTS attempt {attempt+1}/{max_attempts} failed, retrying in {wait:.1f}s...")
#             time.sleep(wait)

#     job_log(job_id, f"   Seg {seg_id}: gTTS failed — trying offline pyttsx3 (English only)...")

#     # Last resort: pyttsx3 offline (English only, robotic but functional)
#     offline_path = out_path.with_stem(out_path.stem + "_offline")
#     if _tts_pyttsx3(text, offline_path):
#         try:
#             offline_path.rename(out_path)
#         except Exception:
#             pass
#         if out_path.exists():
#             job_log(job_id, f"   Seg {seg_id}: pyttsx3 offline TTS succeeded (English only)")
#             return True

#     return False


# # Keep this alias so English fallback path still works
# def _tts_edge_with_retry(job_id: str, seg_id: int, text: str, voice: str,
#                           rate_str: str, out_path: Path, max_attempts: int = 3) -> bool:
#     """Compatibility shim — routes to gTTS chain (edge-tts was network-blocked)."""
#     lang_code = "en"  # this path is only called for English fallback
#     return _tts_multilingual(job_id, seg_id, text, lang_code, out_path, max_attempts)


# def _speed_to_edge_rate(speed: float) -> str:
#     """Convert 0.5–2.0 speed to edge-tts rate string like '+20%' or '-15%'."""
#     pct = int((speed - 1.0) * 100)
#     if pct >= 0:
#         return f"+{pct}%"
#     return f"{pct}%"


# def step_generate_tts(job_id: str, translated: list[dict], tgt_lang: str,
#                       voice_profile: str, speed: float, api_key: str) -> list[dict]:
#     """
#     Generate TTS audio for each segment. Adds 'audio_path' to each segment dict.

#     FIX v2.1:
#     - edge-tts retry now actually re-calls the TTS API (not just sleep-and-fail)
#     - Groq TTS also retries with backoff+jitter on any transient error
#     - Per-segment failures are logged individually; partial success is allowed
#     - Full failure raises a clear error with segment count
#     """
#     lang_code    = LANG_TO_CODE.get(tgt_lang, "en")
#     use_groq     = (lang_code == "en")  # Groq Orpheus for English, edge-tts for everything else
#     edge_rate    = _speed_to_edge_rate(speed)
#     client       = Groq(api_key=api_key) if use_groq else None
#     groq_voice   = GROQ_VOICES.get(voice_profile, "leo")
#     edge_voice   = get_edge_voice(lang_code, voice_profile)

#     engine_name = "Groq Orpheus" if use_groq else f"gTTS/Google ({lang_code})"
#     job_log(job_id, f"🔊 Generating TTS [{tgt_lang} / {voice_profile}] via {engine_name} ...")

#     ok_count   = 0
#     fail_count = 0

#     for seg in translated:
#         text = seg.get("translated", seg.get("text", "")).strip()
#         if not text:
#             seg["audio_path"] = None
#             continue

#         ext      = ".wav" if use_groq else ".mp3"
#         out_path = TEMP_DIR / f"{job_id}_seg_{seg['id']:05d}{ext}"
#         success  = False

#         if use_groq:
#             # ── Groq Orpheus (English) with automatic edge-tts fallback ───
#             # Orpheus needs a paid Groq account. On 400/403 errors we
#             # immediately fall back to edge-tts so free-tier users still work.
#             groq_failed_permanently = False
#             for attempt in range(3):
#                 try:
#                     if out_path.exists():
#                         out_path.unlink()
#                     resp = client.audio.speech.create(
#                         model="canopylabs/orpheus-v1-english",
#                         input=text,
#                         voice=groq_voice,
#                         response_format="wav",
#                     )
#                     resp.stream_to_file(str(out_path))

#                     if out_path.exists() and out_path.stat().st_size > 512:
#                         success = True
#                         break
#                     else:
#                         job_log(job_id, f"   Seg {seg['id']}: Groq wrote empty file (attempt {attempt+1}/3)")

#                 except Exception as e:
#                     err_msg = str(e)
#                     is_permanent = any(c in err_msg for c in ["400", "401", "403", "decommission", "not found", "not available", "not supported"])
#                     is_rate_limit = "rate_limit" in err_msg.lower() or "429" in err_msg
#                     if is_permanent:
#                         job_log(job_id, f"   Seg {seg['id']}: Groq Orpheus unavailable — falling back to edge-tts")
#                         job_log(job_id, f"   Reason: {err_msg[:120]}")
#                         groq_failed_permanently = True
#                         break
#                     if attempt < 2:
#                         wait = min(3.0 * (2 ** attempt) + random.uniform(0, 1.0), 30.0)
#                         if is_rate_limit:
#                             job_log(job_id, f"   Seg {seg['id']}: Groq rate limited — waiting {wait:.1f}s...")
#                         else:
#                             job_log(job_id, f"   Seg {seg['id']}: Groq error (attempt {attempt+1}/3): {err_msg[:80]}")
#                         time.sleep(wait)
#                     else:
#                         job_log(job_id, f"   Seg {seg['id']}: Groq exhausted retries — falling back to edge-tts")
#                         groq_failed_permanently = True

#             # Auto-fallback: use edge-tts English voice if Groq Orpheus failed
#             if not success and groq_failed_permanently:
#                 en_voice = get_edge_voice("en", voice_profile)
#                 fb_path = TEMP_DIR / f"{job_id}_seg_{seg['id']:05d}_fb.mp3"
#                 if _tts_edge_with_retry(job_id, seg["id"], text, en_voice, edge_rate, fb_path):
#                     out_path = fb_path
#                     success = True
#                     job_log(job_id, f"   Seg {seg['id']}: edge-tts English fallback succeeded ✅")

#         else:
#             # ── gTTS → pyttsx3 chain (all non-English languages) ──────────
#             success = _tts_multilingual(
#                 job_id=job_id,
#                 seg_id=seg["id"],
#                 text=text,
#                 lang_code=lang_code,
#                 out_path=out_path,
#                 max_attempts=3,
#             )
#             if not success:
#                 job_log(job_id, f"⚠️ Seg {seg['id']}: all TTS engines failed for this segment")

#         if success:
#             seg["audio_path"] = str(out_path)
#             ok_count += 1
#         else:
#             seg["audio_path"] = None
#             fail_count += 1

#     job_log(job_id, f"✅ TTS done: {ok_count} OK, {fail_count} failed")

#     if ok_count == 0:
#         raise RuntimeError(
#             f"TTS generation failed for ALL {fail_count} segments.\n"
#             f"Engine: {engine_name}\n"
#             "Possible causes:\n"
#             "  • No internet connection\n"
#             "  • edge-tts: Microsoft servers temporarily unavailable\n"
#             "  • Groq: invalid API key — check https://console.groq.com\n"
#             "  • Groq Orpheus model not available on your plan\n"
#             "  • Groq: account quota exhausted"
#         )

#     if fail_count > 0:
#         job_log(job_id, f"⚠️ {fail_count} segments will be silent in the final video")

#     return translated


# # ═══════════════════════════════════════════════════════════════════════════════
# #  STEP 5 — ASSEMBLE DUBBED AUDIO TRACK (pydub, no filter_complex)
# # ═══════════════════════════════════════════════════════════════════════════════

# def step_build_dubbed_audio(job_id: str, segments: list[dict], total_duration: float) -> Path:
#     """
#     Place each TTS clip at its exact timestamp using pydub overlay.
#     Avoids the ffmpeg filter_complex approach which:
#       - Breaks on Windows (path issues, command-line length)
#       - Fails with many segments (amix input limit)
#       - Requires a huge silence base track
#     """
#     job_log(job_id, "🎵 Assembling dubbed audio track...")

#     valid = [(s, s["audio_path"]) for s in segments if s.get("audio_path")]
#     if not valid:
#         raise RuntimeError("No TTS audio generated — nothing to assemble")

#     # Duration of the track in ms (add 5s buffer)
#     track_ms = int((total_duration + 5.0) * 1000)

#     # Build the track: start with silence, overlay each clip at its timestamp
#     track = AudioSegment.silent(duration=track_ms, frame_rate=44100)

#     for seg, apath in valid:
#         try:
#             clip = AudioSegment.from_file(apath)  # handles both .wav (Orpheus) and .mp3 (edge-tts)
#             pos_ms = int(seg["start"] * 1000)
#             # Clamp to track length
#             if pos_ms < track_ms:
#                 track = track.overlay(clip, position=pos_ms)
#         except Exception as e:
#             job_log(job_id, f"⚠️ Skipping seg {seg['id']} in mix: {e}")

#     # Export assembled track
#     out_path = TEMP_DIR / f"{job_id}_dubbed_track.mp3"
#     track.export(str(out_path), format="mp3", bitrate="192k")

#     size_kb = out_path.stat().st_size // 1024
#     job_log(job_id, f"✅ Audio track assembled: {size_kb} KB")
#     return out_path


# # ═══════════════════════════════════════════════════════════════════════════════
# #  STEP 6 — MUX DUBBED AUDIO INTO VIDEO
# # ═══════════════════════════════════════════════════════════════════════════════

# def step_mux_video(job_id: str, video_path: Path, dubbed_audio: Path,
#                    orig_vol: float) -> Path:
#     """
#     Merge dubbed audio into video.
#     Tries stream-copy first (fast). Falls back to libx264 re-encode for
#     MKV/incompatible containers — handles HEVC, VP9, AV1 in MP4, etc.
#     """
#     job_log(job_id, f"📼 Muxing into final video (original mix: {orig_vol:.0%})...")
#     out_path = OUTPUT_DIR / f"{job_id}_dubbed.mp4"

#     def _build_cmd(reencode: bool) -> list[str]:
#         video_codec = ["libx264", "-preset", "fast", "-crf", "20"] if reencode else ["copy"]
#         if orig_vol > 0.01:
#             audio_filter = (
#                 f"[0:a:0]volume={orig_vol}[orig];"
#                 f"[1:a:0]volume=1.0[dub];"
#                 f"[orig][dub]amix=inputs=2:duration=first:normalize=0[out]"
#             )
#             return [
#                 FFMPEG, "-y",
#                 "-i", str(video_path),
#                 "-i", str(dubbed_audio),
#                 "-filter_complex", audio_filter,
#                 "-map", "0:v:0",
#                 "-map", "[out]",
#                 "-c:v", *video_codec,
#                 "-c:a", "aac", "-b:a", "192k",
#                 "-movflags", "+faststart",
#                 "-shortest",
#                 str(out_path),
#             ]
#         else:
#             return [
#                 FFMPEG, "-y",
#                 "-i", str(video_path),
#                 "-i", str(dubbed_audio),
#                 "-map", "0:v:0",
#                 "-map", "1:a:0",
#                 "-c:v", *video_codec,
#                 "-c:a", "aac", "-b:a", "192k",
#                 "-movflags", "+faststart",
#                 "-shortest",
#                 str(out_path),
#             ]

#     # Attempt 1: stream copy (fast)
#     r = subprocess.run(_build_cmd(reencode=False), capture_output=True, text=True)
#     if r.returncode != 0 or not out_path.exists():
#         job_log(job_id, "   Stream copy failed — re-encoding video (slower)...")
#         if out_path.exists():
#             out_path.unlink()
#         # Attempt 2: re-encode with libx264 (handles any container/codec)
#         r2 = subprocess.run(_build_cmd(reencode=True), capture_output=True, text=True)
#         if r2.returncode != 0 or not out_path.exists():
#             raise RuntimeError(
#                 f"FFmpeg mux failed (both copy and re-encode).\n"
#                 f"Last error: {r2.stderr[-1000:]}"
#             )

#     size_mb = out_path.stat().st_size / (1024 * 1024)
#     job_log(job_id, f"✅ Final video: {out_path.name} ({size_mb:.1f} MB)")
#     return out_path


# # ═══════════════════════════════════════════════════════════════════════════════
# #  VIDEO DURATION
# # ═══════════════════════════════════════════════════════════════════════════════

# def get_video_duration(video_path: Path) -> float:
#     r = subprocess.run([
#         FFPROBE, "-v", "quiet", "-print_format", "json",
#         "-show_format", str(video_path)
#     ], capture_output=True, text=True)
#     try:
#         return float(json.loads(r.stdout)["format"]["duration"])
#     except Exception:
#         return 1500.0  # safe fallback: 25 min


# # ═══════════════════════════════════════════════════════════════════════════════
# #  FULL PIPELINE
# # ═══════════════════════════════════════════════════════════════════════════════

# def run_pipeline(job_id: str, video_path: Path, params: dict):
#     """Run all steps sequentially in a background thread. Updates job store throughout."""
#     api_key  = params["api_key"]
#     src_lang = params["src_lang"]
#     tgt_lang = params["tgt_lang"]
#     style    = params["style"]
#     voice    = params["voice"]
#     speed    = float(params.get("speed", 1.0))
#     orig_vol = float(params.get("original_volume", 0.0))

#     temp_files = []  # track for cleanup

#     try:
#         job_update(job_id, status="running", progress=3)

#         # ── Step 1: Extract audio ──────────────────────────────────────────────
#         audio_path = step_extract_audio(job_id, video_path)
#         temp_files.append(audio_path)
#         job_update(job_id, progress=12)

#         total_dur = get_video_duration(video_path)

#         # ── Step 2: Transcribe ────────────────────────────────────────────────
#         segments = step_transcribe(job_id, audio_path, src_lang, api_key)
#         job_update(job_id, progress=30, segments=segments)

#         # ── Step 3: Translate ─────────────────────────────────────────────────
#         translated = step_translate(job_id, segments, src_lang, tgt_lang, style, api_key)
#         job_update(job_id, progress=50, translated=translated)

#         # ── Step 4: TTS ───────────────────────────────────────────────────────
#         tts_done = step_generate_tts(job_id, translated, tgt_lang, voice, speed, api_key)
#         for seg in tts_done:
#             if seg.get("audio_path"):
#                 temp_files.append(Path(seg["audio_path"]))
#         job_update(job_id, progress=75)

#         # ── Step 5: Assemble audio track ──────────────────────────────────────
#         dubbed_audio = step_build_dubbed_audio(job_id, tts_done, total_dur)
#         temp_files.append(dubbed_audio)
#         job_update(job_id, progress=88)

#         # ── Step 6: Mux video ─────────────────────────────────────────────────
#         final_video = step_mux_video(job_id, video_path, dubbed_audio, orig_vol)
#         job_update(job_id, progress=100)

#         job_update(job_id, status="done",
#                    output_file=final_video.name,
#                    output_size=final_video.stat().st_size)
#         job_log(job_id, f"🎉 Done! {final_video.name}")

#     except Exception as e:
#         import traceback
#         tb = traceback.format_exc()
#         job_log(job_id, f"❌ Pipeline failed: {e}")
#         print(f"[{job_id[:8]}] TRACEBACK:\n{tb}")
#         job_update(job_id, status="error", error=str(e))

#     finally:
#         # Clean up temp files regardless of success/failure
#         for f in temp_files:
#             try:
#                 if isinstance(f, Path) and f.exists():
#                     f.unlink()
#             except Exception:
#                 pass
#         # Clean up chunked audio files
#         for chunk in TEMP_DIR.glob(f"{job_id}_chunk_*.wav"):
#             try: chunk.unlink()
#             except: pass


# # ═══════════════════════════════════════════════════════════════════════════════
# #  API ROUTES
# # ═══════════════════════════════════════════════════════════════════════════════

# @app.route("/api/health", methods=["GET"])
# def health():
#     return jsonify({
#         "status": "ok",
#         "version": "2.1.0",
#         "ffmpeg": FFMPEG,
#         "ffprobe": FFPROBE,
#     })


# @app.route("/api/validate-key", methods=["POST"])
# def validate_key():
#     data    = request.json or {}
#     api_key = data.get("api_key", "").strip()
#     if not api_key:
#         return jsonify({"valid": False, "error": "No API key provided"}), 400
#     try:
#         client = Groq(api_key=api_key)
#         client.chat.completions.create(
#             model="llama-3.1-8b-instant",
#             messages=[{"role": "user", "content": "hi"}],
#             max_tokens=3,
#         )
#         return jsonify({"valid": True})
#     except Exception as e:
#         msg = str(e)
#         if "401" in msg or "auth" in msg.lower():
#             msg = "Invalid API key — check https://console.groq.com"
#         return jsonify({"valid": False, "error": msg}), 400


# @app.route("/api/start", methods=["POST"])
# def start_job():
#     api_key = request.form.get("api_key", "").strip()
#     if not api_key:
#         return jsonify({"error": "Groq API key required"}), 400
#     if "video" not in request.files:
#         return jsonify({"error": "No video file uploaded"}), 400

#     file = request.files["video"]
#     if not file.filename:
#         return jsonify({"error": "Empty filename"}), 400

#     allowed = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".ts", ".wmv"}
#     ext = Path(file.filename).suffix.lower()
#     if ext not in allowed:
#         return jsonify({"error": f"Unsupported format '{ext}'. Supported: {', '.join(sorted(allowed))}"}), 400

#     job_id     = str(uuid.uuid4())
#     video_path = UPLOAD_DIR / f"{job_id}{ext}"
#     file.save(str(video_path))

#     file_size = video_path.stat().st_size
#     if file_size < 4096:
#         video_path.unlink()
#         return jsonify({"error": "File too small — likely corrupted or empty"}), 400

#     params = {
#         "api_key":         api_key,
#         "src_lang":        request.form.get("src_lang",        "Japanese"),
#         "tgt_lang":        request.form.get("tgt_lang",        "Hindi"),
#         "style":           request.form.get("style",           "natural"),
#         "voice":           request.form.get("voice",           "male_hero"),
#         "speed":           request.form.get("speed",           "1.0"),
#         "original_volume": request.form.get("original_volume", "0.0"),
#     }

#     size_mb = file_size / (1024 * 1024)
#     with jobs_lock:
#         jobs[job_id] = {
#             "id":         job_id,
#             "status":     "queued",
#             "progress":   0,
#             "logs":       [f"📁 Uploaded: {file.filename} ({size_mb:.1f} MB)"],
#             "params":     {k: v for k, v in params.items() if k != "api_key"},
#             "created_at": time.time(),
#         }

#     threading.Thread(
#         target=run_pipeline,
#         args=(job_id, video_path, params),
#         daemon=True,
#     ).start()

#     return jsonify({"job_id": job_id}), 202


# @app.route("/api/job/<job_id>", methods=["GET"])
# def get_job(job_id: str):
#     with jobs_lock:
#         job = jobs.get(job_id)
#     if not job:
#         return jsonify({"error": "Job not found"}), 404
#     return jsonify({k: v for k, v in job.items() if k != "api_key"})


# @app.route("/api/job/<job_id>/stream", methods=["GET"])
# def stream_job(job_id: str):
#     """SSE stream for real-time progress updates."""
#     def generate():
#         last = 0
#         while True:
#             with jobs_lock:
#                 job = jobs.get(job_id, {})

#             logs   = job.get("logs", [])
#             status = job.get("status", "unknown")

#             payload = json.dumps({
#                 "status":   status,
#                 "progress": job.get("progress", 0),
#                 "logs":     logs[last:],
#                 "error":    job.get("error"),
#                 "output":   job.get("output_file") if status == "done" else None,
#             })
#             last = len(logs)
#             yield f"data: {payload}\n\n"

#             if status in ("done", "error"):
#                 break
#             time.sleep(0.8)

#     return Response(generate(), mimetype="text/event-stream",
#                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# @app.route("/api/download/<job_id>", methods=["GET"])
# def download(job_id: str):
#     with jobs_lock:
#         job = jobs.get(job_id, {})
#     if job.get("status") != "done":
#         return jsonify({"error": "Job not complete"}), 400
#     fname = job.get("output_file")
#     if not fname:
#         return jsonify({"error": "No output file recorded"}), 404
#     path = OUTPUT_DIR / fname
#     if not path.exists():
#         return jsonify({"error": f"Output file missing: {fname}"}), 404
#     return send_file(str(path), mimetype="video/mp4",
#                      as_attachment=True, download_name=fname)


# @app.route("/api/transcript/<job_id>", methods=["GET"])
# def get_transcript(job_id: str):
#     with jobs_lock:
#         job = jobs.get(job_id, {})
#     if not job:
#         return jsonify({"error": "Job not found"}), 404
#     return jsonify({"segments": job.get("segments", []),
#                     "translated": job.get("translated", [])})


# @app.route("/api/text-dub", methods=["POST"])
# def text_dub():
#     """Dub pasted dialogue text — returns MP3 audio file."""
#     data     = request.json or {}
#     api_key  = data.get("api_key", "").strip()
#     text     = data.get("text", "").strip()
#     src_lang = data.get("src_lang", "Japanese")
#     tgt_lang = data.get("tgt_lang", "Hindi")
#     style    = data.get("style", "natural")
#     voice    = data.get("voice", "male_hero")
#     speed    = float(data.get("speed", 1.0))

#     if not api_key or not text:
#         return jsonify({"error": "api_key and text are required"}), 400

#     job_id = str(uuid.uuid4())
#     temp   = []

#     try:
#         # Build fake-timed segments from lines
#         lines = [l.strip() for l in text.splitlines() if l.strip()]
#         segs  = []
#         t = 0.0
#         for i, line in enumerate(lines):
#             dur = max(1.5, len(line) * 0.065)
#             segs.append({"id": i, "start": t, "end": t + dur, "text": line})
#             t += dur + 0.35

#         # Translate
#         translated = step_translate(job_id, segs, src_lang, tgt_lang, style, api_key)

#         # TTS
#         tts_done = step_generate_tts(job_id, translated, tgt_lang, voice, speed, api_key)
#         for seg in tts_done:
#             if seg.get("audio_path"):
#                 temp.append(Path(seg["audio_path"]))

#         # Concatenate in order (pydub)
#         combined = AudioSegment.empty()
#         for seg in tts_done:
#             if seg.get("audio_path") and Path(seg["audio_path"]).exists():
#                 clip = AudioSegment.from_file(seg["audio_path"])  # handles both .wav and .mp3
#                 combined += clip + AudioSegment.silent(duration=300)  # 300ms pause

#         if len(combined) == 0:
#             return jsonify({"error": "TTS produced no audio"}), 500

#         final = OUTPUT_DIR / f"{job_id}_text_dubbed.mp3"
#         combined.export(str(final), format="mp3", bitrate="192k")
#         temp.append(final)

#         return send_file(str(final), mimetype="audio/mpeg",
#                          as_attachment=True,
#                          download_name=f"dubbed_{tgt_lang.lower()}.mp3")

#     except Exception as e:
#         return jsonify({"error": str(e)}), 500
#     finally:
#         for f in temp:
#             try:
#                 if f.exists() and "_text_dubbed" not in f.name:
#                     f.unlink()
#             except Exception:
#                 pass


# @app.route("/api/jobs", methods=["GET"])
# def list_jobs():
#     with jobs_lock:
#         all_j = sorted(jobs.values(), key=lambda j: j.get("created_at", 0), reverse=True)
#     return jsonify([{k: v for k, v in j.items() if k != "api_key"} for j in all_j[:20]])


# # ── Error handlers ─────────────────────────────────────────────────────────────
# @app.errorhandler(413)
# def too_large(e):
#     return jsonify({"error": "File too large. Maximum size is 4GB."}), 413


# if __name__ == "__main__":
#     print("\n" + "=" * 60)
#     print("  🎌 AniDub Studio — Backend v2.1")
#     print("=" * 60)
#     print(f"  Uploads : {UPLOAD_DIR}")
#     print(f"  Outputs : {OUTPUT_DIR}")
#     print(f"  Server  : http://localhost:5050")
#     print("=" * 60 + "\n")
#     app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)

"""
AniDub Studio — Backend v4.0  (PRODUCTION FIXED)
=================================================
Fixes over v3:
  [FIX-1]  CRITICAL: Broken FFmpeg filter_complex when bgm_path provided.
           Old code used [0:a:0] as both input AND muted source in same graph.
           New code: when Demucs BGM available, only 2 inputs (video for video
           stream only, dubbed audio, bgm) — no ambiguous audio from video input.
  [FIX-2]  stream_to_file() broken on newer groq-python — replaced with
           manual write via .content attribute.
  [FIX-3]  _find_binary("ffprobe") called inside step_fit_durations but
           FFPROBE not resolved at startup — use FFPROBE global everywhere.
  [FIX-4]  step_separate_audio returns (full_audio, None) when Demucs unavailable
           but step_mux_video BGM path branch still tried to use None — added
           explicit guard.
  [FIX-5]  pydub AudioSegment.from_file on .wav Groq output sometimes fails
           if file is raw PCM without RIFF header — added WAV→MP3 conversion.
  [FIX-6]  Duration fitting: atempo 0.4 is below FFmpeg minimum (0.5 on some
           builds). Clamped properly. Also _fit file suffix collision fixed.
  [FIX-7]  Demucs stereo input uses 44100 Hz stereo — added explicit check that
           stereo.wav was actually created before passing to demucs.
  [FIX-8]  text-dub route was missing from v3 active code (existed only in
           commented v2 block). Re-added.
  [FIX-9]  Job cleanup now also removes uploaded video and demucs temp dir.
  [FIX-10] /api/job/<id>/regen endpoint added for segment re-generation.
  [FIX-11] Windows path with spaces in FFmpeg subprocess — use list args (already
           done) but also ensure no shell=True anywhere.
  [FIX-12] progress_panel step IDs updated to match v4 frontend.
"""

import os, sys, uuid, json, time, random, asyncio, shutil, subprocess
import threading
from pathlib import Path
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from groq import Groq
from pydub import AudioSegment

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB

BASE_DIR   = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
TEMP_DIR   = BASE_DIR / "temp"
for d in [UPLOAD_DIR, OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(exist_ok=True)

# ── FFmpeg detection ───────────────────────────────────────────────────────────
def _find_binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        candidates = [
            rf"C:\ffmpeg\bin\{name}.exe",
            rf"C:\Program Files\ffmpeg\bin\{name}.exe",
            rf"C:\Program Files (x86)\ffmpeg\bin\{name}.exe",
            rf"C:\ProgramData\chocolatey\bin\{name}.exe",
            os.path.join(os.path.expanduser("~"), rf"scoop\apps\ffmpeg\current\bin\{name}.exe"),
            os.path.join(os.path.expanduser("~"), rf"AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\{name}.exe"),
        ]
        # Also scan WinGet packages directory
        winget_base = Path(os.path.expanduser("~")) / "AppData/Local/Microsoft/WinGet/Packages"
        if winget_base.exists():
            for pkg in winget_base.glob("Gyan.FFmpeg*"):
                for bin_path in pkg.rglob(f"{name}.exe"):
                    candidates.append(str(bin_path))
        for p in candidates:
            if os.path.exists(p):
                return p
    local = BASE_DIR / (name + (".exe" if sys.platform == "win32" else ""))
    if local.exists():
        return str(local)
    raise FileNotFoundError(
        f"'{name}' not found. Install FFmpeg:\n"
        "  Windows: winget install Gyan.FFmpeg  (then restart terminal)\n"
        "  Mac:     brew install ffmpeg\n"
        "  Ubuntu:  sudo apt install ffmpeg"
    )

try:
    FFMPEG  = _find_binary("ffmpeg")
    FFPROBE = _find_binary("ffprobe")
    print(f"[startup] ffmpeg : {FFMPEG}")
except FileNotFoundError as e:
    print(f"\n{'='*60}\n❌ STARTUP FAILED\n{e}\n{'='*60}\n")
    sys.exit(1)

# ── Demucs check ───────────────────────────────────────────────────────────────
try:
    import demucs.separate
    DEMUCS_AVAILABLE = True
    print("[startup] Demucs : available")
except ImportError:
    DEMUCS_AVAILABLE = False
    print("[startup] Demucs : not installed (pip install demucs)")

# ── Job store ──────────────────────────────────────────────────────────────────
jobs: dict = {}
jobs_lock  = threading.Lock()

def job_update(job_id: str, **kw):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kw)

def job_log(job_id: str, msg: str):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].setdefault("logs", []).append(msg)
    print(f"[{job_id[:8]}] {msg}")

def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

# ── Language / voice maps ──────────────────────────────────────────────────────
LANG_TO_CODE = {
    "Japanese": "ja", "Korean": "ko", "Chinese": "zh",
    "English":  "en", "Hindi":  "hi", "Spanish": "es",
    "French":   "fr", "German": "de", "Portuguese": "pt",
    "Arabic":   "ar", "Thai":   "th", "Vietnamese": "vi",
    "Indonesian": "id", "Tamil": "ta", "Telugu": "te",
    "Bengali":  "bn", "Urdu":   "ur", "Turkish": "tr",
    "Russian":  "ru", "Italian": "it", "Dutch": "nl",
}

GROQ_VOICES = {
    "male_hero":     "troy",
    "male_cool":     "austin",
    "male_villain":  "daniel",
    "male_wise":     "daniel",
    "female_hero":   "diana",
    "female_gentle": "autumn",
    "female_villain": "hannah",
    "narrator":      "austin",
}

GTTS_LANG_MAP = {
    "hi": "hi", "en": "en", "es": "es", "pt": "pt", "fr": "fr",
    "de": "de", "ko": "ko", "ja": "ja", "zh": "zh", "ar": "ar",
    "tr": "tr", "ru": "ru", "it": "it", "id": "id", "th": "th",
    "vi": "vi", "nl": "nl", "ta": "ta", "bn": "bn", "te": "te", "ur": "ur",
}

STYLE_GUIDE = {
    "natural":   "Match approximate speech duration. Use natural spoken language. Prioritize lip-sync — prefer shorter phrasings that fit the original timing.",
    "literal":   "Stay as close to the original meaning as possible. Minimal adaptation. Direct translation.",
    "localized": "Culturally adapt references, idioms, and honorifics for the target audience. Make it feel native.",
    "broadcast": "Formal, clear broadcast tone. Neutral enunciation. No slang or contractions.",
}

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1 — EXTRACT AUDIO
# ══════════════════════════════════════════════════════════════════════════════

def step_extract_audio(job_id: str, video_path: Path) -> Path:
    job_log(job_id, "🎬 Extracting audio from video...")
    out = TEMP_DIR / f"{job_id}_audio.wav"
    r = subprocess.run(
        [FFMPEG, "-y", "-i", str(video_path), "-vn",
         "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(out)],
        capture_output=True, text=True
    )
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"FFmpeg audio extraction failed:\n{r.stderr[-800:]}")
    mb = out.stat().st_size / (1024 * 1024)
    job_log(job_id, f"✅ Audio extracted: {mb:.1f} MB")
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1b — AUDIO SEPARATION (Demucs)
# ══════════════════════════════════════════════════════════════════════════════

def step_separate_audio(job_id: str, video_path: Path, use_demucs: bool = True):
    """
    Returns (vocals_path, bgm_path).
    FIX-7: Validate stereo.wav was created before passing to Demucs.
    FIX-4: Always return (path, None) if Demucs unavailable.
    """
    full_audio = step_extract_audio(job_id, video_path)

    if not use_demucs or not DEMUCS_AVAILABLE:
        job_log(job_id, "ℹ️  Skipping Demucs — using volume-blend mix")
        return full_audio, None

    job_log(job_id, "🎛️  Separating vocals from BGM with Demucs (1–3 min first time)...")
    sep_dir = TEMP_DIR / f"{job_id}_demucs"
    sep_dir.mkdir(exist_ok=True)

    # Extract stereo 44.1kHz for Demucs
    stereo = TEMP_DIR / f"{job_id}_stereo.wav"
    r_stereo = subprocess.run(
        [FFMPEG, "-y", "-i", str(video_path), "-vn",
         "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(stereo)],
        capture_output=True, text=True
    )
    # FIX-7: Validate stereo.wav was actually created
    if r_stereo.returncode != 0 or not stereo.exists() or stereo.stat().st_size < 1024:
        job_log(job_id, "⚠️  Stereo extraction failed — falling back to volume blend")
        return full_audio, None

    try:
        import demucs.separate
        demucs.separate.main([
            "--two-stems", "vocals",
            "--out", str(sep_dir),
            "--name", "htdemucs",
            str(stereo)
        ])

        vocals_list = list(sep_dir.rglob("vocals.wav"))
        bgm_list    = list(sep_dir.rglob("no_vocals.wav"))

        if not vocals_list or not bgm_list:
            raise RuntimeError("Demucs produced no output files")

        vocals_stereo = vocals_list[0]
        bgm_stereo    = bgm_list[0]

        # Downmix vocals to mono 16kHz for Whisper
        vocals_mono = TEMP_DIR / f"{job_id}_vocals_mono.wav"
        subprocess.run(
            [FFMPEG, "-y", "-i", str(vocals_stereo), "-ac", "1", "-ar", "16000", str(vocals_mono)],
            capture_output=True
        )

        if not vocals_mono.exists():
            raise RuntimeError("vocals_mono.wav not created")

        job_log(job_id, "✅ Audio separated: vocals + BGM isolated")
        return vocals_mono, bgm_stereo

    except Exception as e:
        job_log(job_id, f"⚠️  Demucs failed: {e} — falling back to volume blend")
        try:
            shutil.rmtree(sep_dir, ignore_errors=True)
        except Exception:
            pass
        return full_audio, None

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — TRANSCRIBE
# ══════════════════════════════════════════════════════════════════════════════

WHISPER_LIMIT_MB = 24.0
CHUNK_SECONDS    = 270

def _transcribe_single(client: Groq, audio_path: Path, lang_code: str) -> list:
    with open(audio_path, "rb") as f:
        resp = client.audio.transcriptions.create(
            file=(audio_path.name, f, "audio/wav"),
            model="whisper-large-v3-turbo",
            language=lang_code,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    segs = []
    for s in (getattr(resp, "segments", None) or []):
        t = str(getattr(s, "text", "")).strip()
        if t:
            segs.append({
                "id":    len(segs),
                "start": float(getattr(s, "start", 0)),
                "end":   float(getattr(s, "end", 0)),
                "text":  t,
            })
    if not segs and getattr(resp, "text", "").strip():
        segs = [{"id": 0, "start": 0.0, "end": 9999.0, "text": resp.text.strip()}]
    return segs

def step_transcribe(job_id: str, audio_path: Path, src_lang: str, api_key: str) -> list:
    lang_code = LANG_TO_CODE.get(src_lang, "ja")
    client    = Groq(api_key=api_key)
    mb        = audio_path.stat().st_size / (1024 * 1024)
    job_log(job_id, f"🎤 Transcribing ({src_lang}, {mb:.1f} MB) with Groq Whisper...")

    if mb <= WHISPER_LIMIT_MB:
        segs = _transcribe_single(client, audio_path, lang_code)
    else:
        job_log(job_id, f"   File {mb:.1f} MB > limit — chunking into {CHUNK_SECONDS}s pieces...")
        pattern = TEMP_DIR / f"{job_id}_chunk_%04d.wav"
        subprocess.run(
            [FFMPEG, "-y", "-i", str(audio_path),
             "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
             "-acodec", "pcm_s16le", str(pattern)],
            capture_output=True
        )
        chunks = sorted(TEMP_DIR.glob(f"{job_id}_chunk_*.wav"))
        if not chunks:
            raise RuntimeError("Audio chunking produced no files")

        segs   = []
        offset = 0.0
        for i, c in enumerate(chunks):
            job_log(job_id, f"   Chunk {i+1}/{len(chunks)}...")
            for s in _transcribe_single(client, c, lang_code):
                s["id"]    = len(segs)
                s["start"] += offset
                s["end"]   += offset
                segs.append(s)
            probe = subprocess.run(
                [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", str(c)],
                capture_output=True, text=True
            )
            try:
                offset += float(json.loads(probe.stdout)["format"]["duration"])
            except Exception:
                offset += CHUNK_SECONDS
            try:
                c.unlink()
            except Exception:
                pass
            time.sleep(0.3)

    if not segs:
        raise RuntimeError(
            "Transcription returned no text.\n"
            "• Check source language is correct\n"
            "• Ensure the video has audible speech\n"
            "• Try a shorter clip to test"
        )
    job_log(job_id, f"✅ Transcribed {len(segs)} dialogue segments")
    return segs

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — TRANSLATE
# ══════════════════════════════════════════════════════════════════════════════

def step_translate(job_id: str, segments: list, src_lang: str,
                   tgt_lang: str, style: str, api_key: str) -> list:
    job_log(job_id, f"🌐 Translating {src_lang} → {tgt_lang} [{style}]...")
    client     = Groq(api_key=api_key)
    guide      = STYLE_GUIDE.get(style, STYLE_GUIDE["natural"])
    batch_size = 25
    results    = []
    total_bat  = (len(segments) + batch_size - 1) // batch_size

    for bi in range(0, len(segments), batch_size):
        batch = segments[bi : bi + batch_size]
        bn    = bi // batch_size + 1
        job_log(job_id, f"   Batch {bn}/{total_bat} ({len(batch)} lines)...")
        input_data = [{"idx": i, "text": s["text"]} for i, s in enumerate(batch)]
        prompt = (
            f"Translate the following {src_lang} anime dialogue to {tgt_lang}.\n"
            f"Style: {guide}\n"
            "Rules:\n"
            "- Return ONLY a JSON array. No markdown, no explanation.\n"
            "- Same number of items as input, same order.\n"
            '- Each item: {"idx": <same as input>, "translated": "<translation>"}\n'
            "- Preserve character voice, emotions, and energy.\n\n"
            f"Input:\n{json.dumps(input_data, ensure_ascii=False)}\n\n"
            "JSON array:"
        )
        translated_batch = None
        for attempt in range(4):
            try:
                resp = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content":
                            f"Expert anime dubbing translator. {src_lang}→{tgt_lang}. "
                            "Return only valid JSON arrays."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.25,
                    max_tokens=4096,
                )
                raw = resp.choices[0].message.content.strip()
                if "```" in raw:
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw   = raw.strip().rstrip(",")
                start = raw.find("[")
                end   = raw.rfind("]") + 1
                if start >= 0 and end > start:
                    raw = raw[start:end]
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    translated_batch = parsed
                    break
            except Exception as ex:
                if attempt < 3:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    job_log(job_id, f"⚠️  Batch {bn} failed: {ex} — using original text")

        for i, seg in enumerate(batch):
            translation = seg["text"]
            if translated_batch:
                for item in translated_batch:
                    if isinstance(item, dict) and item.get("idx") == i:
                        t = str(item.get("translated", "")).strip()
                        if t:
                            translation = t
                        break
                else:
                    if i < len(translated_batch):
                        t = str(translated_batch[i].get("translated", "")).strip()
                        if t:
                            translation = t
            results.append({**seg, "translated": translation})

    job_log(job_id, f"✅ Translation complete ({len(results)} segments)")
    return results

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 4 — TTS GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _tts_gtts(text: str, lang_code: str, out_path: Path, slow: bool = False) -> bool:
    try:
        from gtts import gTTS
        gTTS(text=text, lang=GTTS_LANG_MAP.get(lang_code, "en"), slow=slow).save(str(out_path))
        return out_path.exists() and out_path.stat().st_size > 512
    except Exception:
        return False

def _tts_pyttsx3(text: str, out_path: Path) -> bool:
    try:
        import pyttsx3
        e = pyttsx3.init()
        e.setProperty("rate", 165)
        wav = out_path.with_suffix(".wav")
        e.save_to_file(text, str(wav))
        e.runAndWait()
        if wav.exists() and wav.stat().st_size > 512:
            AudioSegment.from_wav(str(wav)).export(str(out_path), format="mp3")
            wav.unlink(missing_ok=True)
            return out_path.exists() and out_path.stat().st_size > 512
        return False
    except Exception:
        return False

def _tts_multilingual(job_id: str, seg_id: int, text: str,
                       lang_code: str, out_path: Path, max_attempts: int = 3) -> bool:
    for attempt in range(max_attempts):
        try:
            if out_path.exists():
                out_path.unlink()
        except Exception:
            pass
        if _tts_gtts(text, lang_code, out_path):
            return True
        if attempt < max_attempts - 1:
            wait = 1.5 * (attempt + 1) + random.uniform(0, 0.5)
            job_log(job_id, f"   Seg {seg_id}: gTTS attempt {attempt+1} failed, retry {wait:.1f}s...")
            time.sleep(wait)
    job_log(job_id, f"   Seg {seg_id}: gTTS failed — trying pyttsx3 offline...")
    fb = out_path.with_stem(out_path.stem + "_off")
    if _tts_pyttsx3(text, fb):
        try:
            fb.rename(out_path)
        except Exception:
            pass
        if out_path.exists():
            return True
    return False

def step_generate_tts(job_id: str, translated: list, tgt_lang: str,
                      voice_profile: str, speed: float, api_key: str) -> list:
    lang_code  = LANG_TO_CODE.get(tgt_lang, "en")
    use_groq   = (lang_code == "en")
    client     = Groq(api_key=api_key) if use_groq else None
    groq_voice = GROQ_VOICES.get(voice_profile, "troy")
    engine_name = "Groq Orpheus" if use_groq else f"gTTS ({lang_code})"
    job_log(job_id, f"🔊 Generating TTS [{tgt_lang} / {voice_profile}] via {engine_name}...")

    ok = 0
    fail = 0

    for seg in translated:
        text = seg.get("translated", seg.get("text", "")).strip()
        if not text:
            seg["audio_path"] = None
            continue

        # FIX-5: Use .wav for Groq output, convert to mp3 after if needed
        ext      = ".wav" if use_groq else ".mp3"
        out_path = TEMP_DIR / f"{job_id}_seg_{seg['id']:05d}{ext}"
        success  = False

        if use_groq:
            groq_failed = False
            for attempt in range(3):
                try:
                    if out_path.exists():
                        out_path.unlink()
                    resp = client.audio.speech.create(
                        model="canopylabs/orpheus-v1-english",
                        input=text,
                        voice=groq_voice,
                        response_format="wav",
                    )
                    # FIX-2: stream_to_file broken on newer groq-python
                    # Use .content directly (bytes)
                    raw_bytes = None
                    if hasattr(resp, "content"):
                        raw_bytes = resp.content
                    elif hasattr(resp, "read"):
                        raw_bytes = resp.read()
                    elif hasattr(resp, "stream_to_file"):
                        resp.stream_to_file(str(out_path))
                        if out_path.exists() and out_path.stat().st_size > 512:
                            success = True
                            break

                    if raw_bytes:
                        with open(out_path, "wb") as f:
                            f.write(raw_bytes)

                    if out_path.exists() and out_path.stat().st_size > 512:
                        # FIX-5: Verify it's a valid WAV (has RIFF header)
                        with open(out_path, "rb") as f:
                            header = f.read(4)
                        if header == b"RIFF":
                            success = True
                            break
                        else:
                            # Raw PCM — wrap it with pydub
                            try:
                                raw_audio = AudioSegment(
                                    data=open(out_path, "rb").read(),
                                    sample_width=2,
                                    frame_rate=24000,
                                    channels=1,
                                )
                                mp3_path = out_path.with_suffix(".mp3")
                                raw_audio.export(str(mp3_path), format="mp3")
                                out_path.unlink(missing_ok=True)
                                out_path = mp3_path
                                seg["audio_path"] = str(out_path)
                                success = True
                                break
                            except Exception:
                                pass

                except Exception as e:
                    err = str(e)
                    permanent = any(c in err for c in [
                        "400", "401", "403", "decommission",
                        "not found", "not available", "not supported", "terms"
                    ])
                    if permanent:
                        job_log(job_id, f"   Seg {seg['id']}: Groq unavailable — falling back to gTTS")
                        groq_failed = True
                        break
                    if attempt < 2:
                        wait = 3.0 * (2 ** attempt) + random.uniform(0, 1)
                        time.sleep(wait)
                    else:
                        groq_failed = True

            if not success and groq_failed:
                fb = TEMP_DIR / f"{job_id}_seg_{seg['id']:05d}_fb.mp3"
                if _tts_multilingual(job_id, seg["id"], text, "en", fb):
                    out_path = fb
                    success  = True
        else:
            success = _tts_multilingual(job_id, seg["id"], text, lang_code, out_path)

        if success:
            seg["audio_path"] = str(out_path)
            ok += 1
        else:
            seg["audio_path"] = None
            fail += 1

    job_log(job_id, f"✅ TTS done: {ok} OK, {fail} failed")
    if ok == 0:
        raise RuntimeError(
            f"TTS failed for ALL {fail} segments. Engine: {engine_name}\n"
            "Fixes:\n"
            "  • Groq Orpheus: accept terms at console.groq.com → Models\n"
            "  • gTTS: check internet connection (Google must be reachable)\n"
            "  • Verify Groq API key is valid at console.groq.com"
        )
    if fail > 0:
        job_log(job_id, f"⚠️  {fail} segments will be silent in final video")
    return translated

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 4b — DURATION FITTING
# ══════════════════════════════════════════════════════════════════════════════

def _get_audio_duration_ms(path: Path) -> float:
    """Get duration in milliseconds via ffprobe."""
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True
    )
    try:
        return float(json.loads(r.stdout)["format"]["duration"]) * 1000
    except Exception:
        return 0.0

def _stretch_clip(src_path: Path, target_ms: float, out_path: Path) -> Path:
    """
    Time-stretch/compress audio to fit target_ms using FFmpeg atempo.
    FIX-6: Clamp ratio properly for all FFmpeg versions (0.5–2.0 per filter).
    """
    src_ms = _get_audio_duration_ms(src_path)
    if not src_ms or src_ms <= 0:
        return src_path

    ratio = src_ms / target_ms  # >1 = speed up, <1 = slow down

    # Don't stretch if within 8% — unnecessary quality loss
    if abs(ratio - 1.0) < 0.08:
        return src_path

    # FIX-6: Clamp to sane range (never faster than 2.5x or slower than 0.5x)
    ratio = max(0.5, min(2.5, ratio))

    # Build atempo chain — each filter limited to [0.5, 2.0]
    ATEMPO_MAX = 2.0
    ATEMPO_MIN = 0.5
    filters = []
    r = ratio

    if r > ATEMPO_MAX:
        while r > ATEMPO_MAX:
            filters.append(f"atempo={ATEMPO_MAX}")
            r /= ATEMPO_MAX
        filters.append(f"atempo={r:.6f}")
    elif r < ATEMPO_MIN:
        while r < ATEMPO_MIN:
            filters.append(f"atempo={ATEMPO_MIN}")
            r /= ATEMPO_MIN
        filters.append(f"atempo={r:.6f}")
    else:
        filters.append(f"atempo={r:.6f}")

    afilter = ",".join(filters)
    result  = subprocess.run(
        [FFMPEG, "-y", "-i", str(src_path), "-filter:a", afilter, "-ar", "44100", str(out_path)],
        capture_output=True, text=True
    )
    if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 512:
        return out_path
    return src_path

def step_fit_durations(job_id: str, segments: list, total_duration: float) -> list:
    job_log(job_id, "⏱️  Fitting TTS durations to segment gaps...")
    valid = [s for s in segments if s.get("audio_path")]
    if not valid:
        return segments

    fitted = 0
    skipped = 0

    for i, seg in enumerate(valid):
        if i + 1 < len(valid):
            gap_s = valid[i + 1]["start"] - seg["start"]
        else:
            gap_s = total_duration - seg["start"]

        # Leave 300ms silence buffer at end of gap
        target_ms = max(200, (gap_s - 0.30) * 1000)

        src = Path(seg["audio_path"])
        # FIX-6: Use unique suffix to avoid collision
        stretched_path = TEMP_DIR / f"{job_id}_seg_{seg['id']:05d}_fit.mp3"

        result = _stretch_clip(src, target_ms, stretched_path)
        if result != src:
            seg["audio_path"] = str(result)
            fitted += 1
        else:
            if stretched_path.exists():
                try:
                    stretched_path.unlink()
                except Exception:
                    pass
            skipped += 1

    job_log(job_id, f"✅ Duration fitting: {fitted} stretched, {skipped} unchanged")
    return segments

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 5 — ASSEMBLE DUBBED AUDIO TRACK
# ══════════════════════════════════════════════════════════════════════════════

def _normalise_clip(clip: AudioSegment, target_dbfs: float = -18.0) -> AudioSegment:
    if clip.dBFS == float("-inf"):
        return clip
    diff = min(target_dbfs - clip.dBFS, 12.0)
    return clip.apply_gain(diff)

def step_build_dubbed_audio(job_id: str, segments: list, total_duration: float) -> Path:
    job_log(job_id, "🎵 Assembling dubbed audio track...")
    valid = [(s, s["audio_path"]) for s in segments if s.get("audio_path")]
    if not valid:
        raise RuntimeError("No TTS audio generated — nothing to assemble")

    track_ms = int((total_duration + 5.0) * 1000)
    track    = AudioSegment.silent(duration=track_ms, frame_rate=44100)

    for seg, apath in valid:
        try:
            clip   = AudioSegment.from_file(apath)
            clip   = _normalise_clip(clip)
            pos_ms = int(seg["start"] * 1000)
            if pos_ms < track_ms:
                track = track.overlay(clip, position=pos_ms)
        except Exception as e:
            job_log(job_id, f"⚠️  Skipping seg {seg['id']} in mix: {e}")

    out = TEMP_DIR / f"{job_id}_dubbed_track.mp3"
    track.export(str(out), format="mp3", bitrate="192k")
    kb = out.stat().st_size // 1024
    job_log(job_id, f"✅ Audio track assembled: {kb} KB")
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  STEP 6 — MUX VIDEO
#  FIX-1: Completely rewritten to fix filter_complex crash when bgm_path used.
#
#  Mixing modes:
#    A) bgm_path provided (Demucs success):
#       - Input 0: video file (video stream only — NO audio mapped from it)
#       - Input 1: dubbed_audio (the new TTS track)
#       - Input 2: bgm_path (the separated BGM from Demucs)
#       → Mix: [1:a][2:a]amix → output
#       → Never reference [0:a] at all (avoids "unconnected output" error)
#
#    B) orig_vol > 0 (volume blend without Demucs):
#       - Input 0: video file
#       - Input 1: dubbed_audio
#       → Mix: [0:a]volume=orig_vol + [1:a]volume=1.0 → amix
#
#    C) orig_vol == 0 (replace original audio completely):
#       - Input 0: video file
#       - Input 1: dubbed_audio
#       → Just map 0:v and 1:a, no filter_complex needed
# ══════════════════════════════════════════════════════════════════════════════

def step_mux_video(job_id: str, video_path: Path, dubbed_audio: Path,
                   orig_vol: float, bgm_path: Path = None) -> Path:
    job_log(job_id, "📼 Muxing final video...")
    out = OUTPUT_DIR / f"{job_id}_dubbed.mp4"

    def _build_cmd(reencode: bool) -> list:
        vc = ["libx264", "-preset", "fast", "-crf", "20"] if reencode else ["copy"]

        if bgm_path and bgm_path.exists():
            # FIX-1: Mode A — Demucs BGM available
            # 3 inputs: [0]=video(video only), [1]=dubbed audio, [2]=bgm
            # filter_complex only touches [1] and [2], never [0:a]
            af = "[1:a]volume=1.0[dub];[2:a]volume=1.0[bgm];[dub][bgm]amix=inputs=2:duration=first:normalize=0[out]"
            return [
                FFMPEG, "-y",
                "-i", str(video_path),   # 0: video source (map video only)
                "-i", str(dubbed_audio), # 1: dubbed TTS track
                "-i", str(bgm_path),     # 2: BGM from Demucs
                "-filter_complex", af,
                "-map", "0:v:0",
                "-map", "[out]",
                "-c:v", *vc,
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                str(out),
            ]
        elif orig_vol > 0.01:
            # Mode B — volume blend
            af = (
                f"[0:a:0]volume={orig_vol:.4f}[orig];"
                f"[1:a:0]volume=1.0[dub];"
                f"[orig][dub]amix=inputs=2:duration=first:normalize=0[out]"
            )
            return [
                FFMPEG, "-y",
                "-i", str(video_path),
                "-i", str(dubbed_audio),
                "-filter_complex", af,
                "-map", "0:v:0",
                "-map", "[out]",
                "-c:v", *vc,
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                str(out),
            ]
        else:
            # Mode C — complete audio replacement (no filter_complex)
            return [
                FFMPEG, "-y",
                "-i", str(video_path),
                "-i", str(dubbed_audio),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", *vc,
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                str(out),
            ]

    # Attempt 1: stream copy (fast)
    r = subprocess.run(_build_cmd(reencode=False), capture_output=True, text=True)
    if r.returncode != 0 or not out.exists() or out.stat().st_size < 4096:
        job_log(job_id, "   Stream copy failed — re-encoding video (slower)...")
        if out.exists():
            out.unlink()
        # Attempt 2: re-encode with libx264
        r2 = subprocess.run(_build_cmd(reencode=True), capture_output=True, text=True)
        if r2.returncode != 0 or not out.exists() or out.stat().st_size < 4096:
            raise RuntimeError(
                f"FFmpeg mux failed.\n"
                f"Error: {r2.stderr[-1200:]}"
            )

    mb = out.stat().st_size / (1024 * 1024)
    job_log(job_id, f"✅ Final video: {out.name} ({mb:.1f} MB)")
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  VIDEO DURATION
# ══════════════════════════════════════════════════════════════════════════════

def get_video_duration(path: Path) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True
    )
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 1500.0

# ══════════════════════════════════════════════════════════════════════════════
#  FULL PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(job_id: str, video_path: Path, params: dict):
    api_key    = params["api_key"]
    src_lang   = params["src_lang"]
    tgt_lang   = params["tgt_lang"]
    style      = params["style"]
    voice      = params["voice"]
    speed      = float(params.get("speed", 1.0))
    orig_vol   = float(params.get("original_volume", 0.0))
    use_demucs = params.get("use_demucs", True)

    temps = []  # files to clean up

    try:
        job_update(job_id, status="running", progress=3)

        # Get video duration first
        total_dur = get_video_duration(video_path)

        # Step 1/1b: Extract + optionally separate
        vocals_path, bgm_path = step_separate_audio(job_id, video_path, use_demucs=use_demucs)
        temps.append(vocals_path)
        if bgm_path:
            temps.append(bgm_path)
        job_update(job_id, progress=13)

        # Step 2: Transcribe
        segments = step_transcribe(job_id, vocals_path, src_lang, api_key)
        job_update(job_id, progress=29, segments=segments)

        # Step 3: Translate
        translated = step_translate(job_id, segments, src_lang, tgt_lang, style, api_key)
        job_update(job_id, progress=47, translated=translated)

        # Step 4: TTS
        tts_done = step_generate_tts(job_id, translated, tgt_lang, voice, speed, api_key)
        for s in tts_done:
            if s.get("audio_path"):
                temps.append(Path(s["audio_path"]))
        job_update(job_id, progress=67)

        # Step 4b: Duration fitting
        fitted = step_fit_durations(job_id, tts_done, total_dur)
        for s in fitted:
            ap = s.get("audio_path")
            if ap and "_fit" in ap:
                p = Path(ap)
                if p not in temps:
                    temps.append(p)
        job_update(job_id, progress=78)

        # Step 5: Assemble dubbed audio
        dubbed_audio = step_build_dubbed_audio(job_id, fitted, total_dur)
        temps.append(dubbed_audio)
        job_update(job_id, progress=88)

        # Step 6: Mux video
        final = step_mux_video(job_id, video_path, dubbed_audio, orig_vol, bgm_path)
        job_update(job_id, progress=100, status="done",
                   output_file=final.name,
                   output_size=final.stat().st_size)
        job_log(job_id, f"🎉 Done! → {final.name}")

    except Exception as e:
        import traceback
        job_log(job_id, f"❌ Pipeline failed: {e}")
        print(f"[{job_id[:8]}] TRACEBACK:\n{traceback.format_exc()}")
        job_update(job_id, status="error", error=str(e))

    finally:
        # FIX-9: Clean up all temp files + uploaded video
        for f in temps:
            try:
                if isinstance(f, Path) and f.exists():
                    f.unlink()
            except Exception:
                pass
        # Chunk files
        for c in TEMP_DIR.glob(f"{job_id}_chunk_*.wav"):
            try:
                c.unlink()
            except Exception:
                pass
        # Demucs directory
        demucs_dir = TEMP_DIR / f"{job_id}_demucs"
        if demucs_dir.exists():
            try:
                shutil.rmtree(demucs_dir, ignore_errors=True)
            except Exception:
                pass
        # Stereo wav
        stereo = TEMP_DIR / f"{job_id}_stereo.wav"
        if stereo.exists():
            try:
                stereo.unlink()
            except Exception:
                pass
        # Uploaded video
        try:
            if video_path.exists():
                video_path.unlink()
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════════════════
#  API ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/health")
def health():
    return jsonify({
        "status":  "ok",
        "version": "4.0.0",
        "demucs":  DEMUCS_AVAILABLE,
        "ffmpeg":  FFMPEG,
    })

@app.route("/api/validate-key", methods=["POST"])
def validate_key():
    key = (request.json or {}).get("api_key", "").strip()
    if not key:
        return jsonify({"valid": False, "error": "No key provided"}), 400
    try:
        Groq(api_key=key).chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=3,
        )
        return jsonify({"valid": True})
    except Exception as e:
        msg = str(e)
        if "401" in msg or "auth" in msg.lower():
            msg = "Invalid API key — check https://console.groq.com"
        return jsonify({"valid": False, "error": msg}), 400

@app.route("/api/start", methods=["POST"])
def start_job():
    api_key = request.form.get("api_key", "").strip()
    if not api_key:
        return jsonify({"error": "Groq API key required"}), 400
    if "video" not in request.files:
        return jsonify({"error": "No video file uploaded"}), 400

    f   = request.files["video"]
    ext = Path(f.filename).suffix.lower()
    if ext not in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".ts", ".wmv"}:
        return jsonify({"error": f"Unsupported format: {ext}"}), 400

    job_id = str(uuid.uuid4())
    vpath  = UPLOAD_DIR / f"{job_id}{ext}"
    f.save(str(vpath))

    if not vpath.exists() or vpath.stat().st_size < 4096:
        if vpath.exists():
            vpath.unlink()
        return jsonify({"error": "File too small or upload failed"}), 400

    params = {
        "api_key":         api_key,
        "src_lang":        request.form.get("src_lang", "Japanese"),
        "tgt_lang":        request.form.get("tgt_lang", "Hindi"),
        "style":           request.form.get("style", "natural"),
        "voice":           request.form.get("voice", "male_hero"),
        "speed":           request.form.get("speed", "1.0"),
        "original_volume": request.form.get("original_volume", "0.0"),
        "use_demucs":      request.form.get("use_demucs", "true").lower() == "true",
    }

    mb = vpath.stat().st_size / (1024 * 1024)
    with jobs_lock:
        jobs[job_id] = {
            "id":         job_id,
            "status":     "queued",
            "progress":   0,
            "logs":       [f"📁 Uploaded: {f.filename} ({mb:.1f} MB)"],
            "params":     {k: v for k, v in params.items() if k != "api_key"},
            "created_at": time.time(),
        }

    threading.Thread(
        target=run_pipeline,
        args=(job_id, vpath, params),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id}), 202

@app.route("/api/job/<job_id>")
def get_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({k: v for k, v in job.items() if k != "api_key"})

@app.route("/api/job/<job_id>/stream")
def stream_job(job_id: str):
    def gen():
        last = 0
        while True:
            with jobs_lock:
                job = jobs.get(job_id, {})
            logs   = job.get("logs", [])
            status = job.get("status", "unknown")
            payload = json.dumps({
                "status":   status,
                "progress": job.get("progress", 0),
                "logs":     logs[last:],
                "error":    job.get("error"),
                "output":   job.get("output_file") if status == "done" else None,
            })
            last = len(logs)
            yield f"data: {payload}\n\n"
            if status in ("done", "error"):
                break
            time.sleep(0.8)

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.route("/api/download/<job_id>")
def download(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id, {})
    if job.get("status") != "done":
        return jsonify({"error": "Job not complete"}), 400
    p = OUTPUT_DIR / job.get("output_file", "")
    if not p.exists():
        return jsonify({"error": "Output file missing"}), 404
    return send_file(str(p), mimetype="video/mp4", as_attachment=True, download_name=p.name)

@app.route("/api/transcript/<job_id>")
def get_transcript(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id, {})
    if not job:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "segments":   job.get("segments", []),
        "translated": job.get("translated", []),
    })

@app.route("/api/job/<job_id>/srt")
def export_srt(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id, {})
    if not job:
        return jsonify({"error": "Not found"}), 404
    segs = job.get("translated") or job.get("segments") or []
    if not segs:
        return jsonify({"error": "No segments available"}), 404

    def fmt(s: float) -> str:
        h   = int(s // 3600)
        m   = int((s % 3600) // 60)
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")

    lines = []
    for i, seg in enumerate(segs, 1):
        start = seg.get("start", 0)
        end   = seg.get("end", start + 2)
        text  = seg.get("translated") or seg.get("text", "")
        lines.append(f"{i}\n{fmt(start)} --> {fmt(end)}\n{text}\n")

    return Response(
        "\n".join(lines),
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="dubbed_{job_id[:8]}.srt"'}
    )

# FIX-8: Re-add text-dub route (was missing from v3 active code)
@app.route("/api/text-dub", methods=["POST"])
def text_dub():
    data     = request.json or {}
    api_key  = data.get("api_key", "").strip()
    text     = data.get("text", "").strip()
    src_lang = data.get("src_lang", "Japanese")
    tgt_lang = data.get("tgt_lang", "Hindi")
    style    = data.get("style", "natural")
    voice    = data.get("voice", "male_hero")
    speed    = float(data.get("speed", 1.0))

    if not api_key or not text:
        return jsonify({"error": "api_key and text are required"}), 400

    job_id = str(uuid.uuid4())
    temps  = []

    try:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        segs  = []
        t     = 0.0
        for i, line in enumerate(lines):
            dur = max(1.5, len(line) * 0.065)
            segs.append({"id": i, "start": t, "end": t + dur, "text": line})
            t += dur + 0.35

        translated = step_translate(job_id, segs, src_lang, tgt_lang, style, api_key)
        tts_done   = step_generate_tts(job_id, translated, tgt_lang, voice, speed, api_key)

        for seg in tts_done:
            if seg.get("audio_path"):
                temps.append(Path(seg["audio_path"]))

        combined = AudioSegment.empty()
        for seg in tts_done:
            if seg.get("audio_path") and Path(seg["audio_path"]).exists():
                clip = AudioSegment.from_file(seg["audio_path"])
                combined += clip + AudioSegment.silent(duration=300)

        if len(combined) == 0:
            return jsonify({"error": "TTS produced no audio"}), 500

        final = OUTPUT_DIR / f"{job_id}_text_dubbed.mp3"
        combined.export(str(final), format="mp3", bitrate="192k")
        temps.append(final)

        return send_file(
            str(final),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"dubbed_{tgt_lang.lower()}.mp3",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        for f in temps:
            try:
                if f.exists() and "_text_dubbed" not in f.name:
                    f.unlink()
            except Exception:
                pass

# FIX-10: Segment regen endpoint
@app.route("/api/job/<job_id>/regen", methods=["POST"])
def regen_segments(job_id: str):
    """Re-generate TTS for manually edited segments."""
    with jobs_lock:
        job = jobs.get(job_id, {})
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data     = request.json or {}
    api_key  = data.get("api_key", "").strip()
    segments = data.get("segments", [])
    tgt_lang = data.get("tgt_lang") or job.get("params", {}).get("tgt_lang", "Hindi")
    voice    = data.get("voice")    or job.get("params", {}).get("voice", "male_hero")
    speed    = float(data.get("speed", job.get("params", {}).get("speed", 1.0)))

    if not api_key:
        return jsonify({"error": "api_key required"}), 400
    if not segments:
        return jsonify({"error": "No segments provided"}), 400

    regen_id = str(uuid.uuid4())
    try:
        # Run TTS only on provided segments
        tts_done = step_generate_tts(regen_id, segments, tgt_lang, voice, speed, api_key)

        # Build audio track using original segment timings from full job
        all_segs = job.get("translated", [])
        # Merge edited segments back
        seg_map = {s["id"]: s for s in tts_done if s.get("audio_path")}
        for s in all_segs:
            if s["id"] in seg_map:
                s["audio_path"] = seg_map[s["id"]]["audio_path"]

        total_dur = float(job.get("params", {}).get("total_duration", 300))
        dubbed_audio = step_build_dubbed_audio(regen_id, all_segs, total_dur)

        video_files = list(UPLOAD_DIR.glob(f"{job_id}.*"))
        if not video_files:
            return jsonify({"error": "Original video no longer on server"}), 400

        video_path = video_files[0]
        orig_vol   = float(job.get("params", {}).get("original_volume", 0))
        final      = step_mux_video(regen_id, video_path, dubbed_audio, orig_vol)

        # Update job record
        job_update(job_id, status="done",
                   output_file=final.name,
                   output_size=final.stat().st_size,
                   translated=all_segs)

        return jsonify({"output_file": final.name, "job_id": job_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/jobs")
def list_jobs():
    with jobs_lock:
        all_j = sorted(jobs.values(), key=lambda j: j.get("created_at", 0), reverse=True)
    return jsonify([{k: v for k, v in j.items() if k != "api_key"} for j in all_j[:20]])

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large (max 4 GB)"}), 413

if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  🎌 AniDub Studio — Backend v4.0  (PRODUCTION FIXED)")
    print("  Duration fitting: ✅  Audio separation: " +
          ("✅ Demucs" if DEMUCS_AVAILABLE else "⚠️  install: pip install demucs"))
    print("=" * 62 + "\n")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)