// Thin wrapper over the backend. Endpoint shapes match backend/main.py.

async function req(path, options) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const getHealth = () => req('/health')
export const getRoutes = () => req('/routes')

export const analyze = (route_id, weights) =>
  req('/analyze', { method: 'POST', body: JSON.stringify({ route_id, weights }) })
export const getAnalysis = (runId) => req(`/analyze/${runId}`)
export const getAgentTrace = (runId) => req(`/agent-trace/${runId}`)
export const getInterventions = () => req('/interventions')
export const simulate = (run_id, segment_id, intervention) =>
  req('/simulate', {
    method: 'POST',
    body: JSON.stringify({ run_id, segment_id, intervention }),
  })
