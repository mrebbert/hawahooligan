# Example dashboard

Drop-in three-view Lovelace layout that pairs the bundled HAWahooligan
Leaflet viewer with the workout sensors, lifetime totals, trailing-window
sensors, and the FTP / power-zones profile — grouped into focused tabs
so no single page becomes a wall of metrics.

For HACS install + OAuth setup see the [project README](../README.md).
This page focuses on the dashboard itself.

## Three views

| View | What's on it | Driven by |
|---|---|---|
| **Route** | workout picker, Leaflet map, workout metadata, time & distance, power & body | the active picker selection + the per-workout detail cache |
| **Lifetime** | lifetime totals, recent-activity trailing windows (7d / 28d), outdoor vs indoor markdown table | the lifetime totals store + the rolling-window sensors (0.7.20+) |
| **Profile** | FTP, critical power, the seven power-zone boundaries, "edit zones" note | the power-zones coordinator (polls daily; manual refresh via `hawahooligan.refresh_power_zones`) |

## Wiring it up

1. Make sure the integration is set up and at least one workout has
   synced (the picker hides itself until there's something renderable).
2. Settings → Dashboards → open the target dashboard → ⋮ → *Edit dashboard*
   → ⋮ → **Raw configuration editor**.
3. Paste the contents of [`dashboard.yaml`](./dashboard.yaml) (or append the
   inner `views:` entries to your existing `views:` list).

The example uses only built-in card types — `iframe`, `entities`,
`markdown`, `heading`. No HACS frontend cards required.

## Static files the integration writes

The coordinator drops these under `<config>/www/hawahooligan/`
(HA serves them at `/local/hawahooligan/`):

| File | Provisioned by | Lifecycle |
|------|----------------|-----------|
| `map.html` | `async_setup_entry` on every restart | Auto-updates when the packaged viewer version stamp bumps — pinning instructions below |
| `<workout_id>.geojson` | Coordinator, once per outdoor ride | One per ride |
| `latest.geojson` | Coordinator, every time a new outdoor ride arrives | Rolling pointer |
| `workouts.json` | Coordinator, every poll | Manifest of the last 20 rides — drives the picker dropdown |

## Picker behaviour

The dropdown is built from `workouts.json`. Picking an entry:

1. Calls `hawahooligan.select_workout` against the HA REST API with the
   chosen id (auth token read from `localStorage.hassTokens`).
2. Re-fetches the geojson and re-renders the map immediately — doesn't
   wait for the service to round-trip.
3. The coordinator picks up the selection and refreshes within ~1–2 s, so
   the sensor cards in the Route view also flip to the chosen ride.

Selection lives in memory only — it resets to "Latest workout" on HA
restart. To pin permanently, use `?id=<workout_id>` in the iframe URL.

## Customizing entity ids

HA generates entity_ids by slugifying the **translated friendly name**
(English), not from the integration's `translation_key`. The example
references the actually-registered names — *e.g.*
`sensor.hawahooligan_average_speed` rather than `..._speed_avg`.

If you renamed any entity in Settings → Entities, swap the matching row.
Find the canonical ids in Settings → Devices & Services → HAWahooligan
→ Entities.

## `grid_options.rows` instead of `aspect_ratio`

In a `sections` view the iframe card ignores `aspect_ratio` —
[HA's iframe card](https://github.com/home-assistant/frontend/blob/master/src/panels/lovelace/cards/hui-iframe-card.ts)
treats the grid layout as authoritative. Use:

```yaml
- type: iframe
  url: /local/hawahooligan/map.html
  grid_options:
    columns: 12
    rows: 9          # ≈ 500 px; each row is ~56 px
```

For non-sections views (`type: panel`, classic `type: cards`) the legacy
`aspect_ratio: '75%'` still works.

## Pinning your `map.html`

Want to customize the viewer (theme, markers, status bar)?

1. Edit `<config>/www/hawahooligan/map.html` directly.
2. Delete the `HAWahooligan-Viewer-Version: N` line in the header
   comment.

Without the version stamp the integration leaves the file alone on every
subsequent restart. To get back on the bundled viewer, restore the
version line.

## Editing FTP / power zones

The Profile view's "Edit zones" panel shows a slider for your target
FTP and a button that pushes the value to Wahoo via the
`hawahooligan.set_power_zones` service. Stock Lovelace can't collect
free-form numbers in a card, so this needs two one-time helpers in
your `configuration.yaml`.

Copy the contents of [`helpers.yaml`](./helpers.yaml) — one
`input_number` slider and one script — to the root of your
`configuration.yaml`, then restart HA once. The slider on the dashboard
then drives the helper, and clicking the button runs the script — which
derives the seven zone boundaries from your FTP automatically using
Wahoo-style defaults (55% / 70% / 91% / 96% / 103% / 120% / 500%
sentinel), matching what the Wahoo app produces from the same FTP
value. The FTP / Critical Power sensors above refresh immediately
afterwards.

To override individual zones (e.g. pin Zone 4 to a tested LT value)
or change `workout_type_id`, extend the script's `data:` block — the
service accepts `critical_power`, `zone_1` … `zone_7`, and
`workout_type_id` as optional fields. See the README's "Setting your
FTP from HA" section for the full schema.

Shipped in 0.7.26 — pre-0.7.26 the only options were Postman or the
Wahoo Companion App (whose cloud sync proved unreliable in testing).

## Verifying the wiring

After the first poll, you should see:

```text
<config>/www/hawahooligan/
├── map.html
├── workouts.json
├── latest.geojson
└── <workout_id>.geojson
```

Standalone check: visit `http://<your-ha>/local/hawahooligan/map.html`
directly in a browser tab. The page should render the latest track
without the surrounding dashboard.
