import { useState, useEffect } from 'react'
import { listHistory } from '../api'
import SessionPlayback from './SessionPlayback'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pad2(n) { return String(n).padStart(2, '0') }

function dateStr(d) {
  return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${d.getFullYear()}`
}

function timeStr(d) {
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/**
 * Format a session title from its timestamps.
 *
 * Same day:      "10.04.2026 12:10 – 12:30"
 * Cross-day:     "10.04.2026 23:55 – 11.04.2026 00:10"
 * No end:        "10.04.2026 12:10 – ongoing"
 */
function fmtSession(s) {
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

export default function HistoryView() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading]   = useState(true)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    listHistory()
      .then(d => setSessions(d.sessions))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // When a session is selected, show the playback view
  if (selected) {
    return (
      <SessionPlayback
        session={selected}
        onBack={() => setSelected(null)}
      />
    )
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>History</h2>
        {!loading && (
          <span className="badge">{sessions.length} session{sessions.length !== 1 ? 's' : ''}</span>
        )}
      </div>

      {loading && <p className="hint">Loading…</p>}

      {!loading && sessions.length === 0 && (
        <p className="hint">
          No saved sessions yet. Start and stop a surveillance session to create one.
        </p>
      )}

      <div className="history-list">
        {sessions.map(s => (
          <button
            key={s.id}
            className="session-card"
            onClick={() => setSelected(s)}
          >
            <div className="session-title">{fmtSession(s)}</div>
            <div className="session-stats">
              <span className="stat-badge stat-highlights">
                {s.highlight_count} highlight{s.highlight_count !== 1 ? 's' : ''}
              </span>
              <span className="stat-badge stat-alerts">
                {s.alert_count} alert{s.alert_count !== 1 ? 's' : ''}
              </span>
              <span className="stat-badge stat-frames">
                {s.frame_count} frames
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
