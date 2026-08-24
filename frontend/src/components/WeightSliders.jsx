// Step 7: the highest-return UI feature in the project. A judge who moves a
// slider and watches the ranking change understands immediately that this is a
// transparent model, not a black box.
export default function WeightSliders() {
  return (
    <div className="panel">
      <h2>Scoring weights</h2>
      <p className="placeholder">
        Step 7 — sliders for HEI (0.40), DTF (0.20), SVI (0.20), PSI (0.20).
        Moving one re-scores and re-ranks the route live.
      </p>
    </div>
  )
}
