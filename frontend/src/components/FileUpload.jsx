import { useRef, useState } from 'react'
import { identifyImage } from '../api'
import { drawFaces } from './FaceOverlay'

export default function FileUpload() {
  const inputRef = useRef(null)
  const imgRef = useRef(null)
  const canvasRef = useRef(null)

  const [preview, setPreview] = useState(null)
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleFile(file) {
    if (!file) return
    setError(null)
    setResults([])

    // Show preview
    const url = URL.createObjectURL(file)
    setPreview(url)

    setLoading(true)
    try {
      const data = await identifyImage(file)
      setResults(data.faces)

      // Wait for image to render, then draw overlays
      requestAnimationFrame(() => {
        const img = imgRef.current
        const canvas = canvasRef.current
        if (!img || !canvas) return
        canvas.width = img.naturalWidth
        canvas.height = img.naturalHeight
        drawFaces(canvas, data.faces, img.naturalWidth, img.naturalHeight)
      })
    } catch (e) {
      setError('Identification failed: ' + e.message)
    } finally {
      setLoading(false)
    }
  }

  function onInputChange(e) {
    handleFile(e.target.files[0])
  }

  function onDrop(e) {
    e.preventDefault()
    handleFile(e.dataTransfer.files[0])
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>File Upload</h2>
      </div>

      {/* Drop zone */}
      <div
        className="dropzone"
        onClick={() => inputRef.current.click()}
        onDrop={onDrop}
        onDragOver={e => e.preventDefault()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={onInputChange}
        />
        {loading ? (
          <p>Identifying...</p>
        ) : (
          <p>Drop an image here or <span className="link">click to browse</span></p>
        )}
      </div>

      {/* Image + overlay */}
      {preview && (
        <div className="image-wrapper">
          <img
            ref={imgRef}
            src={preview}
            className="uploaded-img"
            alt="uploaded"
            onLoad={() => {
              // Re-draw after image finishes loading
              const img = imgRef.current
              const canvas = canvasRef.current
              if (!img || !canvas || !results.length) return
              canvas.width = img.naturalWidth
              canvas.height = img.naturalHeight
              drawFaces(canvas, results, img.naturalWidth, img.naturalHeight)
            }}
          />
          <canvas ref={canvasRef} className="overlay" />
        </div>
      )}

      {/* Results list */}
      {results.length > 0 && (
        <div className="results">
          <h3>Results</h3>
          {results.map((f, i) => (
            <div key={i} className={`result-row ${f.name === 'Unknown' ? 'unknown' : 'known'}`}>
              <span className="result-name">{f.name}</span>
              <span className="result-meta">
                distance {f.distance.toFixed(4)} · detection {(f.detection_conf * 100).toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      )}

      {results.length === 0 && preview && !loading && !error && (
        <p className="hint">No faces detected.</p>
      )}

      {error && <p className="error">{error}</p>}
    </div>
  )
}
