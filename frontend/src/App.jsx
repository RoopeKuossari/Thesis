import { useState } from 'react'
import WebcamView from './components/WebcamView'
import FileUpload from './components/FileUpload'
import SurveillanceView from './components/SurveillanceView'
import HistoryView from './components/HistoryView'
import LoginPage from './components/LoginPage'
import { useAuth } from './context/AuthContext'
import './App.css'

const TABS = ['Surveillance', 'Webcam', 'File Upload', 'History']

export default function App() {
  const { user, loading, logout } = useAuth()
  const [tab, setTab] = useState('Surveillance')

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

  return (
    <div className="app">
      <header className="header">
        <h1>Face Recognition</h1>
        <nav className="tabs">
          {TABS.map(t => (
            <button
              key={t}
              className={`tab ${tab === t ? 'tab-active' : ''}`}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </nav>
        <div className="header-user">
          <span className="header-username">{user.username}</span>
          <button className="btn btn-secondary btn-sm" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      <main className="main">
        {tab === 'Surveillance' && <SurveillanceView />}
        {tab === 'Webcam'       && <WebcamView />}
        {tab === 'File Upload'  && <FileUpload />}
        {tab === 'History'      && <HistoryView />}
      </main>
    </div>
  )
}
