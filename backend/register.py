"""
Register a person into the face gallery.

Usage:
    python backend/register.py --name "Roope" --images path/to/photo1.jpg path/to/photo2.jpg
"""
import argparse
import numpy as np
from PIL import Image, ImageOps

from backend.recognizer import FaceRecognizer


def load_rgb(path: str) -> np.ndarray:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # honour EXIF rotation from phone cameras
    return np.array(img.convert('RGB'), dtype=np.uint8)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True, help='Name of the person to register')
    parser.add_argument('--images', nargs='+', required=True, help='Paths to photos')
    args = parser.parse_args()

    recognizer = FaceRecognizer()
    total = 0
    for img_path in args.images:
        image = load_rgb(img_path)
        n = recognizer.register(args.name, image)
        total += n

    print(f'\nDone. Registered {total} face(s) for "{args.name}".')
    print(f'Gallery identities: {recognizer.list_identities()}')
