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

### User roles

Every account has one of two roles:

| Role | Can | Cannot |
|---|---|---|
| **admin** | Watch the live feed, start/stop surveillance, register faces, tune all settings, manage users, delete history footages | — |
| **viewer** | Watch the live feed (when an admin has started it), review history | Start/stop surveillance, register or delete faces, change settings, manage users, delete history |

The role is shown in the top-right corner of the app — hover over the username to open the account menu (admins see *Settings* and *Logout*; viewers see only *Logout*).

### Create the first (admin) account

```bash
source .venv/bin/activate
python -m backend.create_user create --username admin --role admin
```

You will be prompted to enter and confirm a password (8+ characters). Once you have one admin account, additional users — viewers and other admins — are easiest to create from the **Settings → Users** panel inside the web UI.

### CLI account management

```bash
python -m backend.create_user create --username alice --role viewer
python -m backend.create_user list                      # list accounts with roles
python -m backend.create_user delete --username alice   # remove an account
```

`--role` accepts `admin` or `viewer` (defaults to `admin` so the first bootstrap user always has full access). The CLI is also the only safe way to recover if you somehow lock yourself out of the web UI.

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

- Alert fires only when an unknown person is **loitering** (continuously present for 5 seconds) — brief glances don't trigger it
- Alert is suppressed if **any known person is in frame**, OR was in frame within the last **60 seconds** (grace period — handles a known person briefly stepping out while a guest is still present)
- A **60-second cooldown** prevents repeated alerts while the same unknown person stays on screen
- The alert includes a cropped photo of the face

Tunables (all editable live from the **Settings** page; admin only):

| Setting | Default | What it controls |
|---|---|---|
| Loitering threshold | 5 s | How long an unknown must stay before being flagged as loitering |
| Known-person grace | 60 s | How long after a known person leaves the alert remains suppressed |
| Telegram alert cooldown | 60 s | Gap between repeat alerts |
| Scene grace | 5 s | How long the active highlight stays open after the last face leaves |
| Identity match threshold | 0.9 | Cosine distance below which a face counts as a known person (lower = stricter) |

Updates take effect on the next ingested frame — no restart required. Persisted to `storage/settings.json`.

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

1. Click **Start Surveillance** — the browser asks for camera permission, then begins streaming (admins only — viewers see "Waiting for an admin to start a session…" until an admin starts one, after which the live feed appears automatically)
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

Below the timeline, the Highlights section shows **scene intervals** — one card per continuous activity period, displayed as a time range like `16:11:30 – 16:12:45`. Active scenes show `– now` until the scene ends.

| Highlight colour | Meaning |
|-----------------|---------|
| 🟢 Green border | Known person only in frame |
| 🟡 Yellow border | Known and unknown person in frame |
| 🔴 Red border | Unknown person only in frame |
| 🟠 Orange border | Spoof (printed photo / screen) detected — point-in-time stamp |

Whenever the colour would change (e.g. an unknown joins a known-only scene), the **current highlight closes and a new one opens at that moment** — so the timeline shows distinct cards per segment (green → yellow → green produces three cards).

Scene rules:
- A continuous scene ends when nobody (known or unknown) has been in frame for **5 seconds**
- Within a scene: known + unknown together → yellow; known only → green; unknown only → red. Each colour is its own highlight; transitions happen with a 5 s grace so a brief glance away doesn't split a segment in two
- Spoof attempts are recorded as separate **orange stamps** (a single point in time you can jump to). A new stamp is only created if no spoof has been seen for 5 s.

Use the **filter buttons** (All / Known / Mixed / Unknown / Spoof) to narrow down the list.
Click **Jump** on any highlight card to seek directly to that moment in the DVR.

---

## Settings page (admin only)

Admins reach the Settings page from the account menu in the top-right corner. It contains four panels:

- **Tuning** — sliders + numeric inputs for the identity-match threshold, scene grace, loitering threshold, known-person grace and Telegram alert cooldown. Each row has a *Reset* button that snaps the value back to its default. Changes are debounced and persisted to `storage/settings.json`; the running surveillance system picks them up on the next frame.
- **Known faces** — list of registered identities with *Remove*, plus a webcam capture button to add a new person without leaving the page.
- **History footages** — every saved session, with a *Delete* button that removes the database row and the on-disk frames + thumbnails for that session.
- **Users** — create new admin or viewer accounts (username + 8-char password + role) and delete existing ones. You cannot delete your own account, and the system refuses to delete the last remaining admin.

Viewers do not see the *Settings* entry in the account menu and any direct attempt to call the underlying admin endpoints returns `403 Admin privilege required.`.

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

Registration is admin-only. Three ways:

### Option A — from the Settings page (recommended for one-off adds)
1. Open the account menu in the top-right corner → **Settings**
2. In the **Known faces** panel, type a name and click **Add face from webcam**

### Option B — from the Webcam tab (good for sweeping multiple angles)
1. Switch to the **Webcam** tab and start the camera
2. Type a name in the field below the video
3. Click **"Register from webcam"** — repeat from different distances and angles for best results

### Option C — from photo files

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

Every endpoint except `POST /auth/login`, `POST /auth/logout` and `GET /auth/me` requires a valid session cookie. Endpoints marked **admin** additionally require the caller's role to be `admin`; viewers receive `403 Admin privilege required.`.

### Authentication & user management

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/login` | public | Verify credentials, set `access_token` cookie. Response includes `username` and `role`. |
| `POST` | `/auth/logout` | public | Clear the auth cookie |
| `GET` | `/auth/me` | any | Current user `{username, role}` (used by the frontend on page load) |
| `GET` | `/auth/users` | admin | List every account with role and creation timestamp |
| `POST` | `/auth/users` | admin | Create a new user `{username, password, role}` |
| `DELETE` | `/auth/users/{username}` | admin | Remove a user (refuses self-deletion or removing the last admin) |

### Settings

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/settings` | any | Current values, defaults and bounds schema for every tunable |
| `PUT` | `/settings` | admin | Apply a partial update (unknown keys / out-of-bounds values → 400) |

### Identification & registration

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/identify` | admin | Detect and identify all faces in an uploaded image |
| `POST` | `/register` | admin | Register a person with one or more uploaded images |
| `DELETE` | `/identities/{name}` | admin | Remove a person from the gallery |
| `GET` | `/identities` | any | List all registered identities |

### Surveillance

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/surveillance/start` | admin | Activate the surveillance system |
| `POST` | `/surveillance/stop` | admin | Deactivate surveillance, flush session to history |
| `POST` | `/surveillance/ingest` | admin | Receive an annotated JPEG frame from the browser |
| `GET` | `/surveillance/status` | any | `{active, start, end, frames}` — used by viewers to detect when a session begins |
| `GET` | `/surveillance/stream` | any | MJPEG live stream of annotated frames |
| `GET` | `/surveillance/frame?t={ms}` | any | Stored frame closest to Unix timestamp (ms) |
| `GET` | `/surveillance/buffer` | any | Buffer metadata: start/end timestamps, frame count |
| `GET` | `/surveillance/highlights` | any | Highlight event list for the current session |
| `GET` | `/surveillance/highlight/{id}/image` | any | Thumbnail JPEG for a specific highlight |

### History

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/history` | any | List all completed sessions (newest first) |
| `DELETE` | `/history/{session_id}` | admin | Permanently delete a saved session and all of its frames + thumbnails |
| `GET` | `/history/{session_id}/frame?t={ms}` | any | Stored frame from a past session closest to timestamp |
| `GET` | `/history/{session_id}/highlights` | any | All highlights for a past session |
| `GET` | `/history/{session_id}/highlight/{id}/image` | any | Thumbnail JPEG for a past highlight |

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
      "liveness_score": 0.87,
      "is_loitering": false
    }
  ]
}
```

`is_loitering` is set to `true` for `Unknown` faces when the unknown group has been
continuously present for the *Loitering threshold* setting (5 s by default; editable live
from **Settings → Tuning**). Known faces and spoofs always report `false`. Telegram alerts
only fire when at least one face has `is_loitering: true` and no known person is in frame.

`distance` is the L2 distance between L2-normalised embeddings (range 0–2).
A face is identified if `distance < identity_threshold` (default `0.9`, editable live from the **Settings → Tuning** panel; persisted to `storage/settings.json`).

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
│   ├── history.py                  # SQLite session history + 7-day retention + delete_session
│   ├── auth.py                     # bcrypt + JWT + roles + require_admin dependency
│   ├── auth_router.py              # FastAPI auth + user-management endpoints
│   ├── settings.py                 # Live-tunable thresholds / cooldowns (JSON-persisted)
│   ├── create_user.py              # CLI account management (supports --role)
│   ├── register.py                 # CLI face registration tool
│   ├── notifier.py                 # Telegram alert sender
│   └── main.py                     # FastAPI REST API + auth middleware + admin gating
├── frontend/
│   ├── src/
│   │   ├── App.jsx                 # Tab layout, role-aware tabs, settings view router
│   │   ├── api.js                  # API client (auth, settings, users, history delete, …)
│   │   ├── context/
│   │   │   └── AuthContext.jsx     # Auth state provider (exposes user, role, isAdmin)
│   │   └── components/
│   │       ├── LoginPage.jsx       # Login form
│   │       ├── UserMenu.jsx        # Top-right account dropdown (role + Settings + Logout)
│   │       ├── SettingsPage.jsx    # Admin: tuning sliders, identities, history, users
│   │       ├── SurveillanceView.jsx # Live stream + DVR (admin can start/stop; viewer auto-tracks state)
│   │       ├── HistoryView.jsx     # Session list (History tab)
│   │       ├── SessionPlayback.jsx # DVR playback for a past session
│   │       ├── WebcamView.jsx      # Live webcam + registration (admin only)
│   │       ├── FileUpload.jsx      # Image upload + identification (admin only)
│   │       └── FaceOverlay.jsx     # Bounding box drawing (canvas)
│   └── package.json
├── storage/                        # Created automatically on first run
│   ├── history.db                  # SQLite database (sessions, highlights, users)
│   ├── settings.json               # Persisted admin overrides for tunable thresholds
│   └── sessions/
│       └── YYYY-MM-DD_HH-MM-SS/   # One directory per session
│           ├── frames/             # Annotated JPEG frames named by Unix ms
│           └── highlights/         # Highlight thumbnail JPEGs
├── requirements.txt
└── notes.md                        # Developer notes
```
