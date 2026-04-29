"""
Telegram notification helper.

Set these environment variables before starting the server:
    TELEGRAM_BOT_TOKEN  — token from BotFather (e.g. 123456:ABC-DEF...)
    TELEGRAM_CHAT_ID    — your personal chat ID (get it by messaging your bot
                          and visiting https://api.telegram.org/bot<TOKEN>/getUpdates)

A cooldown prevents duplicate alerts for the same unknown person staying
on screen across many frames. The decision of *when* to call this — i.e.
loitering / confirmation gating — is the caller's responsibility (see
SurveillanceSystem.ingest, which fires only for loitering unknowns).
"""
import io
import os
import time
import logging

import numpy as np
import requests
from PIL import Image

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# Minimum seconds between notifications (prevents spam while unknown stays on screen)
COOLDOWN_SECONDS = 60

_last_notified_at: float = 0.0


def notify_unknown(
    face_crop: np.ndarray | None = None,
    on_sent=None,
) -> None:
    """
    Send a Telegram alert for an unknown person.

    Args:
        face_crop: Optional float32 (H, W, 3) array in [0, 1] — the cropped
                   face region. If provided it is sent as a photo with the alert.
        on_sent:   Optional zero-argument callable invoked when a notification
                   is actually dispatched (after the cooldown check).
                   Used by SurveillanceSystem to count real alerts.
    """
    global _last_notified_at

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            'Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.'
        )
        return

    now = time.time()

    # Cooldown: don't repeat the alert while the same person stays on screen
    if now - _last_notified_at < COOLDOWN_SECONDS:
        return

    _last_notified_at = now
    if on_sent is not None:
        on_sent()

    try:
        if face_crop is not None:
            _send_photo(face_crop, caption='⚠️ Alert: unknown person detected!')
        else:
            _send_message('⚠️ Alert: unknown person detected!')
    except Exception as exc:
        logger.error('Telegram notification failed: %s', exc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _send_message(text: str) -> None:
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    resp = requests.post(
        url,
        json={'chat_id': TELEGRAM_CHAT_ID, 'text': text},
        timeout=10,
    )
    resp.raise_for_status()


def _send_photo(face_crop: np.ndarray, caption: str) -> None:
    """Convert face array to JPEG and send via Telegram sendPhoto."""
    img_uint8 = (face_crop * 255).clip(0, 255).astype('uint8')
    pil_img = Image.fromarray(img_uint8)

    # Upscale small crops so the photo is readable in Telegram
    min_size = 240
    if pil_img.width < min_size or pil_img.height < min_size:
        scale = min_size / min(pil_img.width, pil_img.height)
        new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
        pil_img = pil_img.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()
    pil_img.save(buf, format='JPEG', quality=90)
    buf.seek(0)

    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto'
    resp = requests.post(
        url,
        data={'chat_id': TELEGRAM_CHAT_ID, 'caption': caption},
        files={'photo': ('face.jpg', buf, 'image/jpeg')},
        timeout=15,
    )
    resp.raise_for_status()
