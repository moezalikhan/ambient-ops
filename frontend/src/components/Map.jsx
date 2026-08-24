// Step 6: Leaflet map, route polyline coloured by Heat Priority Score.
export default function Map({ routeId }) {
  return (
    <div className="panel map-placeholder">
      <p className="placeholder">
        Map — Step 6
        <br />
        Route <code>{routeId || '—'}</code> will render here, coloured by HPS.
      </p>
    </div>
  )
}
