import { FACTOR_LABELS, hpsVar } from '../hps.js'

function FactorBars({ segment, degenerate }) {
  return (
    <div className="factors">
      {['HEI', 'DTF', 'SVI', 'PSI'].map((k) => {
        const flat = degenerate.includes(k)
        const v = segment[k] ?? 0
        return (
          <div className={`factor${flat ? ' degenerate' : ''}`} key={k}>
            <span className="k" title={FACTOR_LABELS[k]}>{k}</span>
            <span className="track">
              <span style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }} />
            </span>
            <span className="v">{v.toFixed(2)}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function SegmentPanel({ result, selectedId, onSelect }) {
  const segments = result?.segments || []

  if (!segments.length) {
    return (
      <div className="panel">
        <h2>Ranked segments</h2>
        <p className="placeholder">
          Pick a route and run the analysis. The agent will rank every ~50 m
          segment and recommend which one to fix first.
        </p>
      </div>
    )
  }

  const degenerate = result.degenerate_factors || []
  const selected = segments.find((s) => s.id === selectedId) || segments[0]
  const maxHps = Math.max(...segments.map((s) => s.HPS || 0), 1)

  return (
    <>
      <div className="panel">
        <h2>Ranked segments · {segments.length}</h2>

        <div className="seg-list">
          {segments.map((s) => (
            <button
              type="button"
              className="seg"
              key={s.id}
              aria-selected={s.id === selected.id}
              onClick={() => onSelect?.(s.id)}
            >
              <span className="rank">{s.rank}</span>
              <span>
                <span className="name">Segment {s.index}</span>
                <span className="bar">
                  <span
                    style={{
                      width: `${((s.HPS || 0) / maxHps) * 100}%`,
                      background: hpsVar(s.HPS),
                    }}
                  />
                </span>
              </span>
              <span className="score">
                <i className="swatch" style={{ background: hpsVar(s.HPS) }} />
                {s.HPS?.toFixed(1)}
              </span>
            </button>
          ))}
        </div>

        <p className="note">
          Scores are relative within this route. Colour bins are fixed on the
          0–100 scale so the same score always reads the same, on any route.
        </p>
      </div>

      <div className="panel">
        <h2>Segment {selected.index} · rank {selected.rank}</h2>
        <FactorBars segment={selected} degenerate={degenerate} />

        <dl style={{ margin: '14px 0 0' }}>
          <div className="kv">
            <dt>Heat Priority Score</dt>
            <dd>{selected.HPS?.toFixed(2)}</dd>
          </div>
          <div className="kv">
            <dt>Continuous exposed run</dt>
            <dd>{selected.raw?.exposed_run_m ?? '—'} m</dd>
          </div>
          <div className="kv">
            <dt>Tree cover</dt>
            <dd>
              {selected.landcover?.tree != null
                ? `${selected.landcover.tree.toFixed(1)}%`
                : '—'}
            </dd>
          </div>
          <div className="kv">
            <dt>Raw heat</dt>
            <dd>
              {selected.raw?.heat != null
                ? `${selected.raw.heat.toFixed(2)} h`
                : '—'}
            </dd>
          </div>
        </dl>

        {degenerate.length > 0 && (
          <p className="note">
            {degenerate.join(', ')} {degenerate.length === 1 ? 'is' : 'are'} constant
            across this route and contributed nothing to the ranking — shown greyed
            above.
          </p>
        )}
      </div>
    </>
  )
}
