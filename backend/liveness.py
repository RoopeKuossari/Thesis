"""
Liveness detection using MiniFASNet (DeepFace's Fasnet).

MiniFASNet is a lightweight anti-spoofing network trained by Minivision on a large
dataset of printed-photo and screen-replay attacks.  DeepFace 0.0.79+ bundles it;
model weights (~12 MB total) are downloaded automatically to ~/.deepface/weights/
on the first call.

The model requires the *full* original image and the face bounding box — not just
the face crop — because it internally applies multi-scale spatial patches (scale
factors 2.7× and 4.0×) around the box before classification.

Requires PyTorch (pip install torch).
"""
import numpy as np

# Confidence score threshold.  MiniFASNet outputs a softmax probability in [0, 1];
# values at or above this are treated as a real face.
# Lowering this value makes the check stricter (more spoofs caught but more false
# rejections); raising it makes it more permissive.
LIVENESS_THRESHOLD = 0.2

_model = None


def _get_model():
    global _model
    if _model is None:
        print('Loading anti-spoofing model (MiniFASNet)...')
        from deepface.models.spoofing.FasNet import Fasnet  # requires torch
        _model = Fasnet()
        print('Anti-spoofing model loaded.')
    return _model


def check_liveness(image: np.ndarray, box: list) -> dict:
    """
    Determine whether a detected face is a live person or a spoof attack.

    Args:
        image: Full RGB image as a uint8 numpy array of shape (H, W, 3).
               Must be the *original* frame — not the 160×160 face crop —
               so the model can sample context around the face at multiple scales.
        box:   Bounding box [x, y, w, h] in pixel coordinates, as returned by MTCNN.

    Returns:
        {
            'is_real':        bool   — True when liveness_score >= LIVENESS_THRESHOLD,
            'liveness_score': float  — model confidence (higher = more likely real),
        }
    """
    model = _get_model()
    is_real, score = model.analyze(image, tuple(box))
    return {
        'is_real':        bool(is_real),
        'liveness_score': round(float(score), 4),
    }
