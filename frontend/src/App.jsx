import { useState } from 'react'
import WebcamView from './components/WebcamView'
import FileUpload from './components/FileUpload'
import SurveillanceView from './components/SurveillanceView'
import HistoryView from './components/HistoryView'
import LoginPage from './components/LoginPage'
import SettingsPage from './components/SettingsPage'
import UserMenu from './components/UserMenu'
import { useAuth } from './context/AuthContext'
import './App.css'

const ADMIN_TABS  = ['Surveillance', 'Webcam', 'File Upload', 'History']
const VIEWER_TABS = ['Surveillance', 'History']

export default function App() {
  const { user, loading, isAdmin } = useAuth()
  const [tab, setTab]   = useState('Surveillance')
  const [view, setView] = useState('main')   // 'main' | 'settings'

  // Wait for the initial /auth/me cookie check to finish
  if (loading) {
    return (
      <div className="app-loading">
        <span>Loading…</span>
      </div>
    )
  }

  // Not logged in — show the login page
  if (!user) {
    return <LoginPage />
  }

  const tabs = isAdmin ? ADMIN_TABS : VIEWER_TABS

  return (
    <div className="app">
      <header className="header">
        <h1>Face Recognition</h1>
        {view === 'main' && (
          <nav className="tabs">
            {tabs.map(t => (
              <button
                key={t}
                className={`tab ${tab === t ? 'tab-active' : ''}`}
                onClick={() => setTab(t)}
              >
                {t}
              </button>
            ))}
          </nav>
        )}
        {view === 'settings' && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setView('main')}
          >
            ← Back
          </button>
        )}
        <div className="header-user">
          <UserMenu onOpenSettings={() => setView('settings')} />
        </div>
      </header>

      <main className="main">
        {view === 'settings' && isAdmin && <SettingsPage />}
        {view === 'main' && (
          <>
            {tab === 'Surveillance' && <SurveillanceView />}
            {tab === 'Webcam'       && isAdmin && <WebcamView />}
            {tab === 'File Upload'  && isAdmin && <FileUpload />}
            {tab === 'History'      && <HistoryView />}
          </>
        )}
      </main>
    </div>
  )
}
