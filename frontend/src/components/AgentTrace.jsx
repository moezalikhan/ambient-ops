// Live view lands in Step 7. The trace endpoint is already serving, so this
// shows the run id rather than pretending there is nothing to see.
export default function AgentTrace({ runId, status }) {
  return (
    <div className="panel">
      <h2>Agent trace</h2>
      {runId ? (
        <p className="placeholder">
          Run <code>{runId}</code> · {status}
          <br />
          Step 7 renders each tool call here — name, arguments, duration, and
          whether it hit the cache. Available now at{' '}
          <code>/api/agent-trace/{runId}</code>.
        </p>
      ) : (
        <p className="placeholder">
          Step 7 — every tool call the agent made, in the order it chose them.
        </p>
      )}
    </div>
  )
}
