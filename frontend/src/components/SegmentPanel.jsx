// Step 6: ranked segment list with HPS, factor breakdown, and the agent's
// recommended intervention per top-ranked segment.
export default function SegmentPanel({ routeId }) {
  return (
    <div className="panel">
      <h2>Ranked segments</h2>
      <p className="placeholder">
        Step 6 — segments for <code>{routeId || '—'}</code>, ranked by Heat
        Priority Score, each with its HEI / DTF / SVI / PSI breakdown.
      </p>
    </div>
  )
}
