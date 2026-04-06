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
import numpy as np
from PIL import Image, ImageOps
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.recognizer import FaceRecognizer

app = FastAPI(title='Face Recognition API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

# Single shared recognizer instance (loads model and gallery once at startup)
recognizer = FaceRecognizer()


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
