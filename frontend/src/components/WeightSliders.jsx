import { DEFAULT_WEIGHTS, FACTOR_LABELS } from '../hps.js'

/* Spec section 6 calls this the highest-return feature in the project: a judge
 * who moves a slider and watches the ranking change understands immediately
 * that this is a transparent model rather than a black box.
 *
 * Re-scoring happens client-side, so the ranking updates as the slider moves.
 */
export default function WeightSliders({ weights, onChange, degenerate = [] }) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0)

  return (
    <div className="panel">
      <h2>Scoring weights</h2>

      {Object.keys(DEFAULT_WEIGHTS).map((k) => {
        const flat = degenerate.includes(k)
        const share = total > 0 ? (weights[k] / total) * 100 : 0
        return (
          <div className={`slider${flat ? ' degenerate' : ''}`} key={k}>
            <div className="slider-head">
              <label htmlFor={`w-${k}`}>
                <strong>{k}</strong> <span>{FACTOR_LABELS[k]}</span>
              </label>
              <span className="v">{share.toFixed(0)}%</span>
            </div>
            <input
              id={`w-${k}`}
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={weights[k]}
              onChange={(e) => onChange({ ...weights, [k]: Number(e.target.value) })}
            />
            {flat && (
              <p className="slider-note">
                Constant on this route — changing this weight cannot change the
                ranking.
              </p>
            )}
          </div>
        )
      })}

      <div className="slider-actions">
        <button type="button" onClick={() => onChange({ ...DEFAULT_WEIGHTS })}>
          Reset to defaults
        </button>
        {total <= 0 && <span className="warn-inline">All weights are zero</span>}
      </div>

      <p className="note">
        Weights are renormalised to sum to 1, so only their relative size
        matters. These defaults are a starting position, not an empirically
        derived optimum — which is exactly why they are adjustable.
      </p>
    </div>
  )
}
