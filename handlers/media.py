"""📷 Разобрать фото / 🎤 Разобрать голос (spec sections 19-20).

TODO(stage-15/16): implement against services/ocr_service.py and
services/speech_service.py. Telegram file download happens here; OCR/STT
logic stays in the services module, never mixed into this handler.
Routed from handlers/menu.py, which currently shows a "coming soon"
message for these buttons instead of calling into this module.
"""
from __future__ import annotations
