import { useEffect, useState } from 'react'
import { getAgentTrace } from '../api.js'

/* The agent decides which tools to call and in what order. This shows that it
 * did — which is the whole Track 06 claim, so spec section 9 says not to skip
 * it. Polls while a run is in flight so the calls appear as they happen.
 */
export default function AgentTrace({ runId, status }) {
  const [trace, setTrace] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!runId) { setTrace(null); return undefined }
    let alive = true
    const tick = () => {
      getAgentTrace(runId)
        .then((t) => { if (alive) setTrace(t) })
        .catch((e) => { if (alive) setError(e.message) })
    }
    tick()
    if (status !== 'running') return () => { alive = false }
    const id = setInterval(tick, 1200)
    return () => { alive = false; clearInterval(id) }
  }, [runId, status])

  if (!runId) {
    return (
      <div className="panel">
        <h2>Agent trace</h2>
        <p className="placeholder">
          Every tool call the agent made, in the order it chose them.
        </p>
      </div>
    )
  }

  const calls = trace?.tool_calls || []

  return (
    <div className="panel">
      <h2>
        Agent trace
        {trace && <span className="h2-sub"> · {trace.elapsed_s}s</span>}
      </h2>

      {trace && (
        <p className="trace-meta">
          {trace.model} · {calls.length} call{calls.length === 1 ? '' : 's'}
          {status === 'running' && ' · running'}
        </p>
      )}
      {error && <p className="placeholder">{error}</p>}

      <ol className="trace">
        {calls.map((c) => (
          <li key={c.seq} className={c.ok ? '' : 'failed'}>
            <div className="trace-row">
              <span className="tool">{c.tool}</span>
              <span className="ms">{c.duration_ms} ms</span>
            </div>
            {Object.keys(c.arguments || {}).length > 0 && (
              <div className="args">
                {Object.entries(c.arguments)
                  .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                  .join('  ')}
              </div>
            )}
            <div className="summary">
              {c.cache_hit && <span className="chip">cached</span>}
              {c.result_summary}
            </div>
          </li>
        ))}
        {status === 'running' && (
          <li className="pending"><span className="tool">thinking…</span></li>
        )}
      </ol>

      {calls.length > 0 && (
        <p className="note">
          Durations are the tool call itself. Where they are near zero the
          answer came from the local cache — the wall-clock time is the model
          deciding what to call next.
        </p>
      )}
    </div>
  )
}
