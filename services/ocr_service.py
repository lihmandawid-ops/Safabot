"""OCRService is the ONLY interface anything else may depend on for
image-to-text (bugfix spec section 17: 📷 Разбор текста с фотографии).
handlers/media.py calls get_ocr_service().extract_text_from_image(...),
never services/ocr_provider.py directly - the same seam services/
ai_service.py provides for AI features, kept as its own, separate module
because OCR is a genuinely different capability the configured AI chat
model does not claim to have.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache

from services.media_errors import OCRConfigurationError, OCRError
from services.ocr_provider import HttpOCRProvider, OCRProvider
from utils.logging import get_logger

logger = get_logger(__name__)


class OCRService(ABC):
    @abstractmethod
    async def extract_text_from_image(self, image_bytes: bytes, *, mime_type: str, user_id: int) -> str:
        """Text found in the image, or "" if there was none legible.
        Raises a services.media_errors.OCRError subclass on failure -
        never None, never a bare Exception."""


class NotConfiguredOCRService(OCRService):
    """No OCR_API_KEY set (or OCR_ENABLED=false) - the default state,
    since the configured AI chat model is not documented as vision-
    capable. Fails immediately and clearly (no network attempt) so
    handlers/media.py can show a friendly "not set up yet" message
    instead of pretending to have read the image."""

    async def extract_text_from_image(self, image_bytes, *, mime_type, user_id):
        raise OCRConfigurationError()


class LiveOCRService(OCRService):
    def __init__(self, *, provider: OCRProvider, provider_label: str) -> None:
        self._provider = provider
        self._provider_label = provider_label

    async def extract_text_from_image(self, image_bytes, *, mime_type, user_id):
        try:
            text = await self._provider.extract_text(image_bytes, mime_type=mime_type)
        except OCRError as exc:
            logger.warning(
                "OCR call failed user_id=%s provider=%s error=%s", user_id, self._provider_label, type(exc).__name__
            )
            raise
        logger.info("OCR call succeeded user_id=%s provider=%s chars=%d", user_id, self._provider_label, len(text))
        return text


@lru_cache(maxsize=1)
def get_ocr_service() -> OCRService:
    """Factory selecting the configured OCR backend. Cached like
    config.get_settings() - call get_ocr_service.cache_clear() after
    changing OCR-related environment variables mid-process (tests only)."""
    from config import get_settings

    settings = get_settings()
    if not settings.ocr_enabled or not settings.ocr_api_key:
        return NotConfiguredOCRService()

    provider = HttpOCRProvider(api_key=settings.ocr_api_key, model=settings.ocr_model, base_url=settings.ocr_base_url)
    return LiveOCRService(provider=provider, provider_label=settings.ocr_provider)
