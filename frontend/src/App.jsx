import { useState } from 'react'
import WebcamView from './components/WebcamView'
import FileUpload from './components/FileUpload'
import './App.css'

const TABS = ['Webcam', 'File Upload']

export default function App() {
  const [tab, setTab] = useState('Webcam')

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
      </header>

      <main className="main">
        {tab === 'Webcam' && <WebcamView />}
        {tab === 'File Upload' && <FileUpload />}
      </main>
    </div>
  )
}
