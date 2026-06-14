# Example dashboard

Three-view Lovelace layout for HAWahooligan. Built-in card types
only — `iframe`, `entities`, `markdown`, `heading`, `button`. No
HACS frontend cards required.

| View | Content |
|---|---|
| **Route** | Picker, Leaflet map, workout metadata, time & distance, power & body |
| **Lifetime** | Lifetime totals, streak, 7d/28d trailing windows, outdoor vs indoor table |
| **Profile** | FTP, critical power, the seven zone boundaries, "Edit zones" panel |

## Install

1. Settings → Dashboards → open the target dashboard → ⋮ →
   *Edit dashboard* → ⋮ → **Raw configuration editor**.
2. Paste [`dashboard.yaml`](./dashboard.yaml) (or append the
   `views:` entries to your existing list).

## Helpers (Profile view)

The Edit zones panel uses an `input_number` slider + a script.
Drop [`helpers.yaml`](./helpers.yaml) into the root of your
`configuration.yaml`, restart HA once. The slider drives a script
that calls `hawahooligan.set_power_zones` — Coggan-style zone
boundaries derive automatically.

For per-zone overrides or `workout_type_id`, extend the script's
`data:` block.

## Customizing

- **Entity IDs**: HA generates them from the slugified English
  friendly name (e.g. `sensor.hawahooligan_average_speed`). If you
  renamed any entity, swap the row.
- **Map height**: in a `sections` view, `aspect_ratio` is ignored.
  Use `grid_options.rows: 9` (≈ 500 px). The shipped YAML does.
- **`map.html`**: customise it directly under
  `<config>/www/hawahooligan/map.html`. Delete the
  `HAWahooligan-Viewer-Version: N` header line to prevent the
  integration overwriting your edits on the next restart.

## Sanity check

After the first poll, `<config>/www/hawahooligan/` contains
`map.html`, `workouts.json`, `latest.geojson`, and one
`<workout_id>.geojson` per outdoor ride. Visit
`http://<your-ha>/local/hawahooligan/map.html` directly to verify
the viewer renders standalone.
