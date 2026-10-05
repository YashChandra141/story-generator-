"""ElevenLabs text-to-speech so the child can hear words and stories read aloud."""

import os

import httpx

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# "Rachel" - ElevenLabs' classic default voice; overridable via env var.
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"


class TTSError(Exception):
    """Raised when audio could not be produced."""


def _api_key() -> str:
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise TTSError("ELEVENLABS_API_KEY is not set")
    return key


def synthesize_speech(text: str, voice_id: str | None = None) -> bytes:
    """Convert text to MP3 audio bytes via the ElevenLabs API."""
    voice = (voice_id or os.getenv("ELEVENLABS_VOICE_ID", "") or DEFAULT_VOICE_ID).strip()
    model = os.getenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5").strip()
    try:
        resp = httpx.post(
            ELEVENLABS_TTS_URL.format(voice_id=voice),
            headers={
                "xi-api-key": _api_key(),
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={"text": text, "model_id": model},
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise TTSError(f"ElevenLabs request failed: {exc}") from exc

    if resp.status_code == 401:
        raise TTSError("ElevenLabs rejected the API key (401)")
    if resp.status_code == 429:
        raise TTSError("ElevenLabs rate limit / quota reached (429)")
    if resp.status_code != 200:
        raise TTSError(f"ElevenLabs error {resp.status_code}: {resp.text[:200]}")
    return resp.content