# Example dashboard

A minimal Lovelace view that pairs the HAWahooligan summary sensors with a
Leaflet viewer rendering the GPS track of the most recent workout.

## What ships where

The integration writes two kinds of artifact under `<config>/www/hawahooligan/`
(served at `/local/hawahooligan/`):

| File | Provisioned by | Lifecycle |
|------|----------------|-----------|
| `map.html` | `async_setup_entry` on every HA restart | Auto-updates when the packaged version is bumped — see "Pinning your copy" below |
| `<workout_id>.geojson` | Coordinator, on a new outdoor (non-manual) workout | One per ride |
| `latest.geojson` | Coordinator, every time a new outdoor workout arrives | Rolling pointer |

`map.html` reads the `id` query parameter; without it, it loads `latest.geojson`.

## Dependencies

None beyond the integration itself. The example uses the built-in
`iframe` and `entities` cards. No HACS frontend cards required.

## Wiring it up

1. Install HAWahooligan via HACS (custom repository) and complete the OAuth
   flow. The first start writes `<config>/www/hawahooligan/map.html`.
2. Settings → Dashboards → Open the dashboard you want to extend → ⋮ → "Edit
   dashboard" → "Raw configuration editor".
3. Append the contents of [`dashboard.yaml`](./dashboard.yaml) to the `views:`
   list, or save it as its own dashboard.
4. Check the sensor IDs against your actual entities (Settings → Devices &
   Services → HAWahooligan → entities) and adjust the example if you renamed
   the device.

## Viewing a specific workout

Use the `id` query parameter in the iframe URL:

```yaml
- type: iframe
  url: /local/hawahooligan/map.html?id=123456
  aspect_ratio: 75%
```

The id matches the Wahoo `workout_id` exposed as an attribute on
`sensor.hawahooligan_last_workout`.

## Pinning your copy of `map.html`

The integration re-installs the packaged viewer whenever the version in the
file header is higher than what's on disk. To keep your customizations:

1. Edit `<config>/www/hawahooligan/map.html`.
2. Delete the `HAWahooligan-Viewer-Version: N` line in the header comment.

Without the version stamp, the integration leaves the file alone on every
subsequent restart.

## Verifying the artifacts

After your first outdoor ride syncs to Wahoo Cloud and HAWahooligan polls it
(≤ 15 min), you should see:

```text
<config>/www/hawahooligan/
├── map.html
├── latest.geojson
└── <workout_id>.geojson
```

Browse to `http://<your-ha>/local/hawahooligan/map.html` directly — the same
page the iframe loads — to confirm the track renders standalone.
