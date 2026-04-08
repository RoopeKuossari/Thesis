# Face Detection & Identification System

A real-time face detection and identification system built with MTCNN (detection), a custom Siamese CNN trained on LFW (embeddings), and ArcFace (pretrained recognition). Includes a FastAPI backend and a React frontend with live webcam and file upload support.

---

## Requirements

- Python 3.12
- Node.js 18+
- NVIDIA GPU recommended (runs on CPU but much slower)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/RoopeKuossari/Thesis.git
cd Thesis
```

### 2. Set up Python environment

**Linux / WSL2:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (Command Prompt or PowerShell):**
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. GPU setup (NVIDIA)

**Linux / WSL2:**

On WSL2 the CUDA driver comes from Windows — no driver install needed inside WSL.
Add the library paths so TensorFlow can find them:

```bash
echo 'export LD_LIBRARY_PATH=/usr/lib/wsl/lib:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
```

**Windows (native):**

Install the [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) and
[cuDNN](https://developer.nvidia.com/cudnn). Then install the CUDA-enabled TensorFlow:

```bat
pip install "tensorflow[and-cuda]"
```

**Verify GPU is detected (all platforms):**
```bash
python -c "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"
```

### 4. Install frontend dependencies

**Linux / WSL2 / Windows:**
```bash
cd frontend
npm install
cd ..
```

---

## Training (optional)

A pretrained Siamese model is included. To retrain from scratch:

1. Download the [LFW deep-funneled dataset](http://vis-www.cs.umass.edu/lfw/) and place it at:
   ```
   dataset/lfw-deepfunneled/lfw-deepfunneled/<PersonName>/<image>.jpg
   ```

2. Run training:

   **Linux / WSL2:**
   ```bash
   python model/train.py
   ```

   **Windows:**
   ```bat
   python model\train.py
   ```

Training uses batch-hard triplet loss combined with a classification head to prevent embedding collapse. The best checkpoint is saved to `model/siamese_model.keras`.

> **Note:** The system uses ArcFace (via DeepFace) for recognition by default, which outperforms the custom CNN. The custom model is retained for thesis comparison purposes.

---

## Telegram notifications (optional)

The system can send a Telegram alert with a face snapshot when an unknown person is detected.

### Setup

1. Open Telegram and message **@BotFather** → `/newbot` → follow the prompts → copy the token
2. Send any message to your new bot
3. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and copy the `id` value from the `chat` object — that is your chat ID

### Configuration

Create a `.env` file in the project root:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
export TELEGRAM_CHAT_ID="987654321"
```

Load it before starting the backend (see Running the system below).

### Behaviour

- Alert fires only after a face has been **continuously unknown for 5 seconds** — brief misidentifications (bad angle, motion blur) do not trigger it
- A **60-second cooldown** prevents repeated alerts while the same unknown person stays on screen
- The alert includes a cropped photo of the face

Both values are tunable at the top of `backend/notifier.py` (`CONFIRM_SECONDS`, `COOLDOWN_SECONDS`).

---

## Running the system

Open two terminals:

**Terminal 1 — Backend API:**

Linux / WSL2:
```bash
source .venv/bin/activate
source .env          # load Telegram credentials (if using notifications)
uvicorn backend.main:app --reload
```

Windows:
```bat
.venv\Scripts\activate
uvicorn backend.main:app --reload
```
On Windows, set the env vars manually before starting:
```bat
set TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
set TELEGRAM_CHAT_ID=987654321
```

**Terminal 2 — Frontend:**

Linux / WSL2 / Windows:
```bash
cd frontend
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Registering a person

### Option A — from the webcam (recommended)
1. Open the app and start the camera
2. Type a name in the field below the video
3. Click **"Register from webcam"** — repeat from different distances and angles for best results

### Option B — from photo files

Linux / WSL2:
```bash
python -m backend.register --name "YourName" --images photo1.jpeg photo2.jpeg photo3.jpeg
```

Windows:
```bat
python -m backend.register --name "YourName" --images photo1.jpeg photo2.jpeg photo3.jpeg
```

- 3–5 photos recommended
- Phone photos are supported (EXIF rotation handled automatically)
- Gallery is saved to `model/gallery.json`

---

## API reference

The backend runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/identify` | Detect and identify all faces in an uploaded image |
| `POST` | `/register` | Register a person with one or more uploaded images |
| `DELETE` | `/identities/{name}` | Remove a person from the gallery |
| `GET` | `/identities` | List all registered identities |

### Example with curl

```bash
# Identify faces in an image
curl -X POST http://localhost:8000/identify \
  -F "image=@photo.jpeg" | python -m json.tool

# Register a person
curl -X POST http://localhost:8000/register \
  -F "name=Alice" \
  -F "images=@alice1.jpeg" \
  -F "images=@alice2.jpeg" | python -m json.tool

# List registered identities
curl http://localhost:8000/identities | python -m json.tool

# Remove a person
curl -X DELETE http://localhost:8000/identities/Alice | python -m json.tool
```

### Response format

```json
{
  "faces": [
    {
      "name": "Alice",
      "distance": 0.42,
      "box": [x, y, width, height],
      "detection_conf": 0.999
    }
  ]
}
```

`distance` is the L2 distance between L2-normalised embeddings (range 0–2).
A face is identified if `distance < IDENTITY_THRESHOLD` (default `0.9`, tunable in `backend/recognizer.py`).

---

## Project structure

```
Thesis/                             # repo root
├── dataset/
│   └── lfw-deepfunneled/           # LFW training dataset
├── model/
│   ├── model.py                    # Siamese CNN architecture + triplet loss
│   ├── train.py                    # Training script
│   ├── migrate_model.py            # One-time weight migration utility
│   ├── siamese_model.keras         # Trained model weights
│   └── gallery.json                # Registered identities (embeddings)
├── backend/
│   ├── detector.py                 # MTCNN face detection
│   ├── recognizer.py               # ArcFace embeddings + gallery matching
│   ├── register.py                 # CLI registration tool
│   ├── notifier.py                 # Telegram alert sender
│   └── main.py                     # FastAPI REST API
├── frontend/
│   ├── src/
│   │   ├── App.jsx                 # Tab layout
│   │   ├── api.js                  # API client
│   │   └── components/
│   │       ├── WebcamView.jsx      # Live webcam + registration
│   │       ├── FileUpload.jsx      # Image upload + identification
│   │       └── FaceOverlay.jsx     # Bounding box drawing
│   └── package.json
├── requirements.txt
└── notes.md                        # Developer notes
```
