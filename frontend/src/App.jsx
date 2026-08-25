import { useCallback, useEffect, useRef, useState } from 'react'
import { analyze, getAnalysis, getHealth, getRoutes } from './api.js'
import AgentTrace from './components/AgentTrace.jsx'
import Map from './components/Map.jsx'
import SegmentPanel from './components/SegmentPanel.jsx'

const POLL_MS = 1500

function useTheme() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem('ao-theme') || 'system',
  )
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    try { localStorage.setItem('ao-theme', theme) } catch { /* private mode */ }
  }, [theme])
  return [theme, setTheme]
}

export default function App() {
  const [routes, setRoutes] = useState([])
  const [routeId, setRouteId] = useState('')
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  const [running, setRunning] = useState(false)
  const [run, setRun] = useState(null)          // { run_id, status, result }
  const [selectedId, setSelectedId] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const timer = useRef(null)

  const [theme, setTheme] = useTheme()

  useEffect(() => {
    Promise.all([getRoutes(), getHealth()])
      .then(([r, h]) => {
        setRoutes(r)
        setHealth(h)
        if (r.length) setRouteId(r[0].id)
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => () => clearInterval(timer.current), [])

  const start = useCallback(async () => {
    setError(null)
    setRun(null)
    setSelectedId(null)
    setRunning(true)
    const startedAt = Date.now()
    setElapsed(0)

    try {
      const { run_id } = await analyze(routeId)
      timer.current = setInterval(async () => {
        setElapsed(Math.round((Date.now() - startedAt) / 1000))
        try {
          const d = await getAnalysis(run_id)
          setRun(d)
          if (d.status !== 'running') {
            clearInterval(timer.current)
            setRunning(false)
            if (d.status === 'failed') setError(d.error)
            const first = d.result?.segments?.[0]
            if (first) setSelectedId(first.id)
          }
        } catch (e) {
          clearInterval(timer.current)
          setRunning(false)
          setError(e.message)
        }
      }, POLL_MS)
    } catch (e) {
      setRunning(false)
      setError(e.message)
    }
  }, [routeId])

  const result = run?.status === 'completed' ? run.result : null
  const missing = health?.missing_keys || []

  return (
    <div className="app">
      <header>
        <h1>Ambient Ops</h1>
        <p className="tagline">Heat-aware route prioritisation for urban planners</p>
        <button
          type="button"
          className="theme-toggle"
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
          {theme === 'dark' ? 'Light' : 'Dark'} theme
        </button>
      </header>

      {error && (
        <div className="banner error">
          <span className="icon">!</span>
          <span>{error}</span>
        </div>
      )}
      {missing.length > 0 && (
        <div className="banner warn">
          <span className="icon">!</span>
          <span>Unconfigured: {missing.join(', ')}</span>
        </div>
      )}

      <div className="controls">
        <label htmlFor="route">Route</label>
        <select
          id="route"
          value={routeId}
          onChange={(e) => setRouteId(e.target.value)}
          disabled={running}
        >
          {routes.map((r) => (
            <option key={r.id} value={r.id}>
              {r.origin_name} → {r.destination_name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="primary"
          onClick={start}
          disabled={running || !routeId || missing.length > 0}
        >
          {running ? 'Analysing…' : 'Run analysis'}
        </button>
        {running && (
          <span className="status">
            {elapsed}s · {run?.tool_calls_so_far ?? 0} tool calls
          </span>
        )}
        {result && (
          <span className="status">
            HPS spread {result.hps_spread} · heat spread {result.heat_spread}
            {' '}{result.heat_layer?.units}
          </span>
        )}
      </div>

      <main className="layout">
        <div>
          <Map result={result} selectedId={selectedId} onSelect={setSelectedId} />
          {result?.brief && (
            <div className="panel" style={{ marginTop: 14 }}>
              <h2>Agent brief</h2>
              <div className="brief scroll-x">{result.brief}</div>
            </div>
          )}
        </div>
        <aside>
          <SegmentPanel
            result={result}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          <AgentTrace runId={run?.run_id} status={run?.status} />
        </aside>
      </main>
    </div>
  )
}
