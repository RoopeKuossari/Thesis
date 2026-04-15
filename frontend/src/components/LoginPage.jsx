import { useState } from 'react'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const { login } = useAuth()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState(null)
  const [loading, setLoading]   = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(username, password)
    } catch {
      setError('Invalid username or password.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-backdrop">
      <div className="login-card">
        <h1 className="login-title">Face Recognition</h1>
        <p className="login-subtitle">Sign in to continue</p>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-field">
            <label className="login-label" htmlFor="username">Username</label>
            <input
              id="username"
              className="text-input login-input"
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={e => setUsername(e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <div className="login-field">
            <label className="login-label" htmlFor="password">Password</label>
            <input
              id="password"
              className="text-input login-input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              disabled={loading}
              required
            />
          </div>

          {error && <p className="error login-error">{error}</p>}

          <button
            className="btn btn-primary login-btn"
            type="submit"
            disabled={loading || !username || !password}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
