"""Speech-to-text integration point (spec section 20).

Deliberately isolated from Telegram: handlers/media.py downloads the voice
note and passes raw bytes here, never the other way around.

TODO(stage-16): implement against a real speech-to-text provider.
"""
from __future__ import annotations


async def transcribe_voice(audio_bytes: bytes, *, language_code: str | None = None) -> str:
    raise NotImplementedError("Speech-to-text integration arrives in Stage 16 (Voice)")
