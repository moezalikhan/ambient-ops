import { useEffect, useState } from 'react'
import { getInterventions, simulate } from '../api.js'

/* What-if mode. Spec section 8 calls this the differentiator: most entries
 * stop at a ranked heat map, this lets a planner ask what happens if they act.
 *
 * Every result carries whether its magnitude is sourced. An unsourced number
 * shown as a finding is the failure spec section 6 warns about; the same
 * number shown as a labelled assumption is a legitimate what-if.
 */
export default function Simulate({ runId, segment, disabled }) {
  const [options, setOptions] = useState([])
  const [choice, setChoice] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    getInterventions()
      .then((d) => {
        setOptions(d.interventions)
        if (d.interventions.length) setChoice(d.interventions[0].id)
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => { setResult(null); setError(null) }, [segment?.id])

  const run = async () => {
    if (!runId || !segment || !choice) return
    setBusy(true); setError(null)
    try {
      setResult(await simulate(runId, segment.id, choice))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const selected = options.find((o) => o.id === choice)

  return (
    <div className="panel">
      <h2>What if we build it?</h2>

      {disabled ? (
        <p className="placeholder">Run an analysis, then pick a segment.</p>
      ) : (
        <>
          <p className="trace-meta">
            Applying to segment {segment.index} (rank {segment.rank})
          </p>

          <div className="sim-controls">
            <select
              value={choice}
              onChange={(e) => setChoice(e.target.value)}
              aria-label="Intervention"
            >
              {options.map((o) => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </select>
            <button type="button" className="primary" onClick={run} disabled={busy}>
              {busy ? 'Simulating…' : 'Simulate'}
            </button>
          </div>

          {selected && !selected.sourced && (
            <p className="slider-note">
              The magnitude of this change is an assumption, not a sourced
              cooling estimate.
            </p>
          )}

          {error && <p className="placeholder">{error}</p>}

          {result && (
            <div className="sim-result">
              <div className="delta">
                <span className="before">{result.before.HPS.toFixed(1)}</span>
                <span className="arrow">→</span>
                <span className="after">{result.after.HPS.toFixed(1)}</span>
                <span className={`chg ${result.delta_HPS <= 0 ? 'good' : 'bad'}`}>
                  {result.delta_HPS > 0 ? '+' : ''}{result.delta_HPS.toFixed(2)}
                </span>
              </div>
              <dl style={{ margin: '10px 0 0' }}>
                <div className="kv">
                  <dt>Rank</dt>
                  <dd>
                    {result.before.rank} → {result.after.rank}
                    {result.delta_rank !== 0 && (
                      <span className="chg good">
                        {' '}({result.delta_rank > 0 ? '-' : '+'}
                        {Math.abs(result.delta_rank)})
                      </span>
                    )}
                  </dd>
                </div>
                <div className="kv">
                  <dt>Segments treated</dt>
                  <dd>{result.segments_affected.length}</dd>
                </div>
                <div className="kv">
                  <dt>Magnitude sourced</dt>
                  <dd>{result.assumption_sourced ? 'yes' : 'no — illustrative'}</dd>
                </div>
              </dl>
              <p className="note"><strong>Assumes:</strong> {result.assumption}</p>
              <p className="note"><strong>Trade-off:</strong> {result.caveat}</p>
              {result.delta_HPS === 0 && (
                <p className="note">
                  A zero change is the correct answer here, not a failure — this
                  intervention does not alter any factor the model reads.
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
