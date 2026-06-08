# HAWahooligan

[![Tests](https://github.com/mrebbert/hawahooligan/actions/workflows/test.yml/badge.svg)](https://github.com/mrebbert/hawahooligan/actions/workflows/test.yml)
[![Validate](https://github.com/mrebbert/hawahooligan/actions/workflows/validate.yml/badge.svg)](https://github.com/mrebbert/hawahooligan/actions/workflows/validate.yml)
[![GitHub release](https://img.shields.io/github/v/release/mrebbert/hawahooligan)](https://github.com/mrebbert/hawahooligan/releases/latest)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![License](https://img.shields.io/github/license/mrebbert/hawahooligan)](LICENSE)

**Your Wahoo rides as native Home Assistant entities — with the GPS track on a map you can drop into any dashboard.**

HAWahooligan polls the [Wahoo Cloud API](https://cloud-api.wahooligan.com/),
exposes the most recent ride's summary as sensors (distance, duration,
power, heart rate, TSS, …), renders the FIT file as a GeoJSON track, and
ships a bundled Leaflet viewer so the map appears in Lovelace via a plain
iframe card. No extra HACS frontend cards required.

---

## At a glance

```text
┌──────────────────────────┐   ┌──────────────────────────────┐
│   /local/hawahooligan/   │   │  sensor.hawahooligan_*       │
│   map.html (Leaflet)     │   │  • last_workout (timestamp)  │
│   ▶ picker dropdown      │   │  • distance, ascent          │
│   ▶ start / end markers  │   │  • duration / total / paused │
│   ▶ ?id=N deep-link      │   │  • avg power / NP / TSS      │
│   ▶ updates sensors      │   │  • avg HR / cadence / speed  │
│     via select_workout   │   │  • calories, work            │
└──────────────────────────┘   │  + 7 attributes incl.        │
                                │    route_id / plan_id        │
                                └──────────────────────────────┘
```

Picking a tour in the viewer dropdown re-renders the map **and** flips
every sensor to the chosen ride — no card drift.

---

## Quick start

### 1. Install via HACS

* HACS → Integrations → ⋮ → **Custom repositories**.
* Add `https://github.com/mrebbert/hawahooligan` as type **Integration**.
* Install **HAWahooligan**, then restart Home Assistant.

### 2. Create a Wahoo developer app

You need your own Wahoo OAuth credentials — the integration deliberately
does not ship a shared client secret.

* Go to <https://cloud-api.wahooligan.com/> → **My Apps** → create one:
  * **Type:** Confidential
  * **Redirect URI:** `https://my.home-assistant.io/redirect/oauth`
  * **Environment:** Sandbox is enough for personal use (Sandbox 25/5min, 100/h, 250/day — comfortable for 1 call per 15 min poll).
* Note the **client_id** and **client_secret**.

### 3. Wire it up in HA

* Settings → Devices & Services → **Add Integration** → search for *HAWahooligan*.
* Paste the **client_id** / **client_secret** into the Application Credentials dialog.
* Complete the OAuth round-trip (your browser → Wahoo → `my.home-assistant.io` → your HA). Works on your local network — no public DNS / TLS required.

After the first poll completes (≤ 15 min after a sync from your bike
computer), the integration backfills GeoJSONs for the last 20 outdoor
rides in the background. The map and the picker dropdown go live as soon
as the first one lands.

---

## What you get

### Sensors

A single device **HAWahooligan** with:

| Sensor (entity_id suffix) | Unit | Source |
|---|---|---|
| `_last_workout` | timestamp | `workout.starts` |
| `_distance` | km | `summary.distance_accum` |
| `_ascent` | m | `summary.ascent_accum` |
| `_duration` | min | `summary.duration_active_accum` |
| `_total_duration` | min | `summary.duration_total_accum` |
| `_paused_duration` | min | `summary.duration_paused_accum` |
| `_average_speed` | km/h | `summary.speed_avg` |
| `_average_power` | W | `summary.power_avg` |
| `_normalized_power` | W | `summary.power_bike_np_last` |
| `_training_stress_score` | – | `summary.power_bike_tss_last` |
| `_average_heart_rate` | bpm | `summary.heart_rate_avg` |
| `_average_cadence` | rpm | `summary.cadence_avg` |
| `_calories` | kcal | `summary.calories_accum` |
| `_work` | kJ | `summary.work_accum` |

> **Note:** HA derives entity_ids from the slugified English name, not
> the integration's translation_key. So `sensor.hawahooligan_average_speed`
> (not `..._speed_avg`). The dashboard YAML in this repo already uses the
> correct ids; a CI test guards against drift.

### Attributes on `sensor.hawahooligan_last_workout`

`workout_id`, `name`, `workout_type_id`, `workout_type`, `indoor`,
`manual`, `edited`, `time_zone`, `fitness_app_id`, `starts`,
`geojson_url`, **`route_id`**, **`plan_id`**, **`plan_ids`**,
**`recent`** (rolling list of the last 20 rides for templating),
**`selected_workout_id`** (set when you've pinned a specific ride).

### Map viewer

Auto-provisioned at `/local/hawahooligan/map.html`. Embed it via a
Lovelace iframe card.

| What | How |
|---|---|
| Default view | Renders `latest.geojson` (the most recent outdoor ride). |
| Deep link | Append `?id=<workout_id>`, e.g. `/local/hawahooligan/map.html?id=12345`. |
| Browse history | The dropdown in the top-right lists the last 20 rides. Picking one re-renders the map AND updates the headline sensors. |
| Indoor rides | Listed in the dropdown but disabled with `(no GPS)`. |

### Services

| Service | What it does |
|---|---|
| `hawahooligan.select_workout` | Pin the integration to a workout id (or pass `"latest"` to release the pin). Sensors and map both follow. The viewer dropdown calls this automatically. |
| `hawahooligan.render_workout` | Render the GeoJSON for an arbitrary workout id — useful for rides older than the 20-ride backfill window. |

---

## The example dashboard

[`dashboard/dashboard.yaml`](./dashboard/dashboard.yaml) is a ready-to-paste
Lovelace view with four sections — map, tour metadata, time & distance,
power & body metrics. See [`dashboard/README.md`](./dashboard/README.md) for
the walkthrough and customization tips.

To install: open your dashboard → ⋮ → *Edit dashboard* → ⋮ →
*Raw configuration editor* → paste the file's `views:` block.

---

## Troubleshooting

**Sensor cards show "unavailable"**
HA derives entity_ids from the *translated friendly name*, not the
translation_key. If your dashboard is from an older release of this
repo, the ids in the example were wrong. Re-paste
[`dashboard/dashboard.yaml`](./dashboard/dashboard.yaml) from `main` /
the latest release.

**The map is a thin strip at the top of its card**
In a `sections`-view, HA's iframe card ignores `aspect_ratio` — set
`grid_options.rows: 9` (≈ 500 px) explicitly. The example YAML already
does this.

**Dropdown updates the map but not the sensors**
The viewer reads your HA auth token from
`localStorage.hassTokens`. If you opened the map.html standalone in a
browser tab without signing in to HA first, the service call from the
dropdown can't authenticate. Open the dashboard from inside the HA
frontend.

**Map shows last week's ride after I updated the integration**
Browser cache on the iframe. Hard-refresh: `Cmd+Shift+R` (macOS),
`Ctrl+Shift+F5` (Win/Linux).

**Wahoo says "token revoked"**
Wahoo expires unused refresh tokens after 60 days. HA pops up a "Reauth"
notification automatically — click *Configure*, walk through OAuth
again, and the same config entry continues with all its long-term
statistics intact.

**Sandbox rate limits**
At 15 min polling the integration uses ~1 call per poll (~96/day). The
first-setup backfill uses up to N+1 calls in the 5 min window after
adding the integration. All comfortably under the Wahoo Sandbox limits
(25 / 5 min, 100 / h, 250 / day).

---

## Roadmap

| Phase | Scope | State |
|---|---|---|
| 1 | OAuth + polling sensors | shipped |
| 2 | FIT → GeoJSON track | shipped |
| 3 | Bundled Leaflet viewer + dashboard | shipped |
| 3+ | Picker UI + selection-driven sensors + backfill | shipped |
| 4 | Analytics (`utility_meter` for monthly km, FTP / power-zones sensor) | optional |
| 5 | Write endpoints — push routes & plans to ELEMNT | optional |

The full implementation plan lives at `.claude/tasks/wahoo_ha_custom_integration_plan.md`.

---

## Development

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e ".[test-integration]"
.venv/bin/pytest tests -v
```

Tier-1 (`tests/test_fit.py`) covers the pure FIT → GeoJSON conversion via
`importlib`, no HA dependency. Tier-2 (`tests/integration/`) loads a real
HA stack via `pytest-homeassistant-custom-component` — that's where the
dashboard entity_id regression test lives.

The integration follows the standard Home Assistant custom-component
layout. Notable files:

```text
custom_components/hawahooligan/
├── __init__.py             # setup / unload / remove + viewer provisioning
├── api.py                  # async Wahoo client (with FIT-download fallback)
├── application_credentials.py
├── config_flow.py          # OAuth2 + reauth
├── const.py
├── coordinator.py          # poll → recent list → selection-aware data
├── fit.py                  # FIT → GeoJSON (no HA imports — Tier-1 testable)
├── manifest.json
├── sensor.py
├── services.py             # render_workout, select_workout
├── services.yaml
├── strings.json
├── translations/en.json
└── web/map.html            # Leaflet viewer with picker
```

---

## License

[MIT](./LICENSE).
