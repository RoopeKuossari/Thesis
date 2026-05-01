"""
FastAPI backend for face detection and identification.

Endpoints:
    POST   /auth/login                            — log in, receive httpOnly JWT cookie
    POST   /auth/logout                           — clear the auth cookie
    GET    /auth/me                               — return current user (auth check)
    GET    /auth/users                            — list users (admin)
    POST   /auth/users                            — create user (admin)
    DELETE /auth/users/{username}                 — delete user (admin)

    POST   /identify                              — detect and identify all faces in an uploaded image (admin)
    POST   /register                              — register a person with one or more uploaded images (admin)
    DELETE /identities/{name}                     — remove a person from the gallery (admin)
    GET    /identities                            — list all registered identities

    GET    /settings                              — current tunable settings
    PUT    /settings                              — update tunable settings (admin)

    POST   /surveillance/start                    — activate the surveillance system (admin)
    POST   /surveillance/stop                     — deactivate surveillance and flush to history (admin)
    POST   /surveillance/ingest                   — receive a JPEG frame from the browser (admin)
    GET    /surveillance/stream                   — MJPEG live stream
    GET    /surveillance/frame?t={ms}             — stored frame closest to timestamp
    GET    /surveillance/buffer                   — ring-buffer metadata
    GET    /surveillance/highlights               — live highlight list
    GET    /surveillance/highlight/{id}/image     — live highlight thumbnail

    GET    /history                               — list all saved sessions
    DELETE /history/{session_id}                  — delete a saved session (admin)
    GET    /history/{session_id}/frame?t={ms}     — stored frame from a past session
    GET    /history/{session_id}/highlights       — highlights for a past session
    GET    /history/{session_id}/highlight/{id}/image — thumbnail for a past highlight

Run:
    uvicorn backend.main:app --reload
"""
import io
import asyncio
import numpy as np
from PIL import Image, ImageOps
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response, JSONResponse

from backend import settings as settings_store
from backend.recognizer import FaceRecognizer
from backend.notifier import notify_unknown
from backend.surveillance import SurveillanceSystem
from backend.history import HistoryDB
from backend.auth import decode_token, require_admin
from backend.auth_router import router as auth_router

app = FastAPI(title='Face Recognition API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
    allow_credentials=True,
)

# ---------------------------------------------------------------------------
# Auth middleware — every route requires a valid JWT cookie except /auth/*
# (login itself doesn't need a cookie). Per-route admin checks live on the
# endpoints themselves via `Depends(require_admin)`.
# ---------------------------------------------------------------------------

@app.middleware('http')
async def require_auth(request: Request, call_next):
    if request.url.path.startswith('/auth/') or request.method == 'OPTIONS':
        return await call_next(request)

    token    = request.cookies.get('access_token')
    username = decode_token(token) if token else None

    if username is None:
        return JSONResponse(status_code=401, content={'detail': 'Not authenticated.'})

    return await call_next(request)

# Auth router (login / logout / me / user management)
app.include_router(auth_router)

# Shared instances (model and gallery loaded once at startup)
recognizer   = FaceRecognizer()
history_db   = HistoryDB()
surveillance = SurveillanceSystem(recognizer, db=history_db)


def decode_image(upload: UploadFile) -> np.ndarray:
    """Read an uploaded file and return a uint8 RGB numpy array."""
    data = upload.file.read()
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)   # handle phone camera EXIF rotation
    return np.array(img.convert('RGB'), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Identification & registration endpoints
# ---------------------------------------------------------------------------

@app.post('/identify')
async def identify(image: UploadFile = File(...), _: dict = Depends(require_admin)):
    """
    Detect and identify all faces in the uploaded image.

    Returns a list of detected faces with name, distance, bounding box,
    and detection confidence.
    """
    img = decode_image(image)
    results = recognizer.identify_image(img)
    for f in results:
        print(f'  identify: {f["name"]} distance={f["distance"]}')

    # Send Telegram alert only if there are unknowns and NO known person in frame
    has_known = any(f['name'] != 'Unknown' for f in results)
    if not has_known:
        for f in results:
            if f['name'] == 'Unknown':
                face_crop = recognizer.get_face_crop(img, f['box'])
                asyncio.get_event_loop().run_in_executor(
                    None, notify_unknown, face_crop
                )
                break  # one notification per frame is enough

    return {'faces': results}


@app.post('/register')
async def register(
    name:   str               = Form(...),
    images: list[UploadFile]  = File(...),
    _:      dict              = Depends(require_admin),
):
    """
    Register a person into the gallery using one or more uploaded images.
    Each image should contain exactly one face.
    """
    total = 0
    failed = 0
    for upload in images:
        img = decode_image(upload)
        n = recognizer.register(name, img)
        total += n
        if n == 0:
            failed += 1

    if total == 0:
        raise HTTPException(
            status_code=422,
            detail=f'No faces detected in any of the {len(images)} uploaded image(s).'
        )

    return {
        'name': name,
        'faces_registered': total,
        'images_with_no_face': failed,
        'gallery': recognizer.list_identities(),
    }


@app.delete('/identities/{name}')
async def remove_identity(name: str, _: dict = Depends(require_admin)):
    """Remove a person from the gallery."""
    removed = recognizer.remove(name)
    if not removed:
        raise HTTPException(status_code=404, detail=f'"{name}" not found in gallery.')
    return {'removed': name, 'gallery': recognizer.list_identities()}


@app.get('/identities')
async def list_identities():
    """Return all registered identities."""
    return {'identities': recognizer.list_identities()}


# ---------------------------------------------------------------------------
# Settings — live-tunable cooldowns and thresholds
# ---------------------------------------------------------------------------

@app.get('/settings')
async def get_settings():
    """Return the current tunable settings."""
    return {
        'settings': settings_store.get_all(),
        'defaults': settings_store.DEFAULTS,
        'schema':   {
            k: {'min': lo, 'max': hi, 'type': typ.__name__}
            for k, (_, typ, lo, hi) in settings_store.SCHEMA.items()
        },
    }


@app.put('/settings')
async def update_settings(body: dict, _: dict = Depends(require_admin)):
    """Apply a partial settings update. Unknown keys / out-of-bounds values raise 400."""
    try:
        new_state = settings_store.update(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {'settings': new_state}


# ---------------------------------------------------------------------------
# Live surveillance endpoints
# ---------------------------------------------------------------------------

@app.post('/surveillance/start')
async def surveillance_start(_: dict = Depends(require_admin)):
    """Activate the surveillance system (browser will start sending frames)."""
    surveillance.start()
    return {'active': surveillance.is_active}


@app.post('/surveillance/stop')
async def surveillance_stop(_: dict = Depends(require_admin)):
    """Deactivate surveillance, flush session to history, and clear the buffer."""
    surveillance.stop()
    return {'active': surveillance.is_active}


@app.post('/surveillance/ingest')
async def surveillance_ingest(
    image: UploadFile = File(...),
    _:     dict       = Depends(require_admin),
):
    """Receive a JPEG frame captured by the browser, process and store it."""
    data = await image.read()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, surveillance.ingest, data)
    return {'ok': True}


@app.get('/surveillance/status')
async def surveillance_status():
    """Return active state and buffer info."""
    info = surveillance.get_buffer_info()
    return {'active': surveillance.is_active, **info}


@app.get('/surveillance/stream')
async def surveillance_stream():
    """MJPEG stream of live annotated frames."""
    async def generate():
        while surveillance.is_active:
            jpeg = surveillance.get_latest_jpeg()
            if jpeg:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n'
                    + jpeg +
                    b'\r\n'
                )
            await asyncio.sleep(1 / 30)

    return StreamingResponse(
        generate(),
        media_type='multipart/x-mixed-replace; boundary=frame',
        headers={'Cache-Control': 'no-cache'},
    )


@app.get('/surveillance/frame')
async def surveillance_frame(t: int = Query(..., description='Unix timestamp in ms')):
    """Return the stored JPEG frame closest to the given timestamp."""
    jpeg = surveillance.get_frame_at(t)
    if jpeg is None:
        raise HTTPException(status_code=404, detail='No frame available at that time.')
    return Response(content=jpeg, media_type='image/jpeg',
                    headers={'Cache-Control': 'no-cache'})


@app.get('/surveillance/buffer')
async def surveillance_buffer():
    """Return ring-buffer metadata: start/end timestamps and frame count."""
    return surveillance.get_buffer_info()


@app.get('/surveillance/highlights')
async def surveillance_highlights():
    """Return all highlight events for the current session (no image data)."""
    return {'highlights': surveillance.get_highlights()}


@app.get('/surveillance/highlight/{highlight_id}/image')
async def surveillance_highlight_image(highlight_id: str):
    """Return the JPEG thumbnail for a specific live highlight."""
    jpeg = surveillance.get_highlight_jpeg(highlight_id)
    if jpeg is None:
        raise HTTPException(status_code=404, detail='Highlight not found.')
    return Response(content=jpeg, media_type='image/jpeg',
                    headers={'Cache-Control': 'max-age=3600'})


# ---------------------------------------------------------------------------
# History endpoints — past sessions stored on disk
# ---------------------------------------------------------------------------

@app.get('/history')
async def history_list():
    """List all completed surveillance sessions, newest first."""
    return {'sessions': history_db.list_sessions()}


@app.delete('/history/{session_id}')
async def history_delete(session_id: str, _: dict = Depends(require_admin)):
    """Permanently remove a saved session and all of its frames + thumbnails."""
    if not history_db.delete_session(session_id):
        raise HTTPException(status_code=404, detail='Session not found.')
    return {'ok': True}


@app.get('/history/{session_id}/frame')
async def history_frame(
    session_id: str,
    t: int = Query(..., description='Unix timestamp in ms'),
):
    """Return the stored JPEG frame from a past session closest to timestamp t."""
    path = history_db.get_frame_at(session_id, t)
    if path is None:
        raise HTTPException(status_code=404, detail='Frame not found.')
    return Response(content=path.read_bytes(), media_type='image/jpeg',
                    headers={'Cache-Control': 'no-cache'})


@app.get('/history/{session_id}/highlights')
async def history_highlights(session_id: str):
    """Return all highlights for a past session."""
    session = history_db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found.')
    return {'highlights': history_db.get_highlights(session_id)}


@app.get('/history/{session_id}/highlight/{highlight_id}/image')
async def history_highlight_image(session_id: str, highlight_id: str):
    """Return the JPEG thumbnail for a highlight in a past session."""
    path = history_db.get_highlight_thumb_path(session_id, highlight_id)
    if path is None:
        raise HTTPException(status_code=404, detail='Highlight image not found.')
    return Response(content=path.read_bytes(), media_type='image/jpeg',
                    headers={'Cache-Control': 'max-age=3600'})
