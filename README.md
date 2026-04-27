# Face Detection & Identification System

A real-time face detection and identification system with a **surveillance mode** featuring live streaming, DVR rewind, and event highlights. Built with MTCNN (detection), ArcFace (recognition), a FastAPI backend, and a React frontend.

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

## Authentication

The system requires a login before the UI is accessible. Accounts are managed locally — there is no public registration.

### Create the first account

```bash
source .venv/bin/activate
python -m backend.create_user create --username admin
```

You will be prompted to enter and confirm a password (8+ characters). Additional commands:

```bash
python -m backend.create_user list                      # list all accounts
python -m backend.create_user delete --username alice   # remove an account
```

Passwords are stored as bcrypt hashes — the database never contains plain-text credentials.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET_KEY` | **Production** | Secret used to sign session tokens. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SECURE_COOKIES` | When using HTTPS | Set to `true` so the session cookie is only sent over HTTPS |

For local development neither variable is required. For port-forwarding both must be set.

Add them to your `.env` file:

```bash
export JWT_SECRET_KEY="your-generated-secret-here"
export SECURE_COOKIES=true   # only when HTTPS is configured
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

## Anti-spoofing (liveness detection)

The system uses **MiniFASNet** (via DeepFace) to reject printed photos and screen-replay attacks before running face recognition. Every detected face is checked for liveness first; spoofs never reach the ArcFace embedding stage.

### How it works

Two lightweight MiniFASNet models (~1.85 MB each) analyse the face at two spatial scales (2.7× and 4.0× around the bounding box). Their softmax predictions are averaged and compared against a threshold.

Model weights are downloaded automatically to `~/.deepface/weights/` on first run.

### Colour coding

| Colour | Meaning |
|--------|---------|
| Green | Known person (real face, gallery match) |
| Red | Unknown person (real face, no gallery match) |
| Orange | Spoof detected (printed photo or screen) |

### Tuning

The threshold is set in `backend/liveness.py`:

```python
LIVENESS_THRESHOLD = 0.2   # lower = stricter (more spoofs caught, more false rejections)
```

The default of `0.2` works well for phone/print attacks. If real faces are being incorrectly rejected, try raising it to `0.3`–`0.4`.

---

## Telegram notifications (optional)

The system can send a Telegram alert with a face snapshot when an unknown person is detected **and no known person is present in the same frame**.

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

- Alert fires only after a face has been **continuously unknown for 5 seconds** — brief misidentifications do not trigger it
- Alert is suppressed if **any known person is also in frame**
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
source .env          # load JWT secret + Telegram credentials
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

Open `http://localhost:5173` in your browser. You will be prompted to sign in — use the account created in the Authentication step above.

---

## Using the Surveillance System

The app opens on the **Surveillance** tab by default.

1. Click **Start Surveillance** — the browser asks for camera permission, then begins streaming
2. The live feed is annotated with bounding boxes and a timestamp in the bottom-right corner
3. Face boxes are colour-coded:
   - **Green** — known person (matched in gallery)
   - **Red** — unknown person (no gallery match)

### DVR rewind

While surveillance is running you can rewind and review past footage:

- **Drag the timeline scrubber** leftward to enter DVR mode — the feed pauses at that point in time
- **Play / Pause** — plays back stored frames at recording speed (~5 fps)
- **Go Live** — returns to the live stream
- Up to **10 minutes** of footage is kept in the buffer at all times

### Highlights

Below the timeline, the Highlights section records the **first time each person enters the frame**:

| Highlight colour | Meaning |
|-----------------|---------|
| 🟢 Green border | Known person entered frame |
| 🟡 Yellow border | Unknown person entered, but a known person is also present |
| 🔴 Red border | Unknown person entered, no known person in frame |

Deduplication rules:
- If a person stays in frame, only the first entry is recorded
- If a person leaves and **returns within 3 minutes**, no new highlight is created
- After 3 minutes, a re-entry generates a new highlight

Use the **filter buttons** (All / Known / Mixed / Unknown) to narrow down the list.
Click **Jump** on any highlight card to seek directly to that moment in the DVR.

---

## History tab

Every completed surveillance session is automatically saved and accessible from the **History** tab.

### Session list

Each saved session is shown as a card with:
- Date and time range formatted as `DD.MM.YYYY HH:MM – HH:MM` (or `DD.MM.YYYY HH:MM – DD.MM.YYYY HH:MM` if the session crosses midnight)
- Highlight count, alert count, and frame count

Sessions older than **7 days** are automatically deleted (both from the database and from disk) the next time surveillance is started.

### Session playback

Click any session card to open it. The playback view works identically to the DVR mode on the Surveillance tab:
- **Scrub the timeline** to jump to any moment
- **Play / Pause** — plays back stored frames at recording speed (~5 fps)
- **⏮ Start / End ⏭** — jump to the beginning or end of the session
- **Highlights panel** shows all highlight events from that session with filter buttons and **Jump** links

---

## Registering a person

### Option A — from the webcam (recommended)
1. Switch to the **Webcam** tab and start the camera
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

### Identification & registration

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/identify` | Detect and identify all faces in an uploaded image |
| `POST` | `/register` | Register a person with one or more uploaded images |
| `DELETE` | `/identities/{name}` | Remove a person from the gallery |
| `GET` | `/identities` | List all registered identities |

### Surveillance

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/surveillance/start` | Activate the surveillance system |
| `POST` | `/surveillance/stop` | Deactivate surveillance, flush session to history |
| `POST` | `/surveillance/ingest` | Receive an annotated JPEG frame from the browser |
| `GET` | `/surveillance/stream` | MJPEG live stream of annotated frames |
| `GET` | `/surveillance/frame?t={ms}` | Stored frame closest to Unix timestamp (ms) |
| `GET` | `/surveillance/buffer` | Buffer metadata: start/end timestamps, frame count |
| `GET` | `/surveillance/highlights` | Highlight event list for the current session |
| `GET` | `/surveillance/highlight/{id}/image` | Thumbnail JPEG for a specific highlight |

### History

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/history` | List all completed sessions (newest first) |
| `GET` | `/history/{session_id}/frame?t={ms}` | Stored frame from a past session closest to timestamp |
| `GET` | `/history/{session_id}/highlights` | All highlights for a past session |
| `GET` | `/history/{session_id}/highlight/{id}/image` | Thumbnail JPEG for a past highlight |

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

# Get surveillance highlights
curl http://localhost:8000/surveillance/highlights | python -m json.tool
```

### Response format (`/identify`)

```json
{
  "faces": [
    {
      "name": "Alice",
      "distance": 0.42,
      "box": [x, y, width, height],
      "detection_conf": 0.999,
      "is_real": true,
      "liveness_score": 0.87
    }
  ]
}
```

`distance` is the L2 distance between L2-normalised embeddings (range 0–2).
A face is identified if `distance < IDENTITY_THRESHOLD` (default `0.9`, tunable in `backend/recognizer.py`).

Spoof faces have `name: "Spoof"` and `distance: null` — ArcFace is skipped for them.
`liveness_score` is the MiniFASNet confidence that the face is real (range 0–1).

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
│   ├── liveness.py                 # MiniFASNet anti-spoofing (liveness detection)
│   ├── surveillance.py             # Surveillance: ingest, ring buffer, highlights, disk persistence
│   ├── history.py                  # SQLite session history + 7-day retention
│   ├── auth.py                     # bcrypt password hashing + JWT helpers
│   ├── auth_router.py              # FastAPI auth endpoints (login / logout / me)
│   ├── create_user.py              # CLI account management tool
│   ├── register.py                 # CLI face registration tool
│   ├── notifier.py                 # Telegram alert sender
│   └── main.py                     # FastAPI REST API + auth middleware
├── frontend/
│   ├── src/
│   │   ├── App.jsx                 # Tab layout + auth gate + logout button
│   │   ├── api.js                  # API client
│   │   ├── context/
│   │   │   └── AuthContext.jsx     # Auth state provider (useAuth hook)
│   │   └── components/
│   │       ├── LoginPage.jsx       # Login form
│   │       ├── SurveillanceView.jsx # Live stream, DVR rewind, highlights
│   │       ├── HistoryView.jsx     # Session list (History tab)
│   │       ├── SessionPlayback.jsx # DVR playback for a past session
│   │       ├── WebcamView.jsx      # Live webcam + registration
│   │       ├── FileUpload.jsx      # Image upload + identification
│   │       └── FaceOverlay.jsx     # Bounding box drawing (canvas)
│   └── package.json
├── storage/                        # Created automatically on first run
│   ├── history.db                  # SQLite database
│   └── sessions/
│       └── YYYY-MM-DD_HH-MM-SS/   # One directory per session
│           ├── frames/             # Annotated JPEG frames named by Unix ms
│           └── highlights/         # Highlight thumbnail JPEGs
├── requirements.txt
└── notes.md                        # Developer notes
```
