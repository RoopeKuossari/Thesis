"""
Live-tunable system settings.

The defaults below are baked into the code; admins can override any of them
at runtime through the `/settings` endpoint. Overrides are persisted to
`storage/settings.json` so they survive a server restart.

Modules that use these values read them through `get(...)` on every call,
so updates take effect on the next frame without restarting anything.
"""
import json
from pathlib import Path
from threading import Lock

SETTINGS_PATH = Path('storage/settings.json')

# Each entry: (default, type, min, max). Bounds are inclusive and used by
# the API to reject obviously broken values.
SCHEMA: dict[str, tuple] = {
    # FaceRecognizer — distance cut-off above which a match is treated as
    # Unknown. ArcFace cosine distance is in [0, 2]; 0.9 is conservative.
    'identity_threshold':      (0.9,  float, 0.1,  2.0),

    # SurveillanceSystem — seconds of "no faces" allowed before the current
    # scene/loitering interval is considered ended.
    'scene_grace':             (5.0,  float, 0.5,  60.0),

    # SurveillanceSystem — continuous unknown presence required before the
    # loitering flag (and Telegram alert) trips.
    'loitering_seconds':       (5.0,  float, 0.5,  120.0),

    # SurveillanceSystem — alerts are suppressed while a known person was
    # seen this recently, on the assumption they're hosting a guest.
    'known_grace_seconds':     (60.0, float, 0.0,  600.0),

    # Notifier — minimum gap between Telegram alerts for the same loitering
    # unknown across many frames.
    'alert_cooldown_seconds':  (60,   int,   0,    3600),
}

DEFAULTS: dict = {k: v[0] for k, v in SCHEMA.items()}

_lock  = Lock()
_state: dict = dict(DEFAULTS)


def _load_from_disk() -> None:
    """Merge any persisted overrides on top of the defaults."""
    if not SETTINGS_PATH.exists():
        return
    try:
        data = json.loads(SETTINGS_PATH.read_text())
    except Exception as exc:
        print(f'[settings] Could not read {SETTINGS_PATH}: {exc}')
        return
    with _lock:
        for k in DEFAULTS:
            if k in data:
                _state[k] = SCHEMA[k][1](data[k])


def _persist() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(_state, indent=2))


def get(key: str):
    with _lock:
        return _state[key]


def get_all() -> dict:
    with _lock:
        return dict(_state)


def update(values: dict) -> dict:
    """
    Validate and apply a partial update. Unknown keys are rejected. Each
    value is coerced to its declared type and bounds-checked.
    Returns the full new state.
    """
    with _lock:
        for key, raw in values.items():
            if key not in SCHEMA:
                raise ValueError(f'Unknown setting: {key}')
            _, typ, lo, hi = SCHEMA[key]
            try:
                value = typ(raw)
            except (TypeError, ValueError):
                raise ValueError(f'{key} must be {typ.__name__}')
            if not (lo <= value <= hi):
                raise ValueError(f'{key} must be between {lo} and {hi}')
            _state[key] = value
        _persist()
        return dict(_state)


_load_from_disk()
