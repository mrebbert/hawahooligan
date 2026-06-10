# HAWahooligan

[![Tests](https://github.com/mrebbert/hawahooligan/actions/workflows/test.yml/badge.svg)](https://github.com/mrebbert/hawahooligan/actions/workflows/test.yml)
[![Validate](https://github.com/mrebbert/hawahooligan/actions/workflows/validate.yml/badge.svg)](https://github.com/mrebbert/hawahooligan/actions/workflows/validate.yml)
[![GitHub release](https://img.shields.io/github/v/release/mrebbert/hawahooligan)](https://github.com/mrebbert/hawahooligan/releases/latest)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/github/license/mrebbert/hawahooligan)](LICENSE)

> **Your Wahoo rides as native Home Assistant entities — with the GPS track on a map you can drop into any dashboard.**

HAWahooligan polls the [Wahoo Cloud API](https://cloud-api.wahooligan.com/),
exposes the most recent ride's summary as sensors (distance, duration,
power, heart rate, TSS, …), renders the FIT file as a GeoJSON track, and
ships a bundled Leaflet viewer so the map appears in Lovelace via a plain
iframe card. No extra HACS frontend cards required.

<p>
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=mrebbert&repository=hawahooligan&category=integration">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open HACS and add this repository as a custom repository." />
  </a>
  &nbsp;
  <a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=hawahooligan">
    <img src="https://my.home-assistant.io/badges/config_flow_start.svg" alt="Open your Home Assistant instance and add the HAWahooligan integration." />
  </a>
</p>

---

## Table of contents

- [What it looks like](#what-it-looks-like)
- [Quick start](#quick-start)
- [Sensors and attributes](#sensors-and-attributes)
- [Map viewer](#map-viewer)
- [Services](#services)
- [Dashboard example](#dashboard-example)
- [Troubleshooting / FAQ](#troubleshooting--faq)
- [Advanced: lifetime totals + utility_meter](#advanced-lifetime-totals--utility_meter)
- [Roadmap](#roadmap)
- [Development](#development)
- [License](#license)

---

## What it looks like

```text
┌──────────────────────────┐   ┌──────────────────────────────┐
│   /local/hawahooligan/   │   │  sensor.hawahooligan_*       │
│   map.html (Leaflet)     │   │  • last_workout (timestamp)  │
│   ▶ picker dropdown      │   │  • distance, ascent          │
│   ▶ start / end markers  │   │  • duration / total / paused │
│   ▶ ?id=N deep-link      │   │  • avg power / NP / TSS      │
│   ▶ updates sensors      │   │  • avg HR / cadence / speed  │
│     via select_workout   │   │  • calories, work            │
└──────────────────────────┘   │  • lifetime_* (utility_meter │
                                │      compatible)            │
                                │  • ftp, critical_power      │
                                └──────────────────────────────┘
```

Picking a tour in the viewer dropdown re-renders the map **and** flips
every sensor to the chosen ride — no card drift.

---

## Quick start

### Step 1 — Install via HACS

The fastest path is the **Open HACS** button in the header. It opens HACS
on your Home Assistant instance with the repository pre-filled. Click
**Download** → restart Home Assistant.

[![Open HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mrebbert&repository=hawahooligan&category=integration)

The manual path:

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add `https://github.com/mrebbert/hawahooligan` as type **Integration**
3. Download **HAWahooligan** and restart Home Assistant

> The bundled Leaflet viewer means **no extra HACS frontend cards** are
> required — the map drops straight into a built-in iframe card.

### Step 2 — Create a Wahoo developer app

You need your own Wahoo OAuth credentials — the integration deliberately
does not ship a shared client secret.

1. Go to <https://cloud-api.wahooligan.com/> → **My Apps** → **+ Add a new app**
2. Fill in:
   - **Type:** `Confidential`
   - **Redirect URI:** `https://my.home-assistant.io/redirect/oauth`
   - **Scopes:** `user_read workouts_read power_zones_read offline_data`
   - **Environment:** Sandbox is enough for personal use (25 / 5 min, 100 / h, **250 / day**). If you plan to use the full-history backfill on a big history, request Production (200 / 5 min, 1000 / h, 5000 / day) via Wahoo's review process.
3. Save and note the **client_id** and **client_secret**.

### Step 3 — Add the integration in Home Assistant

[![Add HAWahooligan integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hawahooligan)

The manual path:

1. **Settings → Devices & Services → Add Integration → HAWahooligan**
2. Paste the **client_id** / **client_secret** into the Application
   Credentials dialog (Home Assistant prompts you the first time).
3. Complete the OAuth round-trip (browser → Wahoo → `my.home-assistant.io` → your HA).

Works on your local network — no public DNS / TLS required. Home
Assistant takes care of token refresh and rotates the refresh token
on every refresh.

> The first sync triggers a background backfill of your **last 20
> outdoor rides** under a sandbox-safe rate-limit budget. The map and
> the picker go live as soon as the first geojson lands.

---

## Sensors and attributes

A single device **HAWahooligan** with 23 sensors. Entity ids follow the
slugified English friendly name (HA's default), so e.g.
`sensor.hawahooligan_average_speed`, not `..._speed_avg`.

### Per-workout (drives the headline / picker)

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

### Lifetime totals (`state_class=total_increasing`, utility_meter-ready)

| Sensor | Unit | Attributes |
|---|---|---|
| `_lifetime_workouts` | count | `outdoor`, `indoor` |
| `_lifetime_distance` | km | `outdoor`, `indoor` |
| `_lifetime_ascent` | m | `outdoor`, `indoor` |
| `_lifetime_duration` | min | `outdoor`, `indoor` |
| `_lifetime_calories` | kcal | `outdoor`, `indoor` |
| `_lifetime_work` | kJ | `outdoor`, `indoor` |
| `_lifetime_tss` | – | `outdoor`, `indoor` |

### Athlete profile (refreshes once a day)

| Sensor | Unit | Attributes |
|---|---|---|
| `_ftp` | W | `zone_1` … `zone_7`, `zone_count`, `workout_type_id`, `workout_type_family_id`, `updated_at` |
| `_critical_power` | W | – |

### Attributes on `sensor.hawahooligan_last_workout`

`workout_id`, `name`, `workout_type_id`, `workout_type`, `indoor`,
`manual`, `edited`, `time_zone`, `fitness_app_id`, `starts`,
`geojson_url`, **`route_id`**, **`plan_id`**, **`plan_ids`**,
**`recent`** (rolling list of the last 20 rides for templating),
**`selected_workout_id`** (set when you've pinned a specific ride via
the picker or service).

---

## Map viewer

Auto-provisioned at `/local/hawahooligan/map.html`. Embed it via a
Lovelace iframe card.

| What | How |
|---|---|
| Default view | Renders `latest.geojson` (the most recent outdoor ride). |
| Deep link | Append `?id=<workout_id>`, e.g. `/local/hawahooligan/map.html?id=12345`. |
| Browse history | The `select.hawahooligan_workout_picker` dropdown (shipped as a card right above the iframe) lists every workout the integration has ever seen — regular polls add the last 20, `full_backfill` adds everything else. Picking one drives the headline sensors AND the iframe in one go. |
| Indoor / manual rides | Pickable like any other workout. Sensors update; the iframe shows a friendly "no GPS track" overlay instead of an empty map. |
| Stay in sync | `cleanup_geojson` removes manifest entries for any tracks it deletes, so the dropdown reflects what's actually on disk. Indoor / manual rows (no track to time-check) are untouched. |

> The integration writes `<config>/www/hawahooligan/map.html` once per
> setup. Customize it by editing the file directly **and** deleting the
> `HAWahooligan-Viewer-Version: N` comment in the header — the
> integration only auto-updates files that still carry the version
> stamp.

---

## Services

| Service | What it does |
|---|---|
| `hawahooligan.select_workout` | Pin the integration to a workout id (or pass `"latest"` to release the pin). Sensors and map both follow. The viewer dropdown calls this automatically. |
| `hawahooligan.render_workout` | Render the GeoJSON for an arbitrary workout id — useful for rides older than the 20-ride backfill window. |
| `hawahooligan.full_backfill` | Paginate through the user's entire Wahoo history and feed the lifetime totals. Rate-limit aware (sandbox-safe defaults of 20 calls / 300 s). Fires `hawahooligan_full_backfill_progress` events per page so you can wire a notification. |
| `hawahooligan.cleanup_geojson` | Prune cached GeoJSON track files in `<config>/www/hawahooligan/` older than `max_age_days` (default 180). Wire to a nightly automation to cap unbounded growth from backfills + `render_workout` calls. |

---

## Dashboard example

[`dashboard/dashboard.yaml`](./dashboard/dashboard.yaml) is a ready-to-paste
Lovelace view with **seven sections**:

1. Map — Leaflet iframe with the picker.
2. Workout — last_workout state + key attributes (name, type, indoor, route/plan ids, selection).
3. Time & distance — durations, distance, ascent, average speed, calories.
4. Power & body — power_avg, normalized power, TSS, work, average heart rate, average cadence.
5. Lifetime — utility_meter-ready totals (workouts, distance, ascent, duration, calories, work, TSS).
6. Outdoor vs indoor — a Markdown table that reads the `outdoor` / `indoor` attributes from every lifetime sensor. Row labels follow the user's HA locale automatically.
7. Profile — FTP and critical power. Zone thresholds are attributes on `_ftp`.

To install: open your dashboard → ⋮ → *Edit dashboard* → ⋮ →
*Raw configuration editor* → paste the file's `views:` block.

See [`dashboard/README.md`](./dashboard/README.md) for the walkthrough and
customization tips (including why the iframe needs `grid_options.rows`
instead of `aspect_ratio`).

---

## Troubleshooting / FAQ

<details>
<summary><strong>Sensor cards show "unavailable"</strong></summary>

Home Assistant derives entity ids from the *translated friendly name* of
the **active HA locale**, not from the integration's `translation_key`.
There are two common ways this drifts away from the documented YAML:

1. **Older release of this repo.** The example used the wrong ids
   (`_speed_avg` instead of `_average_speed`, …). Re-paste
   [`dashboard/dashboard.yaml`](./dashboard/dashboard.yaml) from the
   latest release.
2. **Non-English HA install that observed a sensor for the first time
   after `de.json` shipped (0.7.0+).** The German friendly name
   "Kritische Leistung" slugifies to
   `sensor.hawahooligan_kritische_leistung`, not
   `sensor.hawahooligan_critical_power`. As of 0.7.8 every sensor
   overrides `suggested_object_id` so new installs always get the
   English-style slug regardless of locale. (0.7.7 attempted this
   via `_attr_suggested_object_id`, but HA's entity platform does
   not read that attribute — the property override in 0.7.8 is the
   working fix.) Existing entries are pinned by the registry and
   don't auto-rename; fix them at
   **Settings → Devices & Services → HAWahooligan → click an entity →
   ⚙ → Entity ID** and set the documented form.

</details>

<details>
<summary><strong>The map is a thin strip at the top of its card</strong></summary>

In a `sections` view, HA's iframe card ignores `aspect_ratio`. Set
`grid_options.rows: 9` (≈ 500 px) explicitly. The example YAML already
does this.

</details>

<details>
<summary><strong>Dropdown updates the map but not the sensors</strong></summary>

The viewer reads your HA auth token from `localStorage.hassTokens` and
calls the `select_workout` service against `/api/services/...`. If you
opened the map.html standalone in a browser tab without signing in to
HA first, the service call can't authenticate. Open the dashboard from
inside the HA frontend.

</details>

<details>
<summary><strong>Map shows last week's ride after an update</strong></summary>

Browser cache on the iframe. Hard-refresh: `Cmd+Shift+R` (macOS),
`Ctrl+Shift+F5` (Win/Linux).

</details>

<details>
<summary><strong>"Reauthentication required" notification after upgrading</strong></summary>

0.7.0 added the `power_zones_read` OAuth scope. Existing tokens don't
carry it, so the first `GET /v1/power_zones` returns 403 and HA
schedules a reauth flow. Click *Configure* in the notification, walk
through the Wahoo OAuth flow once, and the new token has every scope.
Your config entry, entity history, and lifetime totals all survive.

</details>

<details>
<summary><strong>HTTP 429 — Too Many Requests</strong></summary>

Wahoo's Sandbox tier limits to 25 calls per 5 min, 100 per hour, **250
per day**. The integration uses a rolling-window budget on the
backfill and a 5-minute retry on the API client — but if you upgrade,
restart a few times, AND run the full-history backfill all on the
same day, you can blow through the daily cap. Wait until 00:00 UTC for
the daily reset, or upgrade your Wahoo Developer App to Production
(200 / 5 min, 1000 / h, 5000 / day) via the Wahoo Developer Portal.

</details>

<details>
<summary><strong>Wahoo says "token revoked"</strong></summary>

Wahoo expires unused refresh tokens after 60 days. HA pops up a "Reauth"
notification automatically — click *Configure*, walk through OAuth
again, and the same config entry continues with all its long-term
statistics intact.

</details>

<details>
<summary><strong>Lifetime totals reset to 0 after restart</strong></summary>

That bug was real in 0.6.0–0.6.x — `async_load_totals` was wired but
not called on startup. Fixed in 0.7.0. Update to a current release and
the persisted store at `.storage/hawahooligan_totals_<entry_id>.json`
is rehydrated on every restart.

</details>

---

## Advanced: lifetime totals + utility_meter

Each lifetime sensor carries `state_class=total_increasing`, so the HA
recorder keeps long-term statistics automatically. To get weekly /
monthly / yearly buckets:

1. **Settings → Devices & Services → Helpers → Create helper → Utility Meter**
2. Source: pick any `sensor.hawahooligan_lifetime_*`
3. Cycle: `daily`, `weekly`, `monthly`, `yearly` …

The result is `sensor.<your_helper>_monthly` with your monthly km / TSS
/ etc. — no Python, no YAML templates.

Indoor / outdoor breakdown lives on the same lifetime sensors as the
`outdoor` and `indoor` attributes. The example dashboard renders them as
a compact Markdown table that picks up your locale automatically via
`state_attr('sensor.X', 'friendly_name')` (German HA → "Distanz
insgesamt"). Each cell falls back to a hard-coded English label when the
entity isn't loaded yet, so the table stays render-safe during HA
startup instead of throwing `UndefinedError: 'None' has no attribute
'name'`.

---

## Roadmap

| Phase | Scope | State |
|---|---|---|
| 1 | OAuth + polling sensors | shipped |
| 2 | FIT → GeoJSON track | shipped |
| 3 | Bundled Leaflet viewer + dashboard | shipped |
| 3+ | Picker UI + selection-driven sensors + backfill | shipped |
| 4 v1 | Lifetime totals + utility_meter | shipped |
| 4 v2 | FTP / power zones | shipped |
| 4 v3 | Indoor / outdoor split + full-history backfill service | shipped |
| 5 | Write endpoints — push routes & plans to ELEMNT | optional, deferred |

The full implementation plan lives at
`.claude/tasks/wahoo_ha_custom_integration_plan.md`.

---

## Development

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e ".[test-integration]"
.venv/bin/pytest tests -v
```

Tier-1 covers the pure-Python modules (`fit.py`, `totals.py`,
`power_zones.py`, `rate_limit.py`) via `importlib`, no HA dependency.
Tier-2 (`tests/integration/`) loads a real HA stack via
`pytest-homeassistant-custom-component` — that's where the dashboard
entity-id regression test lives.

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
├── power_zones.py          # /v1/power_zones parser (Tier-1 testable)
├── rate_limit.py           # rolling-window budget (Tier-1 testable)
├── sensor.py
├── select.py               # workout-picker SelectEntity
├── services.py             # render_workout / select_workout / full_backfill / cleanup_geojson
├── services.yaml
├── strings.json
├── totals.py               # lifetime totals + indoor/outdoor split
├── translations/en.json
├── translations/de.json
└── web/map.html            # Leaflet viewer with picker
```

---

## License

[MIT](./LICENSE).
