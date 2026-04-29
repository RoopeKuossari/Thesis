import { useState, useEffect, useRef } from 'react'
import {
  startSurveillance, stopSurveillance,
  getSurveillanceBuffer, ingestSurveillanceFrame,
  getHighlights,
} from '../api'

// How often to capture a frame and send it to the backend for processing
const CAPTURE_INTERVAL_MS = 600
// DVR playback: advance this many ms per tick (matches capture rate ~5fps)
const FRAME_MS = 200
// How often to poll buffer info
const POLL_MS = 1000

function fmt(ms) {
  if (!ms) return '--:--:--'
  return new Date(ms).toLocaleTimeString()
}

// A scene whose end_t is within this many ms of "now" is treated as still
// live and displayed with "– now" instead of a fixed end time.
const LIVE_END_THRESHOLD_MS = 6000

function fmtHighlightRange(h) {
  if (h.category === 'spoof') return fmt(h.t)
  if (h.end_t == null)         return fmt(h.t)  // legacy row, no end_t
  if (Date.now() - h.end_t < LIVE_END_THRESHOLD_MS) {
    return `${fmt(h.t)} – now`
  }
  return `${fmt(h.t)} – ${fmt(h.end_t)}`
}

export default function SurveillanceView() {
  const [mode, setMode]           = useState('stopped') // 'stopped'|'live'|'dvr'
  const [playing, setPlaying]     = useState(false)
  const [bufInfo, setBufInfo]     = useState(null)
  const [scrubTime, setScrubTime] = useState(null)
  const [error, setError]         = useState(null)
  const [liveKey, setLiveKey]     = useState(0)   // incremented on each live reconnect
  const [highlights, setHighlights] = useState([])
  const [hlFilter, setHlFilter]     = useState('all')

  const videoRef    = useRef(null)   // hidden <video> for webcam capture
  const captureRef  = useRef(null)   // off-screen <canvas>
  const pendingRef  = useRef(false)  // true while an ingest request is in flight
  const intervalRef = useRef(null)   // capture interval id

  // Refs so interval callbacks always read the latest values without re-registering
  const modeRef      = useRef(mode)
  const bufInfoRef   = useRef(bufInfo)
  const scrubTimeRef = useRef(scrubTime)
  useEffect(() => { modeRef.current = mode },      [mode])
  useEffect(() => { bufInfoRef.current = bufInfo }, [bufInfo])
  useEffect(() => { scrubTimeRef.current = scrubTime }, [scrubTime])

  // ------------------------------------------------------------------
  // Buffer polling — active while surveillance is running
  // ------------------------------------------------------------------
  useEffect(() => {
    if (mode === 'stopped') return

    const id = setInterval(async () => {
      try {
        const info = await getSurveillanceBuffer()
        setBufInfo(info)
        bufInfoRef.current = info
        if (modeRef.current === 'live' && info.end) {
          setScrubTime(info.end)
          scrubTimeRef.current = info.end
        }
      } catch { /* ignore transient errors */ }
    }, POLL_MS)

    return () => clearInterval(id)
  }, [mode])

  // ------------------------------------------------------------------
  // DVR playback ticker
  // ------------------------------------------------------------------
  useEffect(() => {
    if (mode !== 'dvr' || !playing) return

    const id = setInterval(() => {
      const next = (scrubTimeRef.current ?? 0) + FRAME_MS
      const end  = bufInfoRef.current?.end

      if (end && next >= end) {
        setMode('live')
        setScrubTime(end)
        setPlaying(false)
      } else {
        setScrubTime(next)
        scrubTimeRef.current = next
      }
    }, FRAME_MS)

    return () => clearInterval(id)
  }, [mode, playing])

  // ------------------------------------------------------------------
  // Highlight polling — every 3 s while active
  // ------------------------------------------------------------------
  useEffect(() => {
    if (mode === 'stopped') return
    const id = setInterval(async () => {
      try {
        const data = await getHighlights()
        setHighlights(data.highlights)
      } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(id)
  }, [mode])

  function jumpTo(t) {
    setScrubTime(t)
    scrubTimeRef.current = t
    setMode('dvr')
    setPlaying(false)
  }

  // ------------------------------------------------------------------
  // Start / Stop
  // ------------------------------------------------------------------
  async function handleStart() {
    setError(null)
    try {
      // Open webcam
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      })
      videoRef.current.srcObject = stream
      await videoRef.current.play()

      // Tell backend to start accepting frames
      await startSurveillance()
      setLiveKey(k => k + 1)
      setMode('live')

      // Begin capture loop
      captureRef.current = document.createElement('canvas')
      intervalRef.current = setInterval(async () => {
        const video = videoRef.current
        if (!video || video.readyState < 2 || pendingRef.current) return

        const canvas = captureRef.current
        canvas.width  = video.videoWidth
        canvas.height = video.videoHeight
        canvas.getContext('2d').drawImage(video, 0, 0)

        canvas.toBlob(async blob => {
          if (!blob) return
          pendingRef.current = true
          try {
            await ingestSurveillanceFrame(blob)
          } catch { /* ignore transient errors */ }
          finally { pendingRef.current = false }
        }, 'image/jpeg', 0.85)
      }, CAPTURE_INTERVAL_MS)

    } catch (e) {
      setError('Could not start surveillance: ' + e.message)
    }
  }

  async function handleStop() {
    // Stop capture loop
    clearInterval(intervalRef.current)

    // Stop webcam tracks
    videoRef.current?.srcObject?.getTracks().forEach(t => t.stop())
    if (videoRef.current) videoRef.current.srcObject = null

    // Tell backend to stop and clear buffer
    try { await stopSurveillance() } catch { /* ignore */ }

    setMode('stopped')
    setBufInfo(null)
    setScrubTime(null)
    setPlaying(false)
    setHighlights([])
  }

  // ------------------------------------------------------------------
  // Scrubber
  // ------------------------------------------------------------------
  function onScrub(e) {
    const t = parseInt(e.target.value)
    setScrubTime(t)
    scrubTimeRef.current = t
    if (mode === 'live') setMode('dvr')
    setPlaying(false)
  }

  function goLive() {
    setLiveKey(k => k + 1)   // new key → new <img> → fresh MJPEG connection
    setMode('live')
    setScrubTime(bufInfoRef.current?.end ?? null)
    setPlaying(false)
  }

  // ------------------------------------------------------------------
  // Displayed frame source
  // key change forces <img> remount, cleanly disconnecting the MJPEG stream
  // ------------------------------------------------------------------
  let imgSrc = null
  const imgKey = mode === 'live' ? `live-${liveKey}` : 'dvr'

  if (mode === 'live') {
    imgSrc = `/api/surveillance/stream?s=${liveKey}`
  } else if (mode === 'dvr' && scrubTime) {
    imgSrc = `/api/surveillance/frame?t=${scrubTime}`
  }

  const bufDuration = bufInfo?.start && bufInfo?.end
    ? Math.round((bufInfo.end - bufInfo.start) / 1000)
    : 0

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Surveillance</h2>
        {mode === 'live' && <span className="badge badge-live">● LIVE</span>}
        {mode === 'dvr'  && <span className="badge badge-dvr">DVR</span>}
      </div>

      {/* Hidden webcam element — used only for frame capture */}
      <video ref={videoRef} style={{ display: 'none' }} playsInline muted />

      {/* Displayed feed: MJPEG stream (live) or single frame (DVR) */}
      <div className="video-wrapper">
        {imgSrc ? (
          <img
            key={imgKey}
            src={imgSrc}
            className="video"
            alt="Surveillance feed"
          />
        ) : (
          <div className="video-placeholder">
            {mode === 'stopped'
              ? 'Surveillance not running'
              : 'Waiting for first frame…'}
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="controls">
        {mode === 'stopped' ? (
          <button className="btn btn-primary" onClick={handleStart}>
            Start Surveillance
          </button>
        ) : (
          <button className="btn btn-danger" onClick={handleStop}>
            Stop
          </button>
        )}

        {mode === 'dvr' && (
          <>
            <button className="btn btn-secondary" onClick={() => setPlaying(p => !p)}>
              {playing ? 'Pause' : 'Play'}
            </button>
            <button className="btn btn-primary" onClick={goLive}>
              Go Live
            </button>
          </>
        )}
      </div>

      {/* Timeline / DVR scrubber */}
      {bufInfo?.start && bufInfo?.end && (
        <div className="timeline">
          <div className="timeline-times">
            <span>{fmt(bufInfo.start)}</span>
            <span className="timeline-now">{fmt(scrubTime)}</span>
            <span>{fmt(bufInfo.end)}</span>
          </div>
          <input
            type="range"
            className="scrubber"
            min={bufInfo.start}
            max={bufInfo.end}
            value={scrubTime ?? bufInfo.end}
            step={1}
            onChange={onScrub}
          />
          <p className="hint">
            {bufDuration}s buffered · {bufInfo.frames} frames
          </p>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      {/* Highlights section */}
      {mode !== 'stopped' && (
        <div className="hl-section">
          <div className="hl-header">
            <span className="hl-title">Highlights</span>
            <div className="hl-filters">
              {[
                { key: 'all',           label: 'All' },
                { key: 'known',         label: '● Known' },
                { key: 'mixed_unknown', label: '● Mixed' },
                { key: 'unknown',       label: '● Unknown' },
                { key: 'spoof',         label: '● Spoof' },
              ].map(f => (
                <button
                  key={f.key}
                  className={`hl-filter hl-filter-${f.key} ${hlFilter === f.key ? 'hl-filter-active' : ''}`}
                  onClick={() => setHlFilter(f.key)}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          {highlights.length === 0 ? (
            <p className="hint">No highlights yet — waiting for faces to enter frame.</p>
          ) : (
            <div className="hl-cards">
              {[...highlights]
                .reverse()
                .filter(h => hlFilter === 'all' || h.category === hlFilter)
                .map(h => (
                  <div key={h.id} className={`hl-card hl-card-${h.category}`}>
                    <img
                      className="hl-img"
                      src={`/api/surveillance/highlight/${h.id}/image`}
                      alt={h.name || 'Unknown'}
                    />
                    <div className="hl-meta">
                      <span className="hl-time">{fmtHighlightRange(h)}</span>
                      <span className="hl-name">
                        {h.category === 'spoof' ? 'Spoof' : (h.name || 'Unknown')}
                      </span>
                    </div>
                    <button className="btn btn-secondary hl-jump" onClick={() => jumpTo(h.t)}>
                      Jump
                    </button>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
