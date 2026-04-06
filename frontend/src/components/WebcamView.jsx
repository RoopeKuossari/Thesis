import { useEffect, useRef, useState } from 'react'
import { identifyBlob, registerBlob } from '../api'
import { drawFaces } from './FaceOverlay'

const CAPTURE_INTERVAL_MS = 600

export default function WebcamView() {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const intervalRef = useRef(null)
  const lastTimeRef = useRef(Date.now())

  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [fps, setFps] = useState(0)
  const [registerName, setRegisterName] = useState('')
  const [registerMsg, setRegisterMsg] = useState(null)
  const [registering, setRegistering] = useState(false)

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
    const canvas = canvasRef.current
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
    setRunning(false)
  }

  // Capture current frame as a JPEG blob
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
    if (!registerName.trim()) {
      setRegisterMsg('Enter a name first.')
      return
    }
    setRegistering(true)
    setRegisterMsg(null)
    try {
      // Capture 3 frames ~200ms apart for better gallery coverage
      const blobs = []
      for (let i = 0; i < 3; i++) {
        const blob = await captureFrame()
        if (blob) blobs.push(blob)
        await new Promise(r => setTimeout(r, 200))
      }
      if (!blobs.length) {
        setRegisterMsg('Could not capture frame.')
        return
      }
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

    const video = videoRef.current
    const overlay = canvasRef.current
    const capture = document.createElement('canvas')

    intervalRef.current = setInterval(async () => {
      if (!video || video.readyState < 2) return

      const vw = video.videoWidth
      const vh = video.videoHeight
      capture.width = vw
      capture.height = vh
      overlay.width = vw
      overlay.height = vh

      capture.getContext('2d').drawImage(video, 0, 0, vw, vh)
      capture.toBlob(async blob => {
        if (!blob) return
        try {
          const data = await identifyBlob(blob)
          drawFaces(overlay, data.faces, vw, vh)
          const now = Date.now()
          setFps(Math.round(1000 / (now - lastTimeRef.current)))
          lastTimeRef.current = now
        } catch (_) {}
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
