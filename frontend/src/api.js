const BASE = '/api'

// ---------------------------------------------------------------------------
// Authentication
// ---------------------------------------------------------------------------

export async function authMe() {
  const res = await fetch(`${BASE}/auth/me`, { credentials: 'include' })
  if (!res.ok) throw new Error('Not authenticated')
  return res.json()
}

export async function authLogin(username, password) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error('Invalid credentials')
  return res.json()
}

export async function authLogout() {
  const res = await fetch(`${BASE}/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function identifyImage(file) {
  const form = new FormData()
  form.append('image', file)
  const res = await fetch(`${BASE}/identify`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function identifyBlob(blob) {
  const file = new File([blob], 'frame.jpeg', { type: 'image/jpeg' })
  return identifyImage(file)
}

export async function registerBlob(name, blob) {
  const form = new FormData()
  form.append('name', name)
  form.append('images', new File([blob], 'frame.jpeg', { type: 'image/jpeg' }))
  const res = await fetch(`${BASE}/register`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function listIdentities() {
  const res = await fetch(`${BASE}/identities`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function startSurveillance(cameraIndex = 0) {
  const res = await fetch(`${BASE}/surveillance/start?camera_index=${cameraIndex}`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function stopSurveillance() {
  const res = await fetch(`${BASE}/surveillance/stop`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getSurveillanceBuffer() {
  const res = await fetch(`${BASE}/surveillance/buffer`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getHighlights() {
  const res = await fetch(`${BASE}/surveillance/highlights`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function ingestSurveillanceFrame(blob) {
  const form = new FormData()
  form.append('image', new File([blob], 'frame.jpeg', { type: 'image/jpeg' }))
  const res = await fetch(`${BASE}/surveillance/ingest`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

export async function listHistory() {
  const res = await fetch(`${BASE}/history`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getHistoryHighlights(sessionId) {
  const res = await fetch(`${BASE}/history/${sessionId}/highlights`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
