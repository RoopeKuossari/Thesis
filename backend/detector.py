import numpy as np
from mtcnn import MTCNN
from PIL import Image

# MTCNN outputs face regions; we resize them to match the embedding network input
FACE_SIZE = (160, 160)

# Minimum confidence to accept a detected face
MIN_CONFIDENCE = 0.90

_detector = None


def get_detector():
    """Lazy-load the MTCNN detector (heavy to initialise)."""
    global _detector
    if _detector is None:
        _detector = MTCNN()
    return _detector


def detect_and_crop(image: np.ndarray) -> list[dict]:
    """
    Detect all faces in an image and return cropped, resized face arrays.

    Args:
        image: RGB numpy array of shape (H, W, 3), uint8.

    Returns:
        List of dicts, one per detected face:
            {
                'face':       np.ndarray (160, 160, 3) float32 in [0, 1],
                'box':        [x, y, w, h]  — bounding box in the original image,
                'confidence': float          — MTCNN detection confidence,
                'keypoints':  dict           — facial landmark coordinates,
            }
        Empty list if no face meets the confidence threshold.
    """
    detector = get_detector()
    detections = detector.detect_faces(image)

    if not detections:
        print(f'  [detector] No faces found in image of shape {image.shape}')
    else:
        for i, d in enumerate(detections):
            print(f'  [detector] Face {i+1}: confidence={d["confidence"]:.3f}, box={d["box"]}')

    results = []
    img_h, img_w = image.shape[:2]

    for det in detections:
        if det['confidence'] < MIN_CONFIDENCE:
            continue

        x, y, w, h = det['box']

        # Clamp to image bounds (MTCNN can return slightly negative coords)
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(img_w, x + w)
        y2 = min(img_h, y + h)

        if x2 <= x1 or y2 <= y1:
            continue

        crop = image[y1:y2, x1:x2]
        face_pil = Image.fromarray(crop).resize(FACE_SIZE, Image.BILINEAR)
        face = np.array(face_pil, dtype=np.float32) / 255.0

        results.append({
            'face': face,
            'box': [x1, y1, x2 - x1, y2 - y1],
            'confidence': det['confidence'],
            'keypoints': det['keypoints'],
        })

    return results
