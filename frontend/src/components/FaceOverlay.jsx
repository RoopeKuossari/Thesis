/**
 * Draws bounding boxes and name labels onto a canvas element.
 *
 * Props:
 *   faces      — array of face result objects from the API
 *   srcWidth   — natural/video width of the source image
 *   srcHeight  — natural/video height of the source image
 *   canvasRef  — ref to the <canvas> element
 */
export function drawFaces(canvas, faces, srcWidth, srcHeight) {
  if (!canvas || !faces?.length) {
    // Clear if nothing to draw
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height)
    return
  }

  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)

  // Scale factors: source pixels → canvas pixels
  const sx = canvas.width / srcWidth
  const sy = canvas.height / srcHeight

  for (const face of faces) {
    const [x, y, w, h] = face.box
    const cx = x * sx
    const cy = y * sy
    const cw = w * sx
    const ch = h * sy

    const isKnown = face.name !== 'Unknown'
    const color = isKnown ? '#00e676' : '#ff1744'

    // Bounding box
    ctx.strokeStyle = color
    ctx.lineWidth = 2
    ctx.strokeRect(cx, cy, cw, ch)

    // Label background
    const label = isKnown
      ? `${face.name} (${face.distance.toFixed(3)})`
      : 'Unknown'
    ctx.font = 'bold 14px sans-serif'
    const textW = ctx.measureText(label).width
    ctx.fillStyle = color
    ctx.fillRect(cx, cy - 22, textW + 10, 22)

    // Label text
    ctx.fillStyle = '#000'
    ctx.fillText(label, cx + 5, cy - 5)
  }
}
