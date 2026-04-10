import { useState } from 'react'
import WebcamView from './components/WebcamView'
import FileUpload from './components/FileUpload'
import SurveillanceView from './components/SurveillanceView'
import HistoryView from './components/HistoryView'
import './App.css'

const TABS = ['Surveillance', 'Webcam', 'File Upload', 'History']

export default function App() {
  const [tab, setTab] = useState('Surveillance')

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
        {tab === 'Surveillance' && <SurveillanceView />}
        {tab === 'Webcam'       && <WebcamView />}
        {tab === 'File Upload'  && <FileUpload />}
        {tab === 'History'      && <HistoryView />}
      </main>
    </div>
  )
}
