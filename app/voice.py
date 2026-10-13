"""Voix off : lecture de la narration par synthèse vocale (gTTS)."""

from pathlib import Path

from gtts import gTTS
from gtts.lang import tts_langs


class VoiceError(RuntimeError):
    pass


def supported_language(code: str) -> str:
    return code if code in tts_langs() else "en"


def synthesize(text: str, language: str, path: Path) -> Path:
    try:
        gTTS(text=text, lang=supported_language(language)).save(str(path))
    except Exception as exc:  # gTTS lève des erreurs réseau variées
        raise VoiceError(f"La synthèse vocale a échoué : {exc}") from exc
    return path
