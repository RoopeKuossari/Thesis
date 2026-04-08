import { useEffect, useRef, useState } from 'react'
import { identifyBlob, registerBlob } from '../api'
import { drawFaces } from './FaceOverlay'

const CAPTURE_INTERVAL_MS = 600

// IoU threshold to consider two boxes the same face across frames
const IOU_MATCH_THRESHOLD = 0.3

// How long (ms) to keep a tracked face alive after it was last seen
const TRACK_EXPIRY_MS = 3000

let _nextTrackId = 1

// ---------------------------------------------------------------------------
// IoU helper — boxes are [x, y, w, h]
// ---------------------------------------------------------------------------
function iou(a, b) {
  const ax2 = a[0] + a[2], ay2 = a[1] + a[3]
  const bx2 = b[0] + b[2], by2 = b[1] + b[3]
  const ix1 = Math.max(a[0], b[0])
  const iy1 = Math.max(a[1], b[1])
  const ix2 = Math.min(ax2, bx2)
  const iy2 = Math.min(ay2, by2)
  if (ix2 <= ix1 || iy2 <= iy1) return 0
  const inter = (ix2 - ix1) * (iy2 - iy1)
  return inter / (a[2] * a[3] + b[2] * b[3] - inter)
}

// ---------------------------------------------------------------------------
// Match API results to tracked faces, return updated tracker map
// ---------------------------------------------------------------------------
function updateTracker(trackerMap, apiResults, now) {
  const updated = new Map(trackerMap)

  // Mark all as not-matched this frame
  for (const t of updated.values()) t._matched = false

  for (const result of apiResults) {
    // Find the best-matching tracked face
    let bestId = null
    let bestIou = IOU_MATCH_THRESHOLD

    for (const [id, tracked] of updated) {
      const score = iou(result.box, tracked.box)
      if (score > bestIou) {
        bestIou = score
        bestId = id
      }
    }

    if (bestId !== null) {
      // Known face — update position and refresh identity every frame
      const t = updated.get(bestId)
      t.box = result.box
      t.lastSeen = now
      t._matched = true
      t.name = result.name
      t.distance = result.distance
      t.status = result.name === 'Unknown' ? 'unknown' : 'known'
    } else {
      // New face — start as identifying (yellow)
      const id = _nextTrackId++
      updated.set(id, {
        id,
        box: result.box,
        name: result.name,
        distance: result.distance,
        // If the API already returned on the very first frame, skip yellow
        status: result.name === 'Unknown' ? 'unknown' : 'known',
        lastSeen: now,
        _matched: true,
      })
    }
  }

  // Remove faces that have not been seen for a while
  for (const [id, t] of updated) {
    if (!t._matched && now - t.lastSeen > TRACK_EXPIRY_MS) {
      updated.delete(id)
    }
  }

  return updated
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function WebcamView() {
  const videoRef    = useRef(null)
  const canvasRef   = useRef(null)
  const intervalRef = useRef(null)
  const lastTimeRef = useRef(Date.now())
  const trackerRef  = useRef(new Map())   // id → tracked face object
  const pendingRef  = useRef(false)       // true while an API call is in flight

  const [running, setRunning]       = useState(false)
  const [error, setError]           = useState(null)
  const [fps, setFps]               = useState(0)
  const [registerName, setRegisterName] = useState('')
  const [registerMsg, setRegisterMsg]   = useState(null)
  const [registering, setRegistering]   = useState(false)

  async function startCamera() {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      })
      videoRef.current.srcObject = stream
      await videoRef.current.play()
      setRunning(true)
    } catch (e) {
      setError('Camera access denied or unavailable: ' + e.message)
    }
  }

  function stopCamera() {
    const stream = videoRef.current?.srcObject
    stream?.getTracks().forEach(t => t.stop())
    if (videoRef.current) videoRef.current.srcObject = null
    clearInterval(intervalRef.current)
    trackerRef.current = new Map()
    const canvas = canvasRef.current
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
    setRunning(false)
  }

  function captureFrame() {
    const video = videoRef.current
    if (!video || video.readyState < 2) return null
    const c = document.createElement('canvas')
    c.width = video.videoWidth
    c.height = video.videoHeight
    c.getContext('2d').drawImage(video, 0, 0)
    return new Promise(resolve => c.toBlob(resolve, 'image/jpeg', 0.9))
  }

  async function handleRegister() {
    if (!registerName.trim()) { setRegisterMsg('Enter a name first.'); return }
    setRegistering(true)
    setRegisterMsg(null)
    try {
      const blobs = []
      for (let i = 0; i < 3; i++) {
        const blob = await captureFrame()
        if (blob) blobs.push(blob)
        await new Promise(r => setTimeout(r, 200))
      }
      if (!blobs.length) { setRegisterMsg('Could not capture frame.'); return }
      let total = 0
      for (const blob of blobs) {
        const data = await registerBlob(registerName.trim(), blob)
        total += data.faces_registered
      }
      setRegisterMsg(total > 0
        ? `Registered "${registerName.trim()}" from webcam.`
        : 'No face detected in captured frames.'
      )
    } catch (e) {
      setRegisterMsg('Error: ' + e.message)
    } finally {
      setRegistering(false)
    }
  }

  useEffect(() => {
    if (!running) return

    const video   = videoRef.current
    const overlay = canvasRef.current
    const capture = document.createElement('canvas')

    intervalRef.current = setInterval(() => {
      if (!video || video.readyState < 2) return

      const vw = video.videoWidth
      const vh = video.videoHeight
      capture.width  = vw
      capture.height = vh
      overlay.width  = vw
      overlay.height = vh

      // Always redraw current tracked state so boxes follow the video smoothly
      const tracked = Array.from(trackerRef.current.values())
      drawFaces(overlay, tracked, vw, vh)

      // Skip API call if previous one is still in flight
      if (pendingRef.current) return

      capture.getContext('2d').drawImage(video, 0, 0, vw, vh)
      capture.toBlob(async blob => {
        if (!blob) return
        pendingRef.current = true
        try {
          const data = await identifyBlob(blob)
          const now  = Date.now()
          trackerRef.current = updateTracker(trackerRef.current, data.faces, now)
          drawFaces(overlay, Array.from(trackerRef.current.values()), vw, vh)
          setFps(Math.round(1000 / (now - lastTimeRef.current)))
          lastTimeRef.current = now
        } catch (_) {
          // ignore transient network errors
        } finally {
          pendingRef.current = false
        }
      }, 'image/jpeg', 0.8)
    }, CAPTURE_INTERVAL_MS)

    return () => clearInterval(intervalRef.current)
  }, [running])

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Live Webcam</h2>
        {running && <span className="badge">{fps} fps</span>}
      </div>

      <div className="video-wrapper">
        <video ref={videoRef} className="video" playsInline muted />
        <canvas ref={canvasRef} className="overlay" />
      </div>

      <div className="controls">
        {!running ? (
          <button className="btn btn-primary" onClick={startCamera}>Start Camera</button>
        ) : (
          <button className="btn btn-danger" onClick={stopCamera}>Stop Camera</button>
        )}
      </div>

      {running && (
        <div className="register-row">
          <input
            className="text-input"
            type="text"
            placeholder="Name"
            value={registerName}
            onChange={e => setRegisterName(e.target.value)}
          />
          <button
            className="btn btn-primary"
            onClick={handleRegister}
            disabled={registering}
          >
            {registering ? 'Capturing...' : 'Register from webcam'}
          </button>
          {registerMsg && <span className="hint">{registerMsg}</span>}
        </div>
      )}

      {error && <p className="error">{error}</p>}
    </div>
  )
}
