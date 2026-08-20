"""Exception hierarchies for the OCR and speech-to-text layers
(services/ocr_provider.py + services/ocr_service.py, services/
stt_provider.py + services/stt_service.py).

Kept in one file because the two hierarchies are structurally identical
(same reasoning as services/ai_errors.py - each failure mode a caller
might react to differently gets its own subclass), but they are two
genuinely separate capabilities DeepSeek does not claim to have (bugfix
spec sections 17-18) - never conflated with AIError, and never with each
other, so a handler catching OCRError can never accidentally swallow an
STT failure or vice versa.
"""
from __future__ import annotations


class OCRError(Exception):
    """Base class for every OCR-layer (image -> text) failure."""


class OCRConfigurationError(OCRError):
    """No OCR_API_KEY configured (or OCR_ENABLED=false) - the default
    state, since the configured AI chat model is not documented as
    vision-capable and 📷 Разбор фото must never pretend otherwise."""

    def __init__(self, message: str = "Распознавание текста на фото пока не настроено.") -> None:
        super().__init__(message)


class OCRAuthenticationError(OCRError):
    """Provider rejected the API key (401/403). Never retried."""


class OCRTimeoutError(OCRError):
    """The OCR request did not complete in time."""


class OCRUnavailableError(OCRError):
    """Network failure or the provider returned a server error (5xx)."""


class OCRInvalidResponseError(OCRError):
    """The provider replied, but not with a usable text response."""


class STTError(Exception):
    """Base class for every speech-to-text-layer failure."""


class STTConfigurationError(STTError):
    """No STT_API_KEY configured (or STT_ENABLED=false) - the default
    state, since DeepSeek does not do audio transcription and 🎤 Разбор
    голоса must never pretend otherwise."""

    def __init__(self, message: str = "Распознавание голосовых сообщений пока не настроено.") -> None:
        super().__init__(message)


class STTAuthenticationError(STTError):
    """Provider rejected the API key (401/403). Never retried."""


class STTTimeoutError(STTError):
    """The transcription request did not complete in time."""


class STTUnavailableError(STTError):
    """Network failure or the provider returned a server error (5xx)."""


class STTInvalidResponseError(STTError):
    """The provider replied, but not with a usable text response."""
