// Step 7: live tool-call trace. This is what makes the Track 06 claim visible —
// the agent decides which tools to call in which order, and this shows it.
export default function AgentTrace() {
  return (
    <div className="panel">
      <h2>Agent trace</h2>
      <p className="placeholder">
        Step 7 — each tool call the agent made, in order, with arguments,
        duration, and whether it hit the cache.
      </p>
    </div>
  )
}
