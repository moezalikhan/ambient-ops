# Project state

Written 27 Aug 2026. Submission due 30 Aug. Everything in the 8-step build plan
is done, tested, and verified offline. What remains is other people's work.

---

## Where things are

**Repo:** https://github.com/moezalikhan/ambient-ops — public, sole contributor
`moezalikhan`. Collaborator invites sent to `Mindyii` and `ameera-13`
(7-day expiry from 25 Aug).

**Run it:** `uvicorn backend.main:app --port 8000` → http://localhost:8000.
One service, whole app. `npm run build` in `frontend/` first if `dist` is
missing. Full runbook in [DEMO.md](DEMO.md).

**Keys:** three, all free tiers — `FORTYGUARD_API_KEY`, `ORS_API_KEY`,
`GROQ_API_KEY`. Scoring and every script work with none of them, because the
cache is committed.

**Credits:** ~1.36M of 2M FortyGuard remaining, resetting 25 Sep. Heat grid is
~4,220 per route; satellite land cover is ~14,400 **per segment**, which is
why arbitrary user routes are not viable (~249k and 20+ minutes each).

**Tests:** 127, no network needed. `pytest backend/tests -q`,
`ruff check backend scripts`.

---

## Decisions that are settled

| Decision | Why |
|---|---|
| **Fresno, California** | FortyGuard coverage is US-only — Abu Dhabi returns zero tiles on every layer |
| **`exceedance` layer, 35 °C, 30-day window** | At any single hour a defensible threshold is exceeded by every tile, flattening HEI. 30 days turns 0.18 °C into 10.5 hours of accumulated exposure |
| **SVI from satellite imagery, not OSM** | OSM has 0 trees and no surface tags on both routes; imagery gives 0–15.3% canopy that varies per segment |
| **Groq `openai/gpt-oss-120b`** | Free, tool-calling verified. Fallback `qwen/qwen3.6-27b`. `groq/compound*` does **not** support tools |
| **Two fixed routes** | Spec §3 excludes arbitrary routes; the satellite cost above makes them impractical anyway |
| **PDF report is the primary output** | Trace moved out of the interface into the report at the team lead's direction |

---

## Findings that shaped the build

**Heat varies at neighbourhood scale, not street scale.** Across 4 km² the
spread is 22.2 hours; across an 800 m route it is 0.63, and on route B
**exactly zero on all 87 tiles**. HEI separates routes, not segments within a
route. A constant factor is detected, neutralised to 0.5, flagged in the API,
greyed in the interface, and stated by the agent in its brief.

**Three of four factors were originally constant.** DTF was redefined as the
continuous unshaded run rather than segment length (segments are equal by
construction, so the literal formula ranked nothing). SVI moved to imagery.
Only PSI varied without those changes.

**The route A ranking is fragile, and the report says so.** Top two segments
differ by **0.18 HPS**; the leader changes under 4 of 8 weight perturbations.
The honest output is a top group, not a single winner. Lead with this — it is
the strongest thing in the submission.

**No cooling figure exists anywhere.** Every `cooling_estimate` is `null`, the
agent is forbidden from stating one, and a test fails if a number is added
without a citation beside it. Simulated magnitudes are labelled assumptions.

---

## Open items — not code

1. **Ameera:** cooling estimates + sources for 6 intervention rows, §10
   references, the 1.3 m/s walking-speed citation. This is the critical path.
2. **Minqi:** METHODOLOGY appears to have **two `### 5.1` headings** after the
   last push. Also §5.1 argues HEI's 0.40 weight needs revisiting since it
   cannot separate segments within a route — their call.
3. **Submission requirements** — confirm whether a live deployed URL is
   required. If not, hosting is added risk; the repo link plus the fallback
   video is enough.
4. **Fallback video** — spec §13. Not yet recorded.

---

## Traps worth remembering

- **Restart uvicorn after any backend edit.** It runs without `--reload`; a
  stale process silently serves the old handler. This already cost one
  debugging round.
- **Use `localhost`, not `127.0.0.1`, for the Vite dev server** — it binds IPv6
  only. The API is fine on either.
- **Overpass returns 406 without a User-Agent**, from Apache, before the query
  is parsed — so the error looks nothing like a query problem.
- **Way centroids are wrong for linear features.** Measuring to a road's centre
  found zero asphalt on a route that is entirely asphalt; use geometry.
- **`tcm` tiles list `tile_id` before `average_temperature`.** Reading "the
  first numeric property" scores the grid on tile indices and looks healthy.

---

## Optional, if time allows

- A one-line live trace strip in the interface. Spec §3 lists a visible
  tool-call trace as an MVP feature and §4 calls it the reason this belongs in
  Track 06; it now lives only in the PDF. Roughly ten minutes.
- A second pre-cached city (Bakersfield or San Bernardino are both covered) for
  the generalisation story — ~250k credits per route.
