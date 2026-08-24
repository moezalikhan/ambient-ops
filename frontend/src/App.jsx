import { useEffect, useState } from 'react'
import { getHealth, getRoutes } from './api.js'
import Map from './components/Map.jsx'
import SegmentPanel from './components/SegmentPanel.jsx'
import WeightSliders from './components/WeightSliders.jsx'
import AgentTrace from './components/AgentTrace.jsx'

export default function App() {
  const [routes, setRoutes] = useState([])
  const [selected, setSelected] = useState('')
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  // Step 1 proves the wiring end to end: backend reachable, contract holds.
  useEffect(() => {
    Promise.all([getRoutes(), getHealth()])
      .then(([r, h]) => {
        setRoutes(r)
        setHealth(h)
        if (r.length) setSelected(r[0].id)
      })
      .catch((e) => setError(e.message))
  }, [])

  return (
    <div className="app">
      <header>
        <h1>Ambient Ops</h1>
        <p className="tagline">Heat-aware route prioritisation for urban planners</p>
      </header>

      {error && <div className="error">Backend unreachable: {error}</div>}

      {health?.missing_keys?.length > 0 && (
        <div className="warn">
          Unconfigured: {health.missing_keys.join(', ')}
        </div>
      )}

      <div className="controls">
        <label htmlFor="route">Route</label>
        <select
          id="route"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
        >
          {routes.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
              {r.status === 'placeholder' ? ' (placeholder)' : ''}
            </option>
          ))}
        </select>
      </div>

      <main className="layout">
        <Map routeId={selected} />
        <aside>
          <WeightSliders />
          <SegmentPanel routeId={selected} />
          <AgentTrace />
        </aside>
      </main>
    </div>
  )
}
