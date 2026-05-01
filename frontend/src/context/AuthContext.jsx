import { createContext, useContext, useEffect, useState } from 'react'
import { authMe, authLogin, authLogout } from '../api'

const AuthContext = createContext(null)

/**
 * Provides authentication state to the whole app.
 *
 * Values exposed via useAuth():
 *   user    — { username, role } when logged in, null otherwise
 *   loading — true while the initial /auth/me check is in flight
 *   isAdmin — convenience boolean
 *   login(username, password) — resolves on success, throws on failure
 *   logout()                  — clears the cookie and resets user to null
 */
export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null)
  const [loading, setLoading] = useState(true)  // checking cookie on page load

  // On mount, ask the backend if the cookie is still valid
  useEffect(() => {
    authMe()
      .then(data => setUser(data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  async function login(username, password) {
    const data = await authLogin(username, password)  // throws on 401
    setUser(data)
  }

  async function logout() {
    await authLogout().catch(() => {})  // best-effort; always clear local state
    setUser(null)
  }

  const isAdmin = user?.role === 'admin'

  return (
    <AuthContext.Provider value={{ user, loading, isAdmin, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
