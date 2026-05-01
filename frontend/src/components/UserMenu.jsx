import { useState, useRef, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'

/**
 * Top-right account dropdown.
 *
 * Shows "<role> (<username>)" and opens on hover or focus. Admins get a
 * Settings entry; viewers only see Logout. Hover-leave is delayed slightly
 * so the user can move their cursor onto the menu without it closing
 * mid-traversal.
 */
export default function UserMenu({ onOpenSettings }) {
  const { user, isAdmin, logout } = useAuth()
  const [open, setOpen]           = useState(false)
  const closeTimer                = useRef(null)

  useEffect(() => () => clearTimeout(closeTimer.current), [])

  if (!user) return null

  function handleEnter() {
    clearTimeout(closeTimer.current)
    setOpen(true)
  }

  function handleLeave() {
    closeTimer.current = setTimeout(() => setOpen(false), 120)
  }

  return (
    <div
      className="user-menu"
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
    >
      <button
        className="user-menu-trigger"
        onFocus={handleEnter}
        onBlur={handleLeave}
        type="button"
      >
        <span className={`user-role user-role-${user.role}`}>{user.role}</span>
        <span className="user-name">({user.username})</span>
        <span className="user-caret" aria-hidden="true">▾</span>
      </button>

      {open && (
        <div className="user-menu-dropdown" role="menu">
          {isAdmin && (
            <button
              className="user-menu-item"
              onClick={() => { setOpen(false); onOpenSettings() }}
              role="menuitem"
            >
              Settings
            </button>
          )}
          <button
            className="user-menu-item user-menu-item-danger"
            onClick={() => { setOpen(false); logout() }}
            role="menuitem"
          >
            Logout
          </button>
        </div>
      )}
    </div>
  )
}
