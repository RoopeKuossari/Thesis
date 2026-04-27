import json
import numpy as np
from pathlib import Path
from deepface import DeepFace

from backend.detector import detect_and_crop

GALLERY_PATH = 'model/gallery.json'

# ArcFace is one of the strongest pretrained face recognition models.
# Other options: "Facenet512", "VGG-Face", "GhostFaceNet"
EMBEDDING_MODEL_NAME = 'ArcFace'

# Distance threshold for ArcFace cosine distance (range 0–2).
# ArcFace embeddings are L2-normalised; 0.68 is the standard LFW threshold.
IDENTITY_THRESHOLD = 0.9


class FaceRecognizer:
    """
    Combines MTCNN face detection with a pretrained ArcFace embedding model
    to detect and identify faces in images.

    The gallery stores one mean embedding per registered person.
    Identification uses nearest-neighbour search with a distance threshold.
    """

    def __init__(
        self,
        gallery_path: str = GALLERY_PATH,
        threshold: float = IDENTITY_THRESHOLD,
        model_name: str = EMBEDDING_MODEL_NAME,
    ):
        self.model_name = model_name
        self.threshold = threshold
        self.gallery_path = Path(gallery_path)

        # Warm up DeepFace (downloads weights on first run)
        print(f'Loading {model_name} embedding model...')
        DeepFace.build_model(model_name)

        self.gallery: dict[str, np.ndarray] = {}
        if self.gallery_path.exists():
            self._load_gallery()

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def embed(self, face: np.ndarray) -> np.ndarray:
        """
        Compute the L2-normalised embedding for a single face crop.

        Args:
            face: float32 array of shape (160, 160, 3) in [0, 1].

        Returns:
            1-D float32 array.
        """
        # DeepFace expects uint8 in [0, 255]
        img_uint8 = (face * 255).astype(np.uint8)
        result = DeepFace.represent(
            img_path=img_uint8,
            model_name=self.model_name,
            enforce_detection=False,  # face already cropped by MTCNN
            detector_backend='skip',
        )
        embedding = np.array(result[0]['embedding'], dtype=np.float32)
        # L2-normalise so cosine similarity = dot product
        return embedding / (np.linalg.norm(embedding) + 1e-12)

    # ------------------------------------------------------------------
    # Gallery management
    # ------------------------------------------------------------------

    def register(self, name: str, image: np.ndarray) -> int:
        """
        Detect all faces in `image`, embed them, and add them to the gallery
        under `name`. Call multiple times with different photos for a more
        robust representation.

        Returns the number of faces successfully registered.
        """
        detections = detect_and_crop(image)
        if not detections:
            print(f'No face detected in the provided image for "{name}".')
            return 0

        new_embeddings = [self.embed(d['face']) for d in detections]

        if name not in self.gallery:
            self.gallery[name] = np.mean(new_embeddings, axis=0)
        else:
            all_embeddings = [self.gallery[name]] + new_embeddings
            self.gallery[name] = np.mean(all_embeddings, axis=0)

        # Re-normalise the mean so it stays on the unit hypersphere
        mean = self.gallery[name]
        self.gallery[name] = mean / (np.linalg.norm(mean) + 1e-12)

        self._save_gallery()
        print(f'Registered {len(new_embeddings)} face(s) for "{name}". '
              f'Gallery now has {len(self.gallery)} identit(ies).')
        return len(new_embeddings)

    def remove(self, name: str) -> bool:
        """Remove a person from the gallery. Returns True if they existed."""
        if name in self.gallery:
            del self.gallery[name]
            self._save_gallery()
            return True
        return False

    def list_identities(self) -> list[str]:
        return list(self.gallery.keys())

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    def identify_face(self, face: np.ndarray) -> dict:
        """
        Identify a single pre-cropped face against the gallery.

        Returns:
            {'name': str, 'distance': float}
        """
        if not self.gallery:
            return {'name': 'Unknown', 'distance': float('inf')}

        embedding = self.embed(face)

        best_name = 'Unknown'
        best_dist = float('inf')

        for name, gallery_emb in self.gallery.items():
            dist = float(np.linalg.norm(embedding - gallery_emb))
            if dist < best_dist:
                best_dist = dist
                best_name = name

        if best_dist > self.threshold:
            best_name = 'Unknown'

        return {'name': best_name, 'distance': round(best_dist, 4)}

    def get_face_crop(self, image: np.ndarray, box: list[int]) -> np.ndarray:
        """
        Return a float32 [0, 1] crop of the face region defined by box [x, y, w, h].
        Used to attach a face snapshot to Telegram notifications.
        """
        x, y, w, h = box
        crop = image[y:y + h, x:x + w]
        return crop.astype(np.float32) / 255.0

    def identify_image(self, image: np.ndarray) -> list[dict]:
        """
        Detect all faces in `image`, run liveness detection, then identify each one.

        Args:
            image: RGB numpy array (H, W, 3), uint8.

        Returns:
            List of dicts with name, distance, box, detection_conf, is_real, liveness_score.
            Spoof faces have name='Spoof' and distance=None; ArcFace is skipped for them.
        """
        from backend.liveness import check_liveness

        detections = detect_and_crop(image)
        results = []
        for det in detections:
            liveness = check_liveness(image, det['box'])

            if not liveness['is_real']:
                print(f'  [liveness] SPOOF detected — score={liveness["liveness_score"]}')
                results.append({
                    'name':            'Spoof',
                    'distance':        None,
                    'box':             det['box'],
                    'detection_conf':  round(det['confidence'], 4),
                    'is_real':         False,
                    'liveness_score':  liveness['liveness_score'],
                })
                continue

            identity = self.identify_face(det['face'])
            print(f'  [liveness] real — score={liveness["liveness_score"]}')
            results.append({
                'name':           identity['name'],
                'distance':       identity['distance'],
                'box':            det['box'],
                'detection_conf': round(det['confidence'], 4),
                'is_real':        True,
                'liveness_score': liveness['liveness_score'],
            })
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_gallery(self):
        self.gallery_path.parent.mkdir(parents=True, exist_ok=True)
        serialisable = {name: emb.tolist() for name, emb in self.gallery.items()}
        with open(self.gallery_path, 'w') as f:
            json.dump(serialisable, f)

    def _load_gallery(self):
        with open(self.gallery_path) as f:
            raw = json.load(f)
        self.gallery = {name: np.array(emb, dtype=np.float32)
                        for name, emb in raw.items()}
        print(f'Loaded gallery with {len(self.gallery)} identit(ies) '
              f'from {self.gallery_path}')
