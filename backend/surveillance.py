"""
Surveillance system: receives JPEG frames from the browser, runs face recognition,
annotates them, stores in a ring buffer for live streaming and DVR rewind, and
tracks person entry events to generate highlights.

All annotated frames and highlight thumbnails are also persisted to disk by
HistoryDB so that past sessions can be reviewed on the History tab.
"""
import io
import time
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from backend.notifier import notify_unknown

BUFFER_SECONDS = 600       # 10 minutes of footage in ring buffer

# Highlight settings
DEPARTURE_GRACE    = 5.0    # seconds a person can be absent before counted as "left"
HIGHLIGHT_COOLDOWN = 180.0  # seconds before the same person can generate another highlight
HIGHLIGHT_THUMB_W  = 480    # thumbnail width stored per highlight


class SurveillanceSystem:
    def __init__(self, recognizer, db=None):
        """
        Args:
            recognizer: FaceRecognizer instance (shared with the API).
            db:         Optional HistoryDB instance. When provided every session
                        is persisted to disk and SQLite for later review.
        """
        self.recognizer = recognizer
        self._db = db
        self._active = False
        self._lock = threading.Lock()
        self._buffer: deque = deque()
        self._latest_jpeg: bytes | None = None

        try:
            self._font = ImageFont.load_default(size=15)
        except TypeError:
            self._font = ImageFont.load_default()

        # Highlights list and its own lock
        self._highlights: list = []
        self._hl_lock = threading.Lock()
        self._hl_counter = 0

        # Known-person entry/departure tracking
        self._kn_last_seen: dict[str, float] = {}  # name → last seen timestamp
        self._kn_departed:  dict[str, float] = {}  # name → departure timestamp
        self._kn_active:    set[str] = set()        # names currently in frame

        # Unknown-group tracking (unknowns treated as a single group)
        self._unk_last_seen:   float = 0.0
        self._unk_departed_at: float = 0.0
        self._unk_active:      bool  = False

        # History / persistence state
        self._session_id:  str | None  = None
        self._frames_dir:  Path | None = None
        self._frame_count: int         = 0
        self._alert_count: int         = 0

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def start(self):
        # Purge sessions older than the retention window before starting a new one
        if self._db is not None:
            self._db.purge_old_sessions()

        self._active = True

        # Fresh session: clear highlights and reset tracking state
        with self._hl_lock:
            self._highlights.clear()
            self._hl_counter = 0
        self._kn_last_seen.clear()
        self._kn_departed.clear()
        self._kn_active.clear()
        self._unk_last_seen   = 0.0
        self._unk_departed_at = 0.0
        self._unk_active      = False
        self._frame_count     = 0
        self._alert_count     = 0

        # Create a new DB session and on-disk directory
        if self._db is not None:
            now_ms = int(time.time() * 1000)
            self._session_id = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            self._frames_dir = self._db.create_session(self._session_id, now_ms)
            print(f'[history] Session started: {self._session_id}')

    def stop(self):
        self._active = False

        # Persist final counts to DB
        if self._db is not None and self._session_id is not None:
            with self._hl_lock:
                hl_count = len(self._highlights)
            self._db.end_session(
                session_id      = self._session_id,
                ended_at        = int(time.time() * 1000),
                frame_count     = self._frame_count,
                highlight_count = hl_count,
                alert_count     = self._alert_count,
            )
            print(f'[history] Session ended: {self._session_id} '
                  f'({self._frame_count} frames, {hl_count} highlights, '
                  f'{self._alert_count} alerts)')

        self._session_id = None
        self._frames_dir = None

        with self._lock:
            self._buffer.clear()
            self._latest_jpeg = None

    @property
    def is_active(self) -> bool:
        return self._active

    # ------------------------------------------------------------------
    # Ingest — called by the API endpoint for each browser frame
    # ------------------------------------------------------------------

    def ingest(self, jpeg_bytes: bytes) -> list[dict]:
        """
        Decode a browser-captured JPEG, run recognition, annotate,
        store in the ring buffer, persist to disk, and update highlights.
        """
        if not self._active:
            return []

        img = Image.open(io.BytesIO(jpeg_bytes)).convert('RGB')
        frame_rgb = np.array(img, dtype=np.uint8)

        faces = self.recognizer.identify_image(frame_rgb)

        # Telegram alert — only when no known person is in frame.
        # Spoof faces are excluded from both the known-person check and alert
        # triggering; only real unknown faces can fire the notification.
        # on_sent increments the real alert counter only when the notification
        # actually fires (after confirm window and cooldown checks).
        has_known = any(f['name'] not in ('Unknown', 'Spoof') for f in faces)
        if not has_known:
            for f in faces:
                if f['name'] == 'Unknown':
                    crop = self.recognizer.get_face_crop(frame_rgb, f['box'])
                    threading.Thread(
                        target=notify_unknown,
                        args=(crop,),
                        kwargs={'on_sent': self._on_alert_sent},
                        daemon=True,
                    ).start()
                    break

        now = time.time()

        # Annotate frame (draws on img, returns JPEG bytes)
        annotated_jpeg = self._annotate(img, faces, now)

        # Highlight event detection (uses the annotated img)
        self._check_highlights(faces, img, now)

        # Save annotated frame to disk for history
        if self._frames_dir is not None:
            ts_ms = int(now * 1000)
            frame_path = self._frames_dir / f'{ts_ms}.jpg'
            frame_path.write_bytes(annotated_jpeg)
            self._frame_count += 1

        # Store in ring buffer
        cutoff = now - BUFFER_SECONDS
        with self._lock:
            self._latest_jpeg = annotated_jpeg
            self._buffer.append({'t': now, 'jpeg': annotated_jpeg})
            while self._buffer and self._buffer[0]['t'] < cutoff:
                self._buffer.popleft()

        return faces

    def _on_alert_sent(self):
        """Called by notify_unknown when a Telegram notification is actually sent."""
        self._alert_count += 1

    # ------------------------------------------------------------------
    # Data access — buffer
    # ------------------------------------------------------------------

    def get_latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def get_frame_at(self, timestamp_ms: int) -> bytes | None:
        target = timestamp_ms / 1000.0
        with self._lock:
            if not self._buffer:
                return None
            best = min(self._buffer, key=lambda e: abs(e['t'] - target))
            return best['jpeg']

    def get_buffer_info(self) -> dict:
        with self._lock:
            if not self._buffer:
                return {'start': None, 'end': None, 'frames': 0}
            return {
                'start':  int(self._buffer[0]['t'] * 1000),
                'end':    int(self._buffer[-1]['t'] * 1000),
                'frames': len(self._buffer),
            }

    # ------------------------------------------------------------------
    # Data access — highlights
    # ------------------------------------------------------------------

    def get_highlights(self) -> list[dict]:
        """Return highlight metadata (no JPEG bytes)."""
        with self._hl_lock:
            return [
                {
                    'id':       h['id'],
                    't':        h['t'],
                    'category': h['category'],
                    'name':     h['name'],
                }
                for h in self._highlights
            ]

    def get_highlight_jpeg(self, highlight_id: str) -> bytes | None:
        with self._hl_lock:
            for h in self._highlights:
                if h['id'] == highlight_id:
                    return h['jpeg']
        return None

    # ------------------------------------------------------------------
    # Highlight event detection
    # ------------------------------------------------------------------

    def _check_highlights(self, faces: list, img: Image.Image, now: float):
        # Spoof faces are excluded from all highlight and tracking logic —
        # they are not real persons so they must not generate entry events.
        current_known      = {f['name'] for f in faces if f['name'] not in ('Unknown', 'Spoof')}
        has_unknown        = any(f['name'] == 'Unknown' for f in faces)
        has_known_in_frame = bool(current_known)

        # --- Known persons ---
        for name in current_known:
            self._kn_last_seen[name] = now

        for name in current_known:
            if name not in self._kn_active:
                departed_at = self._kn_departed.get(name, 0.0)
                if now - departed_at >= HIGHLIGHT_COOLDOWN:
                    self._add_highlight(name, 'known', img, now)
                self._kn_active.add(name)

        for name in list(self._kn_active):
            if now - self._kn_last_seen.get(name, 0.0) > DEPARTURE_GRACE:
                self._kn_active.discard(name)
                self._kn_departed[name] = now

        # --- Unknown group ---
        if has_unknown:
            self._unk_last_seen = now
            if not self._unk_active:
                if now - self._unk_departed_at >= HIGHLIGHT_COOLDOWN:
                    category = 'mixed_unknown' if has_known_in_frame else 'unknown'
                    self._add_highlight(None, category, img, now)
                self._unk_active = True
        else:
            if self._unk_active and now - self._unk_last_seen > DEPARTURE_GRACE:
                self._unk_active      = False
                self._unk_departed_at = now

    def _add_highlight(
        self,
        name:     str | None,
        category: str,
        img:      Image.Image,
        frame_t:  float,
    ):
        # Resize to thumbnail
        w, h  = img.size
        new_h = int(h * HIGHLIGHT_THUMB_W / w)
        thumb = img.resize((HIGHLIGHT_THUMB_W, new_h), Image.BILINEAR)
        buf   = io.BytesIO()
        thumb.save(buf, format='JPEG', quality=80)
        thumb_bytes = buf.getvalue()

        with self._hl_lock:
            self._hl_counter += 1
            highlight_id = str(self._hl_counter)
            self._highlights.append({
                'id':       highlight_id,
                't':        int(frame_t * 1000),
                'category': category,
                'name':     name,
                'jpeg':     thumb_bytes,
            })

        # Persist thumbnail to disk and record in DB
        if self._db is not None and self._session_id is not None:
            thumb_dir  = self._db.highlight_thumb_dir(self._session_id)
            thumb_path = thumb_dir / f'{highlight_id}.jpg'
            thumb_path.write_bytes(thumb_bytes)
            self._db.add_highlight(
                session_id   = self._session_id,
                highlight_id = highlight_id,
                t            = int(frame_t * 1000),
                category     = category,
                name         = name,
                thumb_path   = thumb_path,
            )

        label = name or 'unknown'
        ts    = datetime.fromtimestamp(frame_t).strftime('%H:%M:%S')
        print(f'[highlight] {category} · {label} · {ts}')

    # ------------------------------------------------------------------
    # Frame annotation
    # ------------------------------------------------------------------

    def _annotate(self, img: Image.Image, faces: list, frame_t: float) -> bytes:
        """Draw face boxes, labels, and a timestamp onto img; return JPEG bytes."""
        draw = ImageDraw.Draw(img)

        for face in faces:
            x, y, w, h = face['box']
            if face['name'] == 'Spoof':
                color = '#ff9100'
                label = f"Spoof ({face['liveness_score']:.2f})"
            elif face['name'] == 'Unknown':
                color = '#ff1744'
                label = 'Unknown'
            else:
                color = '#00e676'
                label = f"{face['name']} ({face['distance']:.2f})"

            draw.rectangle([x, y, x + w, y + h], outline=color, width=3)

            lw = len(label) * 9 + 8
            lh = 20
            ty = max(0, y - lh)
            draw.rectangle([x, ty, x + lw, ty + lh], fill=color)
            draw.text((x + 4, ty + 3), label, fill='black', font=self._font)

        # Timestamp — bottom-right corner
        ts = datetime.fromtimestamp(frame_t).strftime('%d.%m.%Y  %H:%M')
        tw = len(ts) * 9 + 8
        th = 20
        tx = img.width  - tw - 8
        ty = img.height - th - 8
        draw.rectangle([tx, ty, tx + tw, ty + th], fill=(20, 20, 20))
        draw.text((tx + 4, ty + 3), ts, fill=(220, 220, 220), font=self._font)

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        return buf.getvalue()
