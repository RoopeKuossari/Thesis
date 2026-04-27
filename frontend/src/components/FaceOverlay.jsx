/**
 * Draws bounding boxes and name labels onto a canvas element.
 *
 * Face status → box colour:
 *   'known'       → green  (#00e676)
 *   'unknown'     → red    (#ff1744)
 *   'spoof'       → orange (#ff9100)
 *   'identifying' → yellow (#ffd600)
 */
export function drawFaces(canvas, faces, srcWidth, srcHeight) {
  if (!canvas || !faces?.length) {
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
    return
  }

  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)

  const sx = canvas.width  / srcWidth
  const sy = canvas.height / srcHeight

  for (const face of faces) {
    const [x, y, w, h] = face.box
    const cx = x * sx
    const cy = y * sy
    const cw = w * sx
    const ch = h * sy

    let color, label
    if (face.status === 'identifying') {
      color = '#ffd600'
      label = 'Identifying…'
    } else if (face.status === 'spoof') {
      color = '#ff9100'
      label = face.liveness_score != null
        ? `Spoof (${face.liveness_score.toFixed(2)})`
        : 'Spoof'
    } else if (face.status === 'known') {
      color = '#00e676'
      label = face.distance != null
        ? `${face.name} (${face.distance.toFixed(3)})`
        : face.name
    } else {
      // unknown
      color = '#ff1744'
      label = 'Unknown'
    }

    // Bounding box
    ctx.strokeStyle = color
    ctx.lineWidth = 2
    ctx.strokeRect(cx, cy, cw, ch)

    // Label background
    ctx.font = 'bold 14px sans-serif'
    const textW = ctx.measureText(label).width
    ctx.fillStyle = color
    ctx.fillRect(cx, cy - 22, textW + 10, 22)

    // Label text
    ctx.fillStyle = '#000'
    ctx.fillText(label, cx + 5, cy - 5)
  }
}
