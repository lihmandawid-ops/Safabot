"""OCR integration point (spec section 19).

Deliberately isolated from Telegram: handlers/media.py downloads the photo
and passes raw bytes here, never the other way around.

TODO(stage-15): implement against a real OCR provider (API key in .env as
OCR_API_KEY).
"""
from __future__ import annotations


async def extract_text_from_image(image_bytes: bytes) -> str:
    raise NotImplementedError("OCR integration arrives in Stage 15 (Photo)")
