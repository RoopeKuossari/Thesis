import { useState, useEffect, useRef } from 'react'
import { getHistoryHighlights } from '../api'

// DVR playback: advance this many ms per tick (~5 fps to match capture rate)
const FRAME_MS = 200

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pad2(n) { return String(n).padStart(2, '0') }
function dateStr(d) { return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${d.getFullYear()}` }
function timeStr(d) { return `${pad2(d.getHours())}:${pad2(d.getMinutes())}` }

function fmtTime(ms) {
  if (!ms) return '--:--:--'
  return new Date(ms).toLocaleTimeString()
}

function fmtTitle(s) {
  const start = new Date(s.started_at)
  const end   = s.ended_at ? new Date(s.ended_at) : null
  const startPart = `${dateStr(start)} ${timeStr(start)}`
  if (!end) return `${startPart} – ongoing`
  const sameDay = dateStr(start) === dateStr(end)
  const endPart = sameDay ? timeStr(end) : `${dateStr(end)} ${timeStr(end)}`
  return `${startPart} – ${endPart}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SessionPlayback({ session, onBack }) {
  const sessionEnd = session.ended_at ?? session.started_at

  const [scrubTime, setScrubTime] = useState(session.started_at)
  const [playing, setPlaying]     = useState(false)
  const [highlights, setHighlights] = useState([])
  const [hlFilter, setHlFilter]     = useState('all')

  // Refs so the playback interval always reads the latest values
  const scrubTimeRef = useRef(session.started_at)
  useEffect(() => { scrubTimeRef.current = scrubTime }, [scrubTime])

  // Load highlights once on mount
  useEffect(() => {
    getHistoryHighlights(session.id)
      .then(d => setHighlights(d.highlights))
      .catch(() => {})
  }, [session.id])

  // DVR playback ticker
  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => {
      const next = scrubTimeRef.current + FRAME_MS
      if (next >= sessionEnd) {
        setScrubTime(sessionEnd)
        scrubTimeRef.current = sessionEnd
        setPlaying(false)
      } else {
        setScrubTime(next)
        scrubTimeRef.current = next
      }
    }, FRAME_MS)
    return () => clearInterval(id)
  }, [playing, sessionEnd])

  function onScrub(e) {
    const t = parseInt(e.target.value)
    setScrubTime(t)
    scrubTimeRef.current = t
    setPlaying(false)
  }

  function jumpTo(t) {
    setScrubTime(t)
    scrubTimeRef.current = t
    setPlaying(false)
  }

  const atEnd   = scrubTime >= sessionEnd
  const atStart = scrubTime <= session.started_at

  const imgSrc = `/api/history/${session.id}/frame?t=${scrubTime}`

  const filteredHighlights = highlights.filter(
    h => hlFilter === 'all' || h.category === hlFilter
  )

  return (
    <div className="panel">
      {/* Header */}
      <div className="panel-header">
        <button className="btn btn-secondary" onClick={onBack}>← Back</button>
        <h2 style={{ fontSize: '0.92rem' }}>{fmtTitle(session)}</h2>
      </div>

      {/* Session-level stats */}
      <div className="session-stats" style={{ paddingBottom: '4px' }}>
        <span className="stat-badge stat-highlights">
          {session.highlight_count} highlight{session.highlight_count !== 1 ? 's' : ''}
        </span>
        <span className="stat-badge stat-alerts">
          {session.alert_count} alert{session.alert_count !== 1 ? 's' : ''}
        </span>
        <span className="stat-badge stat-frames">
          {session.frame_count} frames
        </span>
      </div>

      {/* Video frame */}
      <div className="video-wrapper">
        {session.frame_count > 0 ? (
          <img
            src={imgSrc}
            className="video"
            alt="Recorded frame"
          />
        ) : (
          <div className="video-placeholder">No frames recorded in this session.</div>
        )}
      </div>

      {/* Playback controls */}
      <div className="controls">
        <button
          className="btn btn-secondary"
          onClick={() => { setScrubTime(session.started_at); scrubTimeRef.current = session.started_at; setPlaying(false) }}
          disabled={atStart}
        >
          ⏮ Start
        </button>
        <button
          className="btn btn-primary"
          onClick={() => setPlaying(p => !p)}
          disabled={atEnd}
        >
          {playing ? 'Pause' : 'Play'}
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => { setScrubTime(sessionEnd); scrubTimeRef.current = sessionEnd; setPlaying(false) }}
          disabled={atEnd}
        >
          End ⏭
        </button>
      </div>

      {/* Timeline scrubber */}
      <div className="timeline">
        <div className="timeline-times">
          <span>{fmtTime(session.started_at)}</span>
          <span className="timeline-now">{fmtTime(scrubTime)}</span>
          <span>{fmtTime(sessionEnd)}</span>
        </div>
        <input
          type="range"
          className="scrubber"
          min={session.started_at}
          max={sessionEnd}
          value={scrubTime}
          step={1}
          onChange={onScrub}
        />
      </div>

      {/* Highlights */}
      <div className="hl-section">
        <div className="hl-header">
          <span className="hl-title">Highlights</span>
          <div className="hl-filters">
            {[
              { key: 'all',           label: 'All' },
              { key: 'known',         label: '● Known' },
              { key: 'mixed_unknown', label: '● Mixed' },
              { key: 'unknown',       label: '● Unknown' },
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

        {filteredHighlights.length === 0 ? (
          <p className="hint">No highlights in this session.</p>
        ) : (
          <div className="hl-cards">
            {filteredHighlights.map(h => (
              <div key={h.id} className={`hl-card hl-card-${h.category}`}>
                <img
                  className="hl-img"
                  src={`/api/history/${session.id}/highlight/${h.id}/image`}
                  alt={h.name || 'Unknown'}
                />
                <div className="hl-meta">
                  <span className="hl-time">{fmtTime(h.t)}</span>
                  <span className="hl-name">{h.name || 'Unknown'}</span>
                </div>
                <button className="btn btn-secondary hl-jump" onClick={() => jumpTo(h.t)}>
                  Jump
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
