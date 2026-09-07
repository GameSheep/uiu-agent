"""Voice interaction — TTS (text-to-speech) and STT (speech-to-text).

TTS: edge-tts (high quality, online, Chinese support) + pyttsx3 (offline fallback)
STT: whisper (local) or SpeechRecognition (Google API fallback)

Tools:
- speak(text): convert text to speech and play
- listen(): record audio and transcribe to text
- voice_state(): check if voice features are available

Install:
    pip install edge-tts pyttsx3 SpeechRecognition openai-whisper
"""

from __future__ import annotations

import os
import tempfile
import threading
import subprocess

# whisper 模型缓存：避免每次 listen 都重新加载（加载 base 约需数秒）
_whisper_model = None
_whisper_lock = threading.Lock()


def _get_whisper_model():
    """Get (and cache) the whisper model instance."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            import whisper
            _whisper_model = whisper.load_model("base")
        return _whisper_model


# ---------- TTS ----------

def speak(text: str, voice: str = "", rate: int = 0, save_path: str = "") -> str:
    """Convert text to speech and play it.

    Uses edge-tts (online, high quality) with pyttsx3 (offline) fallback.

    text: text to speak
    voice: voice name (e.g. "zh-CN-XiaoxiaoNeural" for Chinese female)
    rate: speech rate (-50 to +50, default 0)
    save_path: if set, save audio to file instead of playing
    """
    if not text.strip():
        return "[error] 没有要朗读的文本"

    # Try edge-tts first (better quality, Chinese support)
    try:
        return _speak_edge_tts(text, voice, rate, save_path)
    except Exception:
        pass

    # Fallback to pyttsx3 (offline)
    try:
        return _speak_pyttsx3(text, rate)
    except Exception as e:
        return f"[error] TTS 失败: {type(e).__name__}: {e}"


def _speak_edge_tts(text: str, voice: str, rate: int, save_path: str) -> str:
    """Speak using Microsoft Edge TTS (online, high quality)."""
    import asyncio
    import edge_tts

    # Default to Chinese voice if text contains CJK
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    if not voice:
        voice = "zh-CN-XiaoxiaoNeural" if has_cjk else "en-US-AriaNeural"

    rate_str = f"{rate:+d}%" if rate else "+0%"

    if save_path:
        # Just save to file
        async def _save():
            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            await communicate.save(save_path)

        asyncio.run(_save())
        return f"[ok] 语音已保存: {save_path}"
    else:
        # Play directly
        tmp_path = os.path.join(tempfile.gettempdir(), "uiu_speech.mp3")

        async def _generate():
            communicate = edge_tts.Communicate(text, voice, rate=rate_str)
            await communicate.save(tmp_path)

        asyncio.run(_generate())

        # Play the audio
        _play_audio(tmp_path)

        # Clean up temp file
        try:
            os.remove(tmp_path)
        except Exception:
            pass

        return f"[ok] 已朗读: {text[:50]}{'…' if len(text) > 50 else ''}"


def _speak_pyttsx3(text: str, rate_offset: int) -> str:
    """Speak using pyttsx3 (offline fallback)."""
    import pyttsx3

    engine = pyttsx3.init()
    if rate_offset:
        current = engine.getProperty("rate")
        engine.setProperty("rate", current + rate_offset)
    engine.say(text)
    engine.runAndWait()
    return f"[ok] 已朗读 (离线): {text[:50]}{'…' if len(text) > 50 else ''}"


def _play_audio(path: str):
    """Play an audio file (platform-specific)."""
    import os
    import platform

    system = platform.system()
    if system == "Windows":
        # SoundPlayer 只支持 .wav；mp3 用默认播放器打开（不拼字符串，无注入）
        if path.lower().endswith(".wav"):
            subprocess.run(
                ["powershell", "-NoProfile", "-c", "(New-Object Media.SoundPlayer $args[0]).PlaySync()",
                 "--", path],
                timeout=30,
                capture_output=True,
            )
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.run(["afplay", path], timeout=30, capture_output=True)
    else:
        subprocess.run(["aplay", path], timeout=30, capture_output=True)


# ---------- STT ----------

def listen(duration: int = 5, language: str = "") -> str:
    """Record audio from microphone and transcribe to text.

    Uses whisper (local) or SpeechRecognition (Google API) fallback.

    duration: recording duration in seconds (default 5)
    language: language code (e.g. "zh-CN", "en-US")
    """
    # Try whisper first (local, private)
    try:
        return _listen_whisper(duration, language)
    except Exception:
        pass

    # Fallback to SpeechRecognition
    try:
        return _listen_speech_recognition(duration, language)
    except Exception as e:
        return f"[error] STT 失败: {type(e).__name__}: {e}"


def _listen_whisper(duration: int, language: str) -> str:
    """Transcribe using OpenAI Whisper (local)."""
    import sounddevice as sd
    import numpy as np
    from scipy.io import wavfile

    # Record audio
    sample_rate = 16000
    recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1)
    sd.wait()

    # Save to temp file
    tmp_path = os.path.join(tempfile.gettempdir(), "iu_record.wav")
    wavfile.write(tmp_path, sample_rate, recording)

    # Transcribe
    model = _get_whisper_model()
    result = model.transcribe(tmp_path, language=language or None)

    # Clean up
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    text = result.get("text", "").strip()
    return text or "(未识别到语音)"


def _listen_speech_recognition(duration: int, language: str) -> str:
    """Transcribe using SpeechRecognition (Google API fallback)."""
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        audio = recognizer.listen(source, timeout=duration + 2, phrase_time_limit=duration)

    # Try Google's API
    lang = language or "zh-CN"  # 默认中文识别（Google 无语言参数时自动检测不可靠）
    try:
        text = recognizer.recognize_google(audio, language=lang)
        return text
    except sr.UnknownValueError:
        return "(未识别到语音)"
    except sr.RequestError as e:
        return f"[error] 语音识别 API 错误: {e}"


# ---------- state ----------

def voice_state() -> str:
    """Check which voice features are available."""
    state = []

    # TTS
    try:
        import edge_tts
        state.append("✅ edge-tts (在线 TTS)")
    except ImportError:
        state.append("❌ edge-tts (未安装: pip install edge-tts)")

    try:
        import pyttsx3
        state.append("✅ pyttsx3 (离线 TTS)")
    except ImportError:
        state.append("❌ pyttsx3 (未安装: pip install pyttsx3)")

    # STT
    try:
        import whisper
        state.append("✅ whisper (本地 STT)")
    except ImportError:
        state.append("❌ whisper (未安装: pip install openai-whisper)")

    try:
        import speech_recognition
        state.append("✅ SpeechRecognition (在线 STT)")
    except ImportError:
        state.append("❌ SpeechRecognition (未安装: pip install SpeechRecognition)")

    return "语音功能状态:\n" + "\n".join(f"  {s}" for s in state)


# ---------- tool definitions ----------

SPEAK_DEF = {
    "type": "function",
    "function": {
        "name": "speak",
        "description": "把文字转换成语音朗读出来。支持中文和英文。适合汇报结果、朗读文章。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要朗读的文字"},
                "voice": {"type": "string", "description": "语音名称（可选，默认中文女声）"},
                "rate": {"type": "integer", "description": "语速 (-50 到 +50，默认 0)"},
                "save_path": {"type": "string", "description": "保存音频文件路径（可选，不填则直接播放）"},
            },
            "required": ["text"],
        },
    },
}

LISTEN_DEF = {
    "type": "function",
    "function": {
        "name": "listen",
        "description": "录制麦克风语音并转成文字。支持中文和英文。适合语音输入指令。",
        "parameters": {
            "type": "object",
            "properties": {
                "duration": {"type": "integer", "description": "录音秒数（默认 5 秒）"},
                "language": {"type": "string", "description": "语言代码（如 zh-CN, en-US）"},
            },
        },
    },
}

VOICE_STATE_DEF = {
    "type": "function",
    "function": {
        "name": "voice_state",
        "description": "检查语音功能可用状态（TTS/STT 哪些已安装）",
        "parameters": {"type": "object", "properties": {}},
    },
}


VOICE_TOOLS: dict[str, dict] = {
    "speak": {"def": SPEAK_DEF, "fn": speak},
    "listen": {"def": LISTEN_DEF, "fn": listen},
    "voice_state": {"def": VOICE_STATE_DEF, "fn": voice_state},
}


def voice_tool_defs() -> list[dict]:
    return [t["def"] for t in VOICE_TOOLS.values()]


def call_voice_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in VOICE_TOOLS:
        return f"[error] unknown voice tool: {name}"
    fn = VOICE_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"
