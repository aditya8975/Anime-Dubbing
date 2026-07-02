# 🎌 AniDub Studio — Anime Dubbing Engine

> **Production-ready, 100% free** anime dubbing platform.  
> Japanese/Korean → Hindi/English/Spanish/+ in minutes.

---

## What It Does

AniDub Studio takes any anime video and produces a fully dubbed version in your target language:

1. **Extracts audio** from the video (FFmpeg)
2. **Transcribes** dialogue with Groq Whisper (AI, free)
3. **Translates** with Groq LLaMA-3.3-70b (AI, free)
4. **Generates voice** audio with Groq PlayAI TTS (English) or Microsoft Edge Neural TTS (Hindi, Spanish, etc.)
5. **Muxes** the dubbed audio back into the video (FFmpeg)

---

## Requirements

| Tool | Purpose | How to Install |
|------|---------|---------------|
| **Python 3.9+** | Backend runtime | https://python.org |
| **FFmpeg** | Video/audio processing | See below |
| **Groq API Key** | Transcription + Translation + TTS (FREE) | https://console.groq.com |

### Install FFmpeg

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install ffmpeg
```

**Windows:**
```
winget install ffmpeg
```
or download from https://ffmpeg.org/download.html and add to PATH.

---

## Quick Start

### 1. Get Your Free Groq API Key

Visit https://console.groq.com → Sign up → Create API key  
Free tier: 14,400 requests/day — more than enough for dubbing.

### 2. Start the Studio

**Mac/Linux:**
```bash
chmod +x start.sh
./start.sh
```

**Windows:**
```
start.bat
```

**Manual:**
```bash
cd backend
pip install -r requirements.txt
python app.py
```
Then open `frontend/index.html` in your browser.

### 3. Dub Your Anime

1. Enter your Groq API key and click **Verify**
2. Select source language (Japanese, Korean, etc.)
3. Select target language (Hindi, English, Spanish, etc.)
4. Choose voice profile and translation style
5. Drop your anime video file
6. Click **START DUBBING**
7. Download the dubbed MP4

---

## Supported Languages

### Source (Transcription)
Japanese, Korean, Chinese, English, Spanish, French, German, Portuguese, Arabic, Thai, Vietnamese, Indonesian, Hindi, Tamil, Telugu, Bengali, Russian, Turkish, Italian, Dutch, and 50+ more via Groq Whisper.

### Target (Dubbing)

| Language | TTS Engine | Voice Quality |
|----------|-----------|---------------|
| **English** | Groq PlayAI | ⭐⭐⭐⭐⭐ Excellent |
| **Hindi** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| **Spanish** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| **Portuguese** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| **French** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| **German** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| **Arabic** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| **Indonesian** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| **Japanese** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| **Korean** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| **Chinese** | Microsoft Edge Neural | ⭐⭐⭐⭐ Very Good |
| Russian, Turkish, Italian, Thai, Vietnamese, Dutch, + more | Microsoft Edge Neural | ⭐⭐⭐ Good |

---

## Voice Profiles

| Profile | Character Type | Best For |
|---------|---------------|----------|
| ⚡ Male Hero | Energetic, passionate | Shonen protagonists |
| 🧊 Male Cool | Calm, deep, confident | Rival characters |
| 💀 Male Villain | Dark, sharp, menacing | Antagonists |
| 🧙 Male Wise | Slow, measured, warm | Sensei/elder characters |
| ⚡ Female Hero | Fierce, powerful | Shonen heroines |
| 🌸 Female Gentle | Soft, warm, kind | Support characters |
| 🕷️ Female Villain | Sharp, calculating | Female antagonists |
| 📻 Narrator | Neutral, clear | Episode narration |

---

## Translation Styles

| Style | Description | Best For |
|-------|-------------|----------|
| **Natural** | Lip-sync friendly, spoken language | Standard anime dubbing |
| **Literal** | Close to original meaning | Subtitles reference |
| **Localized** | Cultural adaptation | Western audience dubs |
| **Broadcast** | Formal, clear enunciation | Official broadcast quality |

---

## Project Structure

```
anime-dubbing-studio/
├── start.sh              ← Run this (Mac/Linux)
├── start.bat             ← Run this (Windows)
├── frontend/
│   ├── index.html        ← Open in browser
│   ├── assets/
│   │   └── style.css     ← UI styles
│   └── js/
│       └── app.js        ← Frontend logic
└── backend/
    ├── app.py            ← Flask API server (main)
    ├── requirements.txt  ← Python dependencies
    └── .env.example      ← Copy to .env for key storage
```

---

## API Endpoints

The backend exposes these REST endpoints on `http://localhost:5050`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Server health check |
| `/api/validate-key` | POST | Verify Groq API key |
| `/api/start` | POST | Upload video and start dubbing |
| `/api/job/<id>` | GET | Get job status |
| `/api/job/<id>/stream` | GET | SSE stream for live updates |
| `/api/download/<id>` | GET | Download dubbed video |
| `/api/transcript/<id>` | GET | Get transcription + translation |
| `/api/text-dub` | POST | Dub from pasted text (no video) |
| `/api/jobs` | GET | List recent jobs |

---

## Tips for Best Results

- **Episode length:** Works for any length; 24-min episodes take ~5-8 min
- **Audio quality:** Clean audio = better transcription; avoid noisy sources
- **Translation style:** Use "Natural" for dubbing — it fits the timing better
- **Speed:** 0.9x helps translated audio fit better in some cases
- **Original volume:** Set to 10-15% to keep ambient sound effects
- **Long videos:** Split into episodes for best per-episode quality

---

## Costs

**Completely free.** All services used are on free tiers:

- **Groq Whisper** (transcription): Free — 14,400 requests/day
- **Groq LLaMA-3.3-70b** (translation): Free — generous daily limits
- **Groq PlayAI TTS** (English voice): Free tier available
- **Microsoft Edge Neural TTS** (multilingual): Free via edge-tts library
- **FFmpeg** (audio/video processing): Free, open-source

---

## Troubleshooting

**Backend not starting:**
- Make sure Python 3.9+ is installed
- Run: `pip install -r backend/requirements.txt`

**FFmpeg not found:**
- Install FFmpeg and make sure it's in your PATH
- Test: `ffmpeg -version`

**Transcription failed:**
- Verify your Groq API key is valid at https://console.groq.com
- Check that the video has clear audio

**Edge-TTS not working (Hindi/multilingual):**
- edge-tts requires internet access to Microsoft's TTS service
- Make sure you have a working internet connection

**TTS audio out of sync:**
- This happens when translated text is much longer/shorter than original
- Try "Natural" translation style which optimizes for timing
- Adjust speed slider (0.85-0.95x often helps)

---

## License

MIT — Use freely for personal and commercial projects.
