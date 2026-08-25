/* Shared scale helpers.
 *
 * The HPS ramp is a sequential encoding — one hue, light to dark, five
 * discrete steps rather than a continuous gradient. Discrete because a
 * planner reads a map by comparing segments to each other and to a legend,
 * which a continuous gradient makes harder, not easier.
 *
 * Bins are fixed on the 0-100 HPS scale, not on the route's own min and max.
 * Binning per-route would repaint identical scores differently on different
 * routes and make the legend a lie.
 */

export const HPS_STEPS = 5;

export const BIN_EDGES = [20, 35, 50, 65]; // 5 bins: <20, <35, <50, <65, >=65

export function hpsBin(hps) {
  if (hps == null || Number.isNaN(hps)) return 0;
  let i = 0;
  while (i < BIN_EDGES.length && hps >= BIN_EDGES[i]) i += 1;
  return i; // 0..4
}

/** CSS custom property for a score. Resolved by the theme, so it follows
 *  light/dark without the component knowing which is active. */
export function hpsVar(hps) {
  return `var(--hps-${hpsBin(hps) + 1})`;
}

/** Read the ramp's real hex values — Leaflet paints to canvas/SVG and cannot
 *  resolve a CSS variable in a path's stroke. */
export function readRamp() {
  const s = getComputedStyle(document.documentElement);
  return Array.from({ length: HPS_STEPS }, (_, i) =>
    s.getPropertyValue(`--hps-${i + 1}`).trim() || "#d1601f",
  );
}

export function readVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export const FACTOR_LABELS = {
  HEI: "Heat Exposure",
  DTF: "Dwell Time",
  SVI: "Surface Vulnerability",
  PSI: "Population Sensitivity",
};
