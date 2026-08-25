import { useEffect, useMemo, useState } from 'react'
import {
  CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap,
} from 'react-leaflet'
import { BIN_EDGES, hpsBin, readRamp, readVar } from '../hps.js'

/** Refit whenever the rendered route changes. */
function FitBounds({ bounds }) {
  const map = useMap()
  useEffect(() => {
    if (bounds?.length) map.fitBounds(bounds, { padding: [40, 40] })
  }, [bounds, map])
  return null
}

function Legend({ ramp }) {
  return (
    <div className="legend">
      <div className="title">Heat Priority Score</div>
      <div className="ramp">
        {ramp.map((c, i) => <i key={i} style={{ background: c }} />)}
      </div>
      <div className="ends">
        <span>0</span>
        <span>{BIN_EDGES.join('  ')}</span>
        <span>100</span>
      </div>
    </div>
  )
}

export default function Map({ result, selectedId, onSelect }) {
  // Leaflet strokes SVG paths directly, so it needs resolved hex, not
  // var(--hps-n). Re-read whenever the theme changes.
  const [ramp, setRamp] = useState(readRamp)
  const [casing, setCasing] = useState(() => readVar('--casing', '#fff'))
  const [accent, setAccent] = useState(() => readVar('--accent', '#2a78d6'))

  useEffect(() => {
    const refresh = () => {
      setRamp(readRamp())
      setCasing(readVar('--casing', '#fff'))
      setAccent(readVar('--accent', '#2a78d6'))
    }
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', refresh)
    const obs = new MutationObserver(refresh)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { mq.removeEventListener('change', refresh); obs.disconnect() }
  }, [])

  const segments = result?.segments || []
  const coords = result?.route?.coordinates || []

  const bounds = useMemo(() => coords.map(([lon, lat]) => [lat, lon]), [coords])
  const center = bounds.length
    ? bounds[Math.floor(bounds.length / 2)]
    : [36.7378, -119.7871] // Fresno

  if (!segments.length) {
    return (
      <div className="map-wrap">
        <MapContainer center={center} zoom={13} scrollWheelZoom>
          <TileLayer
            attribution='&copy; OpenStreetMap contributors'
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
        </MapContainer>
      </div>
    )
  }

  return (
    <div className="map-wrap">
      <MapContainer center={center} zoom={16} scrollWheelZoom>
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds bounds={bounds} />

        {/* Casing first: a wider stroke in the surface colour under every
            segment, so the ramp keeps its separation over any map tile. */}
        {segments.map((s) => (
          <Polyline
            key={`casing-${s.id}`}
            positions={[[s.start.lat, s.start.lon], [s.end.lat, s.end.lon]]}
            pathOptions={{ color: casing, weight: 13, opacity: 0.95, lineCap: 'butt' }}
            interactive={false}
          />
        ))}

        {segments.map((s) => {
          const selected = s.id === selectedId
          return (
            <Polyline
              key={s.id}
              positions={[[s.start.lat, s.start.lon], [s.end.lat, s.end.lon]]}
              pathOptions={{
                color: selected ? accent : ramp[hpsBin(s.HPS)],
                weight: selected ? 11 : 9,
                opacity: 1,
                lineCap: 'butt',
              }}
              eventHandlers={{ click: () => onSelect?.(s.id) }}
            >
              <Tooltip sticky>
                <strong>#{s.rank}</strong> · HPS {s.HPS?.toFixed(1)}
                <br />
                HEI {s.HEI?.toFixed(2)} · DTF {s.DTF?.toFixed(2)} ·
                {' '}SVI {s.SVI?.toFixed(2)} · PSI {s.PSI?.toFixed(2)}
              </Tooltip>
            </Polyline>
          )
        })}

        {coords.length > 0 && (
          <>
            <CircleMarker
              center={[coords[0][1], coords[0][0]]}
              radius={7}
              pathOptions={{ color: casing, weight: 3, fillColor: accent, fillOpacity: 1 }}
            >
              <Tooltip>Start · {result.route.origin_name}</Tooltip>
            </CircleMarker>
            <CircleMarker
              center={[coords[coords.length - 1][1], coords[coords.length - 1][0]]}
              radius={7}
              pathOptions={{ color: casing, weight: 3, fillColor: accent, fillOpacity: 1 }}
            >
              <Tooltip>Destination · {result.route.destination_name}</Tooltip>
            </CircleMarker>
          </>
        )}
      </MapContainer>
      <Legend ramp={ramp} />
    </div>
  )
}
