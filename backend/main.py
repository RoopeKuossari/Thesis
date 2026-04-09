"""
FastAPI backend for face detection and identification.

Endpoints:
    POST /identify          — detect and identify all faces in an uploaded image
    POST /register          — register a person with one or more uploaded images
    DELETE /identities/{name} — remove a person from the gallery
    GET  /identities        — list all registered identities

Run:
    uvicorn backend.main:app --reload
"""
import io
import asyncio
import numpy as np
from PIL import Image, ImageOps
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response

from backend.recognizer import FaceRecognizer
from backend.notifier import notify_unknown
from backend.surveillance import SurveillanceSystem

app = FastAPI(title='Face Recognition API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

# Shared instances (model and gallery loaded once at startup)
recognizer   = FaceRecognizer()
surveillance = SurveillanceSystem(recognizer)


def decode_image(upload: UploadFile) -> np.ndarray:
    """Read an uploaded file and return a uint8 RGB numpy array."""
    data = upload.file.read()
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)   # handle phone camera EXIF rotation
    return np.array(img.convert('RGB'), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post('/identify')
async def identify(image: UploadFile = File(...)):
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
    name: str = Form(...),
    images: list[UploadFile] = File(...),
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
async def remove_identity(name: str):
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
# Surveillance endpoints
# ---------------------------------------------------------------------------

@app.post('/surveillance/start')
async def surveillance_start():
    """Activate the surveillance system (browser will start sending frames)."""
    surveillance.start()
    return {'active': surveillance.is_active}


@app.post('/surveillance/stop')
async def surveillance_stop():
    """Deactivate surveillance and clear the buffer."""
    surveillance.stop()
    return {'active': surveillance.is_active}


@app.post('/surveillance/ingest')
async def surveillance_ingest(image: UploadFile = File(...)):
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
    """Return the JPEG thumbnail for a specific highlight."""
    jpeg = surveillance.get_highlight_jpeg(highlight_id)
    if jpeg is None:
        raise HTTPException(status_code=404, detail='Highlight not found.')
    return Response(content=jpeg, media_type='image/jpeg',
                    headers={'Cache-Control': 'max-age=3600'})
