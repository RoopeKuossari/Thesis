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
# A "scene" is one continuous interval where someone is in frame. The scene
# ends only when nobody (known or unknown) has been seen for SCENE_GRACE
# seconds — brief gaps don't split a single scene into two highlights.
# The same grace also drives unknown-group loitering tracking and spoof
# stamp dedup.
SCENE_GRACE       = 5.0
HIGHLIGHT_THUMB_W = 480     # thumbnail width stored per highlight

# Loitering — an unknown is flagged as loitering after staying continuously
# in frame for this many seconds. Telegram alerts only fire for loitering
# unknowns when no known person is present.
LOITERING_SECONDS = 5.0

# Grace period after a known person was last seen — alerts are suppressed
# during this window even if the known person has left frame, on the
# assumption that they may briefly step out (e.g. with a guest still present).
KNOWN_GRACE_SECONDS = 60.0


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

        # Active scene state — one open interval highlight at a time. Scene
        # category flips in place between known/unknown/mixed_unknown as
        # people come and go (with SCENE_GRACE smoothing brief gaps).
        self._scene_id:           str | None = None
        self._scene_category:     str | None = None
        self._scene_primary_name: str | None = None
        self._scene_last_known:   float      = 0.0
        self._scene_last_unknown: float      = 0.0

        # Spoof stamp dedup — a new orange highlight is only created if no
        # spoof has been seen for at least SCENE_GRACE seconds.
        self._spoof_last_seen: float = 0.0

        # Unknown-group tracking — drives the loitering alert gate. Kept
        # separate from the scene state because the alert logic needs its
        # own continuous-presence timer.
        self._unk_last_seen:  float = 0.0
        self._unk_active:     bool  = False
        self._unk_first_seen: float = 0.0

        # Last time any known person was in frame — drives the alert grace period
        self._last_known_seen_at: float = 0.0

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
        self._scene_id           = None
        self._scene_category     = None
        self._scene_primary_name = None
        self._scene_last_known   = 0.0
        self._scene_last_unknown = 0.0
        self._spoof_last_seen    = 0.0
        self._unk_last_seen      = 0.0
        self._unk_active         = False
        self._unk_first_seen     = 0.0
        self._last_known_seen_at = 0.0
        self._frame_count        = 0
        self._alert_count        = 0

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
        now = time.time()

        # Update the unknown-group state machine first so the loitering check
        # below sees this frame's data (no off-by-one frame).
        self._update_unknown_group(faces, now)

        # Loitering — an unknown is loitering once the unknown group has been
        # continuously present for LOITERING_SECONDS.
        unk_loitering = (
            self._unk_active
            and self._unk_first_seen > 0.0
            and (now - self._unk_first_seen) >= LOITERING_SECONDS
        )
        for f in faces:
            f['is_loitering'] = (f['name'] == 'Unknown' and unk_loitering)

        # Track when a known person was last in frame — drives the alert grace.
        # Spoof faces are excluded.
        has_known = any(f['name'] not in ('Unknown', 'Spoof') for f in faces)
        if has_known:
            self._last_known_seen_at = now

        # Telegram alert — only when an unknown is loitering AND no known
        # person has been in frame within KNOWN_GRACE_SECONDS. The grace check
        # subsumes "currently in frame" (timestamp would be `now`, so the
        # elapsed value is 0).
        # on_sent increments the real alert counter only when the notification
        # actually fires (after the cooldown check in notifier.py).
        known_recent = (now - self._last_known_seen_at) < KNOWN_GRACE_SECONDS
        if unk_loitering and not known_recent:
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

        # Annotate frame (draws on img, returns JPEG bytes)
        annotated_jpeg = self._annotate(img, faces, now)

        # Update interval scene + spoof stamps (uses the annotated img for thumbs)
        self._update_highlights(faces, img, now)

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
                    'end_t':    h['end_t'],
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
    # Unknown-group tracking (drives the loitering alert)
    # ------------------------------------------------------------------

    def _update_unknown_group(self, faces: list, now: float):
        """
        Maintain `_unk_active` / `_unk_first_seen` / `_unk_last_seen` for the
        loitering alert gate. Independent of the scene/highlight tracker.
        """
        has_unknown = any(f['name'] == 'Unknown' for f in faces)
        if has_unknown:
            self._unk_last_seen = now
            if not self._unk_active:
                self._unk_active     = True
                self._unk_first_seen = now
        else:
            if self._unk_active and (now - self._unk_last_seen) > SCENE_GRACE:
                self._unk_active     = False
                self._unk_first_seen = 0.0

    # ------------------------------------------------------------------
    # Highlight tracking — interval scenes + spoof stamps
    # ------------------------------------------------------------------

    def _update_highlights(self, faces: list, img: Image.Image, now: float):
        """
        Drive a single open scene highlight that flips between green / red /
        yellow as known/unknown people come and go (with SCENE_GRACE smoothing
        brief gaps). Spoofs are emitted as standalone orange stamps.
        """
        has_known   = any(f['name'] not in ('Unknown', 'Spoof') for f in faces)
        has_unknown = any(f['name'] == 'Unknown' for f in faces)
        has_spoof   = any(f['name'] == 'Spoof' for f in faces)

        primary_known = next(
            (f['name'] for f in faces if f['name'] not in ('Unknown', 'Spoof')),
            None,
        )

        # Refresh per-class last-seen timestamps
        if has_known:
            self._scene_last_known = now
        if has_unknown:
            self._scene_last_unknown = now

        known_recent = (
            self._scene_last_known > 0.0
            and (now - self._scene_last_known) < SCENE_GRACE
        )
        unknown_recent = (
            self._scene_last_unknown > 0.0
            and (now - self._scene_last_unknown) < SCENE_GRACE
        )

        # --- Scene state machine ---
        # Each colour change closes the current highlight and opens a new one,
        # so the timeline shows distinct cards per segment (e.g. green → yellow
        # → green produces three separate highlights).
        if known_recent or unknown_recent:
            if known_recent and unknown_recent:
                new_category = 'mixed_unknown'
            elif known_recent:
                new_category = 'known'
            else:
                new_category = 'unknown'

            if self._scene_id is None:
                # Open the first segment of a fresh scene
                self._scene_id           = self._next_hl_id()
                self._scene_category     = new_category
                self._scene_primary_name = primary_known
                self._add_scene_highlight(
                    self._scene_id, new_category, primary_known, img, now,
                )
            elif new_category != self._scene_category:
                # Category transition — close the current segment at `now`,
                # then open a new segment that begins immediately at `now`.
                self._update_scene_end_t(self._scene_id, now)

                # Carry the known name forward on transitions that still
                # involve a known person; drop to None for unknown-only.
                if new_category == 'unknown':
                    new_primary = None
                else:
                    new_primary = (
                        primary_known
                        if primary_known is not None
                        else self._scene_primary_name
                    )

                self._scene_id           = self._next_hl_id()
                self._scene_category     = new_category
                self._scene_primary_name = new_primary
                self._add_scene_highlight(
                    self._scene_id, new_category, new_primary, img, now,
                )
            else:
                # Same category — live-update end_t every frame
                self._update_scene_end_t(self._scene_id, now)

                # Backfill the primary name if the segment started without a
                # known person (e.g. unknown-only segment that now also has a
                # named person — the next tick may flip to mixed_unknown).
                if self._scene_primary_name is None and primary_known is not None:
                    self._scene_primary_name = primary_known
                    self._update_scene_name(self._scene_id, primary_known)
        else:
            # Nobody seen for >SCENE_GRACE — finalize the scene
            if self._scene_id is not None:
                end_t = max(self._scene_last_known, self._scene_last_unknown)
                self._update_scene_end_t(self._scene_id, end_t)
                label = self._scene_primary_name or 'unknown'
                ts    = datetime.fromtimestamp(end_t).strftime('%H:%M:%S')
                print(f'[highlight] scene end · {self._scene_category} · {label} · {ts}')
                self._scene_id           = None
                self._scene_category     = None
                self._scene_primary_name = None
                self._scene_last_known   = 0.0
                self._scene_last_unknown = 0.0

        # --- Spoof stamps (parallel, point-in-time) ---
        if has_spoof:
            if (now - self._spoof_last_seen) >= SCENE_GRACE:
                self._add_spoof_stamp(img, now)
            self._spoof_last_seen = now

    # ------------------------------------------------------------------
    # Highlight helpers — create / update in memory + DB
    # ------------------------------------------------------------------

    def _next_hl_id(self) -> str:
        with self._hl_lock:
            self._hl_counter += 1
            return str(self._hl_counter)

    def _make_thumb(self, img: Image.Image) -> bytes:
        w, h  = img.size
        new_h = int(h * HIGHLIGHT_THUMB_W / w)
        thumb = img.resize((HIGHLIGHT_THUMB_W, new_h), Image.BILINEAR)
        buf   = io.BytesIO()
        thumb.save(buf, format='JPEG', quality=80)
        return buf.getvalue()

    def _add_scene_highlight(
        self,
        hl_id:    str,
        category: str,
        name:     str | None,
        img:      Image.Image,
        start_t:  float,
    ):
        thumb_bytes = self._make_thumb(img)
        start_ms    = int(start_t * 1000)
        with self._hl_lock:
            self._highlights.append({
                'id':       hl_id,
                't':        start_ms,
                'end_t':    start_ms,
                'category': category,
                'name':     name,
                'jpeg':     thumb_bytes,
            })

        if self._db is not None and self._session_id is not None:
            thumb_path = self._db.highlight_thumb_dir(self._session_id) / f'{hl_id}.jpg'
            thumb_path.write_bytes(thumb_bytes)
            self._db.add_highlight(
                session_id   = self._session_id,
                highlight_id = hl_id,
                t            = start_ms,
                end_t        = start_ms,
                category     = category,
                name         = name,
                thumb_path   = thumb_path,
            )

        label = name or 'unknown'
        ts    = datetime.fromtimestamp(start_t).strftime('%H:%M:%S')
        print(f'[highlight] scene start · {category} · {label} · {ts} (id={hl_id})')

    def _update_scene_end_t(self, hl_id: str, end_t: float):
        end_ms = int(end_t * 1000)
        with self._hl_lock:
            for h in self._highlights:
                if h['id'] == hl_id:
                    h['end_t'] = end_ms
                    break
        if self._db is not None and self._session_id is not None:
            self._db.update_highlight(
                session_id   = self._session_id,
                highlight_id = hl_id,
                end_t        = end_ms,
            )

    def _update_scene_name(self, hl_id: str, name: str):
        with self._hl_lock:
            for h in self._highlights:
                if h['id'] == hl_id:
                    h['name'] = name
                    break
        if self._db is not None and self._session_id is not None:
            self._db.update_highlight(
                session_id   = self._session_id,
                highlight_id = hl_id,
                name         = name,
            )

    def _add_spoof_stamp(self, img: Image.Image, now: float):
        hl_id       = self._next_hl_id()
        thumb_bytes = self._make_thumb(img)
        ts_ms       = int(now * 1000)
        with self._hl_lock:
            self._highlights.append({
                'id':       hl_id,
                't':        ts_ms,
                'end_t':    ts_ms,
                'category': 'spoof',
                'name':     None,
                'jpeg':     thumb_bytes,
            })

        if self._db is not None and self._session_id is not None:
            thumb_path = self._db.highlight_thumb_dir(self._session_id) / f'{hl_id}.jpg'
            thumb_path.write_bytes(thumb_bytes)
            self._db.add_highlight(
                session_id   = self._session_id,
                highlight_id = hl_id,
                t            = ts_ms,
                end_t        = ts_ms,
                category     = 'spoof',
                name         = None,
                thumb_path   = thumb_path,
            )

        ts_str = datetime.fromtimestamp(now).strftime('%H:%M:%S')
        print(f'[highlight] spoof stamp · {ts_str} (id={hl_id})')

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
                label = 'Unknown (loitering)' if face.get('is_loitering') else 'Unknown'
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
