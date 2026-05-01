import { useState, useEffect, useRef } from 'react'
import {
  getSettings, updateSettings,
  listIdentities, deleteIdentity, registerBlob,
  listHistory,
  listUsers, createUser, deleteUser,
} from '../api'
import { useAuth } from '../context/AuthContext'

// ---------------------------------------------------------------------------
// Human-friendly labels for each tunable. The schema (min / max / type)
// comes from the backend so the UI never needs to be kept in sync manually.
// ---------------------------------------------------------------------------
const SETTING_LABELS = {
  identity_threshold:     { label: 'Identity match threshold',
                            help:  'Cosine distance below which a face is treated as a known person. Lower = stricter.' },
  scene_grace:            { label: 'Scene grace period (seconds)',
                            help:  'How long the current highlight stays open after the last face leaves frame.' },
  loitering_seconds:      { label: 'Loitering threshold (seconds)',
                            help:  'How long an unknown must stay continuously in frame before it counts as loitering.' },
  known_grace_seconds:    { label: 'Known-person grace (seconds)',
                            help:  'After a known person is seen, alerts are suppressed for this many seconds.' },
  alert_cooldown_seconds: { label: 'Telegram alert cooldown (seconds)',
                            help:  'Minimum gap between Telegram alerts for the same loitering event.' },
}

// Step picked per setting so sliders feel natural for floats vs. ints.
function stepFor(key, schema) {
  if (schema.type === 'int') return 1
  if (key === 'identity_threshold') return 0.01
  return 0.1
}

function dateStr(ms) {
  const d = new Date(ms)
  return d.toLocaleString()
}


export default function SettingsPage() {
  return (
    <div className="settings">
      <TuningPanel />
      <IdentitiesPanel />
      <HistoryPanel />
      <UsersPanel />
    </div>
  )
}


// ---------------------------------------------------------------------------
// Tuning — sliders for cooldowns, thresholds, grace periods
// ---------------------------------------------------------------------------

function TuningPanel() {
  const [values, setValues]   = useState(null)
  const [schema, setSchema]   = useState(null)
  const [defaults, setDef]    = useState(null)
  const [savedKey, setSaved]  = useState(null)
  const [error, setError]     = useState(null)
  const saveTimerRef          = useRef({})

  useEffect(() => {
    getSettings()
      .then(d => { setValues(d.settings); setSchema(d.schema); setDef(d.defaults) })
      .catch(e => setError(e.message))
  }, [])

  function pushUpdate(key, raw) {
    // Debounce so sliding the range doesn't fire one PUT per pixel
    clearTimeout(saveTimerRef.current[key])
    saveTimerRef.current[key] = setTimeout(async () => {
      try {
        const data = await updateSettings({ [key]: raw })
        setValues(data.settings)
        setSaved(key)
        setTimeout(() => setSaved(s => (s === key ? null : s)), 1500)
      } catch (e) {
        setError(e.message)
      }
    }, 300)
  }

  function onChange(key, e) {
    const raw = e.target.value
    setValues(v => ({ ...v, [key]: raw }))
    pushUpdate(key, raw)
  }

  function reset(key) {
    setValues(v => ({ ...v, [key]: defaults[key] }))
    pushUpdate(key, defaults[key])
  }

  if (!values || !schema) {
    return (
      <div className="panel">
        <div className="panel-header"><h2>Tuning</h2></div>
        {error ? <p className="error">{error}</p> : <p className="hint">Loading…</p>}
      </div>
    )
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Tuning</h2>
        <span className="badge">live</span>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="settings-grid">
        {Object.entries(schema).map(([key, s]) => {
          const meta  = SETTING_LABELS[key] || { label: key, help: '' }
          const value = values[key]
          const step  = stepFor(key, s)
          const isDefault = String(value) === String(defaults[key])
          return (
            <div key={key} className="setting-row">
              <div className="setting-head">
                <label className="setting-label">{meta.label}</label>
                <div className="setting-value">
                  <input
                    className="text-input setting-number"
                    type="number"
                    min={s.min}
                    max={s.max}
                    step={step}
                    value={value}
                    onChange={e => onChange(key, e)}
                  />
                  {!isDefault && (
                    <button className="btn btn-secondary btn-sm" onClick={() => reset(key)}>
                      Reset
                    </button>
                  )}
                  {savedKey === key && <span className="setting-saved">Saved</span>}
                </div>
              </div>
              <input
                type="range"
                className="scrubber"
                min={s.min}
                max={s.max}
                step={step}
                value={value}
                onChange={e => onChange(key, e)}
              />
              <div className="setting-meta">
                <span>{s.min}</span>
                <span className="hint">{meta.help}</span>
                <span>{s.max}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Identities — list, register from webcam, remove
// ---------------------------------------------------------------------------

function IdentitiesPanel() {
  const [names, setNames]         = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const [registerName, setRName]  = useState('')
  const [registering, setReg]     = useState(false)
  const [msg, setMsg]             = useState(null)

  const videoRef = useRef(null)

  function refresh() {
    listIdentities()
      .then(d => setNames(d.identities))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

  async function captureBlobs(count = 3) {
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: true })
    } catch (e) {
      throw new Error('Could not access webcam: ' + e.message)
    }

    const video = videoRef.current
    video.srcObject = stream
    await video.play()

    const c = document.createElement('canvas')
    const blobs = []
    for (let i = 0; i < count; i++) {
      c.width  = video.videoWidth
      c.height = video.videoHeight
      c.getContext('2d').drawImage(video, 0, 0)
      const blob = await new Promise(res => c.toBlob(res, 'image/jpeg', 0.9))
      if (blob) blobs.push(blob)
      await new Promise(r => setTimeout(r, 200))
    }

    stream.getTracks().forEach(t => t.stop())
    video.srcObject = null
    return blobs
  }

  async function handleRegister() {
    const name = registerName.trim()
    if (!name) { setMsg('Enter a name first.'); return }
    setReg(true); setMsg(null); setError(null)
    try {
      const blobs = await captureBlobs(3)
      let total = 0
      for (const b of blobs) {
        const data = await registerBlob(name, b)
        total += data.faces_registered
      }
      setMsg(total > 0
        ? `Registered ${total} face(s) for "${name}".`
        : 'No face detected in captured frames.'
      )
      setRName('')
      refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setReg(false)
    }
  }

  async function handleDelete(name) {
    if (!confirm(`Remove "${name}" from the gallery?`)) return
    try {
      await deleteIdentity(name)
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Known faces</h2>
        {!loading && <span className="badge">{names.length}</span>}
      </div>

      <video ref={videoRef} style={{ display: 'none' }} playsInline muted />

      <div className="register-row">
        <input
          className="text-input"
          type="text"
          placeholder="Name"
          value={registerName}
          onChange={e => setRName(e.target.value)}
          disabled={registering}
        />
        <button
          className="btn btn-primary"
          onClick={handleRegister}
          disabled={registering}
        >
          {registering ? 'Capturing…' : 'Add face from webcam'}
        </button>
        {msg && <span className="hint">{msg}</span>}
      </div>

      {loading && <p className="hint">Loading…</p>}
      {!loading && names.length === 0 && (
        <p className="hint">No registered identities yet.</p>
      )}

      <ul className="identity-list">
        {names.map(n => (
          <li key={n} className="identity-row">
            <span className="identity-name">{n}</span>
            <button
              className="btn btn-danger btn-sm"
              onClick={() => handleDelete(n)}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      {error && <p className="error">{error}</p>}
    </div>
  )
}


// ---------------------------------------------------------------------------
// History — list saved sessions and allow deletion
// ---------------------------------------------------------------------------

function HistoryPanel() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)

  function refresh() {
    setLoading(true)
    listHistory()
      .then(d => setSessions(d.sessions))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

  async function handleDelete(s) {
    if (!confirm(`Delete session ${s.id}? This removes all frames and highlights for it.`)) return
    try {
      const res = await fetch(`/api/history/${encodeURIComponent(s.id)}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (!res.ok) throw new Error(await res.text())
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>History footages</h2>
        {!loading && (
          <span className="badge">{sessions.length} session{sessions.length !== 1 ? 's' : ''}</span>
        )}
      </div>

      {loading && <p className="hint">Loading…</p>}
      {!loading && sessions.length === 0 && (
        <p className="hint">No saved sessions.</p>
      )}

      <ul className="identity-list">
        {sessions.map(s => (
          <li key={s.id} className="identity-row">
            <span className="identity-name">
              {dateStr(s.started_at)}
              <span className="hint" style={{ marginLeft: 8 }}>
                · {s.frame_count} frames · {s.highlight_count} highlights
              </span>
            </span>
            <button
              className="btn btn-danger btn-sm"
              onClick={() => handleDelete(s)}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>

      {error && <p className="error">{error}</p>}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Users — list, create, delete
// ---------------------------------------------------------------------------

function UsersPanel() {
  const { user: me } = useAuth()
  const [users, setUsers]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)

  const [newName, setNewName]   = useState('')
  const [newPass, setNewPass]   = useState('')
  const [newRole, setNewRole]   = useState('viewer')
  const [creating, setCreating] = useState(false)

  function refresh() {
    setLoading(true)
    listUsers()
      .then(d => setUsers(d.users))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

  async function handleCreate(e) {
    e.preventDefault()
    setError(null)
    if (newPass.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    setCreating(true)
    try {
      await createUser(newName.trim(), newPass, newRole)
      setNewName(''); setNewPass(''); setNewRole('viewer')
      refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(u) {
    if (!confirm(`Delete user "${u.username}"?`)) return
    try {
      await deleteUser(u.username)
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Users</h2>
        {!loading && <span className="badge">{users.length}</span>}
      </div>

      <form className="register-row" onSubmit={handleCreate}>
        <input
          className="text-input"
          type="text"
          placeholder="Username"
          value={newName}
          onChange={e => setNewName(e.target.value)}
          required
          minLength={1}
        />
        <input
          className="text-input"
          type="password"
          placeholder="Password (8+ chars)"
          value={newPass}
          onChange={e => setNewPass(e.target.value)}
          required
          minLength={8}
        />
        <select
          className="text-input"
          value={newRole}
          onChange={e => setNewRole(e.target.value)}
        >
          <option value="viewer">Viewer</option>
          <option value="admin">Admin</option>
        </select>
        <button className="btn btn-primary" type="submit" disabled={creating}>
          {creating ? 'Creating…' : 'Create user'}
        </button>
      </form>

      {loading && <p className="hint">Loading…</p>}

      <ul className="identity-list">
        {users.map(u => (
          <li key={u.username} className="identity-row">
            <span className="identity-name">
              {u.username}
              <span className={`user-role user-role-${u.role}`} style={{ marginLeft: 10 }}>
                {u.role}
              </span>
              {u.username === me?.username && (
                <span className="hint" style={{ marginLeft: 8 }}>(you)</span>
              )}
            </span>
            <button
              className="btn btn-danger btn-sm"
              onClick={() => handleDelete(u)}
              disabled={u.username === me?.username}
              title={u.username === me?.username ? 'You cannot delete your own account' : ''}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>

      {error && <p className="error">{error}</p>}
    </div>
  )
}
