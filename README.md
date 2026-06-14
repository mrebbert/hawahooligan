# HAWahooligan — Wahoo Cloud integration for Home Assistant

![Wahoo wordmark](https://raw.githubusercontent.com/mrebbert/hawahooligan/main/custom_components/hawahooligan/brand/logo.png)

[![Tests](https://github.com/mrebbert/hawahooligan/actions/workflows/test.yml/badge.svg)](https://github.com/mrebbert/hawahooligan/actions/workflows/test.yml)
[![Validate](https://github.com/mrebbert/hawahooligan/actions/workflows/validate.yml/badge.svg)](https://github.com/mrebbert/hawahooligan/actions/workflows/validate.yml)
[![GitHub release](https://img.shields.io/github/v/release/mrebbert/hawahooligan)](https://github.com/mrebbert/hawahooligan/releases/latest)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/mrebbert/hawahooligan/blob/main/LICENSE)

> **Track your Wahoo rides in Home Assistant — sensors for every ride
> metric, lifetime totals, a built-in Leaflet map for GPS tracks, and
> a workout picker that drives both the map and the headline sensors
> in one click.**

> [!WARNING]
> **Early-stage software — use at your own risk.**
> HAWahooligan is in active 0.x development. Expect occasional breaking
> changes between minor versions and the odd rough edge — entity IDs,
> services, and dashboard YAML may still move around. The integration
> is **read-only** against the Wahoo Cloud API (no writes, no
> deletions), so the impact on your Wahoo account is bounded. Pin a
> known-good release if you depend on stability, and please open an
> [issue](https://github.com/mrebbert/hawahooligan/issues) for anything
> that surprises you.

## What is HAWahooligan?

**HAWahooligan is a [Home Assistant](https://www.home-assistant.io/)
custom integration for the [Wahoo Cloud
API](https://cloud-api.wahooligan.com/).** It polls your Wahoo account
every 15 minutes, exposes the latest ride as native Home Assistant
sensors, persists lifetime totals across restarts, and renders FIT
files as GeoJSON tracks for a bundled Leaflet map viewer.

Built for cyclists who already use a **Wahoo ELEMNT** (BOLT, ROAM,
RIVAL, …) and want their rides surfaced in their home automation
dashboard — distance, duration, power, heart rate, TSS, FTP, route
on a map — without writing Python, templates, or YAML automations.

## Features

- **23 native sensors** covering distance, ascent, duration (active /
  total / paused), average speed, average power, normalized power,
  TSS, average heart rate, average cadence, calories, work, FTP,
  critical power, and full lifetime totals (`state_class=total_increasing`,
  utility_meter-ready).
- **Indoor / outdoor split** as `outdoor` and `indoor` attributes on
  every lifetime sensor — break down weekly km or monthly TSS by
  location without spawning a second set of entities.
- **Workout picker as a Home Assistant `SelectEntity`.** Pick any
  workout from a dropdown card and the headline sensors plus the map
  follow. Indoor and manual rides are picker-eligible too; the map
  shows a friendly "no GPS" overlay instead of breaking.
- **Bundled Leaflet map viewer** — `/local/hawahooligan/map.html`,
  embeddable via a built-in iframe card. No extra HACS frontend cards
  required.
- **FIT → GeoJSON renderer** runs locally; tracks land at
  `<config>/www/hawahooligan/<workout_id>.geojson` and stay accessible
  even if your Wahoo account is offline.
- **Auto-render on pick:** picking an outdoor workout whose track
  isn't on disk yet kicks off a background render. The map fills in
  seconds — one Wahoo API call per pick, idempotent.
- **Bulk-render the full history** via the `hawahooligan.full_backfill`
  service with `with_tracks: true`. Sandbox-safe rate-limit defaults
  + 3-strike 429 bail-out; resumes from where it left off after a
  quota reset.
- **OAuth + token-rotation handled by Home Assistant.** No public DNS
  or TLS required — local Home Assistant install, plus your own Wahoo
  developer credentials (the integration deliberately does not ship a
  shared client secret).
- **i18n:** English and German translations included.

## Table of contents

- [Quick start](#quick-start)
- [Sensors and attributes](#sensors-and-attributes)
- [Map viewer](#map-viewer)
- [Services](#services)
- [Dashboard example](#dashboard-example)
- [Troubleshooting / FAQ](#troubleshooting--faq)
- [Advanced: lifetime totals + utility_meter](#advanced-lifetime-totals--utility_meter)
- [Development](#development)
- [License](#license)

---

## Quick start

### Step 1 — Install via HACS

The fastest path: click the badge below. It opens HACS on your Home
Assistant instance with this repository pre-filled. Then click
**Download** → restart Home Assistant.

[![Open HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mrebbert&repository=hawahooligan&category=integration)

The manual path:

1. **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/mrebbert/hawahooligan` as type **Integration**
3. Download **HAWahooligan** and restart Home Assistant

> The bundled Leaflet viewer means **no extra HACS frontend cards** are
> required — the map drops straight into a built-in iframe card.

### Step 2 — Create a Wahoo developer app

You need your own Wahoo OAuth credentials.

1. Go to <https://cloud-api.wahooligan.com/> → **My Apps** → **+ Add a new app**
2. Fill in:
   - **Type:** `Confidential`
   - **Redirect URI:** `https://my.home-assistant.io/redirect/oauth`
   - **Scopes:** `user_read workouts_read power_zones_read offline_data`
   - **Environment:** Sandbox (25 / 5 min, 100 / hour, **250 / day**) is
     enough for personal use. For full-history backfills on a large
     workout history, request **Production** (200 / 5 min, 1000 / hour,
     5000 / day) via Wahoo's review process.
3. Save and note the **client_id** and **client_secret**.

> Want to poke the Wahoo Cloud API directly from a terminal to debug
> what the integration sees (or to explore endpoints it doesn't surface
> yet)? See [`docs/wahoo-cloud-api-cli.md`](https://github.com/mrebbert/hawahooligan/blob/main/docs/wahoo-cloud-api-cli.md)
> for the full curl + jq cookbook (OAuth flow, every read endpoint with
> examples, rate-limit notes, useful jq recipes).

### Step 3 — Add the integration to Home Assistant

[![Add HAWahooligan integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hawahooligan)

The manual path:

1. **Settings → Devices & Services → Add Integration → HAWahooligan**
2. Paste the **client_id** / **client_secret** into the Application
   Credentials dialog (Home Assistant prompts you the first time).
3. Complete the OAuth round-trip (browser → Wahoo →
   `my.home-assistant.io` → your Home Assistant).

Works on your local network — no public DNS / TLS required. Home
Assistant handles token refresh and rotates the refresh token on
every refresh.

> The first sync triggers a background backfill of your **last 20
> outdoor rides** under a sandbox-safe rate-limit budget. The map and
> the picker go live as soon as the first GeoJSON file lands.

---

## Sensors and attributes

A single device **HAWahooligan** with 23 sensors plus the workout
picker. Entity IDs follow the slugified English friendly name (e.g.
`sensor.hawahooligan_average_speed`, **not** `..._speed_avg`).

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

### Trailing-window sensors (0.7.20+, `state_class=measurement`)

| Sensor | Unit | Attributes |
|---|---|---|
| `_rolling_distance_7d` / `_28d` | km | `outdoor`, `indoor` |
| `_rolling_duration_7d` / `_28d` | min | `outdoor`, `indoor` |
| `_rolling_workouts_7d` / `_28d` | count | `outdoor`, `indoor` |
| `_rolling_tss_7d` / `_28d` | – | – |

Rolling = "the last N days ending NOW", NOT "this calendar week".
For calendar buckets see [Advanced: lifetime totals + utility_meter](#advanced-lifetime-totals--utility_meter).

### Streak (0.7.25+, `state_class=measurement`)

| Sensor | Unit | Attributes |
|---|---|---|
| `_streak` | days | `longest_streak`, `current_streak_start_date`, `last_workout_date` |

Consecutive calendar days (in HA's local timezone) with at least one
workout. The current streak is valid if it ends **today or yesterday**
— users opening the dashboard at 6am the morning after a 30-day streak
still see 30, not 0. Older trailing runs report 0.

### Personal-record events (0.7.25+)

When the polling path detects a new workout that sets a record in any
of distance / duration / avg power / TSS — indoor and outdoor tracked
separately — HAWahooligan fires a `hawahooligan_personal_record` event
on the HA bus. Payload:

```yaml
event_type: hawahooligan_personal_record
event_data:
  kind: distance        # one of: distance, duration, power_avg, tss
  value: 120.5          # the new high
  previous_value: 95.0  # the old max (null on the first-ever workout)
  workout_id: 1234567
  indoor: false
```

Wire it into an automation trigger to notify on every PR:

```yaml
trigger:
  - platform: event
    event_type: hawahooligan_personal_record
action:
  - service: notify.persistent_notification
    data:
      title: "New {{ trigger.event.data.kind }} record!"
      message: "{{ trigger.event.data.value | round(1) }} (previous: {{ trigger.event.data.previous_value | round(1) }})"
```

Backfill paths (the full-history backfill service, the recent-page
catch-up at boot) deliberately stay silent — they populate the baseline
without flooding the bus with stale records.

### Workout picker

`select.hawahooligan_workout_picker` — every workout the integration
has ever seen, labelled `YYYY-MM-DD · name · duration · 🚴/🏠/📝`.
Driven by both the regular poll (last 20) and the `full_backfill`
service (everything else).

### Attributes on `sensor.hawahooligan_last_workout`

`workout_id`, `name`, `workout_type_id`, `workout_type`, `indoor`,
`manual`, `edited`, `time_zone`, `fitness_app_id`, `starts`,
`geojson_url`, **`route_id`**, **`plan_id`**, **`plan_ids`**,
**`recent`** (rolling list of the last 20 rides for templating),
**`selected_workout_id`** (set when you've pinned a specific ride via
the picker or service).

---

## Map viewer

Auto-provisioned at `/local/hawahooligan/map.html`. Embed via a
Lovelace iframe card (the example dashboard does this for you).

| What | How |
|---|---|
| Default view | Renders `latest.geojson` (the most recent outdoor ride). |
| Deep link | Append `?id=<workout_id>`, e.g. `/local/hawahooligan/map.html?id=12345`. |
| Browse history | The `select.hawahooligan_workout_picker` dropdown (shipped as a card right above the iframe) lists every workout the integration has ever seen. Picking one drives the headline sensors AND the iframe in one go. |
| Auto-render on pick | Picking an outdoor / non-manual ride whose `.geojson` isn't on disk yet kicks off a background render (1 Wahoo API call + FIT download; FIT downloads don't count against the Wahoo rate limit). The map fills within seconds. |
| Bulk-render history | Call `hawahooligan.full_backfill` with `with_tracks: true` to render every historic outdoor track in one shot. Default budget (8 detail calls / 5 min ≈ 96 / hour) stays under the Sandbox hourly cap; pass `max_calls_per_window: 50` on the Production tier for much faster runs. If your daily Sandbox quota is exhausted mid-run the backfill bails after 3 consecutive 429s and resumes from where it left off the next time you call it. |
| Indoor / manual rides | Pickable like any other workout. Sensors update; the iframe shows a friendly "no GPS track" overlay instead of an empty map. |
| Stay in sync | `hawahooligan.cleanup_geojson` removes manifest entries for any tracks it deletes, so the dropdown reflects what's actually on disk. Indoor / manual rows (no track to time-check) are untouched. |

> The integration writes `<config>/www/hawahooligan/map.html` once per
> setup. Customise it by editing the file directly **and** deleting
> the `HAWahooligan-Viewer-Version: N` comment in the header — the
> integration only auto-updates files that still carry the version
> stamp.

---

## Services

| Service | What it does |
|---|---|
| `hawahooligan.select_workout` | Pin the integration to a workout ID (or pass `"latest"` to release the pin). Sensors and map both follow. The picker calls this automatically. |
| `hawahooligan.render_workout` | Render the GeoJSON for an arbitrary workout ID — useful for rides outside the auto-render path. |
| `hawahooligan.full_backfill` | Paginate through your entire Wahoo history and feed the lifetime totals. Rate-limit aware: Sandbox-safe default of 8 calls / 5 min (≈ 96 / hour), bails after 3 consecutive 429s. Pass `with_tracks: true` to also render every historic outdoor track. Fires `hawahooligan_full_backfill_progress` events per page so you can wire a notification. |
| `hawahooligan.cleanup_geojson` | Prune cached GeoJSON tracks in `<config>/www/hawahooligan/` older than `max_age_days` (default 180). Wire to a nightly automation to cap unbounded growth. |
| `hawahooligan.refresh_power_zones` | Force an immediate refresh of the FTP / Critical Power / zone-threshold sensors instead of waiting for the regular 24-hour cycle. Useful after updating FTP in the Wahoo app or after a Reauth that just granted the `power_zones_read` scope. Fire-and-forget — runs in the background. |
| `hawahooligan.set_power_zones` | Set or update your FTP, critical power, and the seven zone boundaries directly from HA (0.7.26+). Auto-derives `zone_1`..`zone_7` from FTP via Wahoo-style defaults (matching the Wahoo app's auto-derivation); pass any `zone_N` to override. POSTs on first call, PUTs on subsequent calls. Triggers an immediate sensor refresh. Requires the `power_zones_write` scope (added in 0.7.26 — existing users see a one-time reauth banner on upgrade). |

### Setting your FTP from HA (0.7.26+)

The `set_power_zones` service lets you write your FTP and zones to
the Wahoo Cloud API without leaving Home Assistant. Minimal call:

```yaml
service: hawahooligan.set_power_zones
data:
  ftp: 250
```

That POSTs a new record (or PUTs the existing one) with FTP = 250 W,
critical power = 250 W, and the seven Wahoo-style derived boundaries
(zone_1 = 138, zone_2 = 175, …, zone_7 = 1250 — matching the Wahoo
app's own auto-derivation). Override any zone explicitly when you
know better:

```yaml
service: hawahooligan.set_power_zones
data:
  ftp: 250
  critical_power: 265
  zone_4: 270        # pin LT to your tested value
  workout_type_id: 0 # 0 = Biking (default), 2 = Indoor cycling
```

The FTP / Critical Power sensors refresh immediately — no need to wait
for the daily poll.

**Why this exists:** Wahoo's `/v1/power_zones` is **app-scoped** —
records written through a different OAuth client (e.g. via Postman
with a separate developer app) are invisible to HA. Pre-0.7.26 the
only options were to set FTP in the Wahoo companion app (whose
cloud sync is unreliable) or to manually re-authorize Postman with
HA's `client_id`. The new service writes through HA's own OAuth
session so the record is always visible to HA.

---

## Dashboard example

[`dashboard/dashboard.yaml`](https://github.com/mrebbert/hawahooligan/blob/main/dashboard/dashboard.yaml) is a
ready-to-paste Lovelace view with **seven sections**:

1. **Map** — Leaflet iframe with the picker card above it.
2. **Workout** — `last_workout` state + key attributes (name, type,
   indoor flag, route / plan IDs, current selection).
3. **Time & distance** — durations, distance, ascent, average speed,
   calories.
4. **Power & body** — power average, normalized power, TSS, work,
   average heart rate, average cadence.
5. **Lifetime** — utility_meter-ready totals (workouts, distance,
   ascent, duration, calories, work, TSS).
6. **Outdoor vs indoor** — Markdown table reading the `outdoor` /
   `indoor` attributes from every lifetime sensor. Row labels follow
   the user's Home Assistant locale automatically.
7. **Profile** — FTP and critical power. Zone thresholds are
   attributes on `_ftp`.

To install: open your dashboard → ⋮ → **Edit dashboard** → ⋮ →
**Raw configuration editor** → paste the file's `views:` block.

See [`dashboard/README.md`](https://github.com/mrebbert/hawahooligan/blob/main/dashboard/README.md) for the walkthrough
and customisation tips (including why the iframe needs
`grid_options.rows` instead of `aspect_ratio`).

---

## Troubleshooting / FAQ

<details>
<summary><strong>Sensor cards show "unavailable"</strong></summary>

Two common causes:

1. **Stale dashboard YAML.** Re-paste
   [`dashboard/dashboard.yaml`](https://github.com/mrebbert/hawahooligan/blob/main/dashboard/dashboard.yaml) from the
   latest release.
2. **Non-English HA install carrying entity IDs from before 0.7.8.**
   Old German installs registered e.g. `sensor.hawahooligan_kritische_leistung`
   instead of `…_critical_power`. Fresh installs are pinned to the
   English slug; for existing ones, rename at **Settings → Devices &
   Services → HAWahooligan → entity → ⚙ → Entity ID**.

</details>

<details>
<summary><strong>The map is a thin strip at the top of its card</strong></summary>

`sections` views ignore `aspect_ratio` on iframe cards. Set
`grid_options.rows: 9` explicitly (the shipped YAML already does).

</details>

<details>
<summary><strong>Old in-iframe dropdown still visible after upgrade</strong></summary>

Your browser cached the old `map.html`. Hard-reload it: open
`<your HA URL>/local/hawahooligan/map.html` directly and press
`Cmd+Shift+R` (macOS) / `Ctrl+Shift+F5` (Windows / Linux), then go
back to the dashboard.

</details>

<details>
<summary><strong>Picker updates sensors but the map sits on the previous track</strong></summary>

Check the `HAWahooligan-Viewer-Version` line in
`<config>/www/hawahooligan/map.html`. If it's v3, hard-reload (see
above). If it's v5+ and the map still lags, call
`hawahooligan.select_workout` from Developer Tools to force a refresh.

</details>

<details>
<summary><strong>Map shows last week's ride after an update</strong></summary>

Browser cache on the iframe. Hard-refresh: `Cmd+Shift+R` (macOS),
`Ctrl+Shift+F5` (Windows / Linux).

</details>

<details>
<summary><strong>"Reauthentication required" notification after upgrading</strong></summary>

A scope was added in a newer release. Click **Configure** in the
notification and walk through OAuth — the config entry, entity
history, and lifetime totals all survive.

</details>

<details>
<summary><strong>HTTP 429 — Too Many Requests</strong></summary>

Sandbox limits: **25 / 5 min**, **100 / hour**, **250 / day**. The
backfill loops bail after 3 consecutive 429s and pick up where they
left off on the next run; workouts already in totals are skipped.

If the daily 250-call cap is exhausted: wait for the 00:00 UTC
reset, or upgrade your Wahoo developer app to Production. Picks that
trigger an auto-render hit the same limit (one detail call); the
warning `On-demand render for outdoor workout N returned no track`
is the signal.

</details>

<details>
<summary><strong>Wahoo says "token revoked"</strong></summary>

Wahoo expires unused refresh tokens after 60 days. Click **Configure**
in the reauth notification and walk through OAuth again.

</details>

<details>
<summary><strong>Lifetime totals reset to 0 after restart</strong></summary>

That bug was real in 0.6.0–0.6.x — `async_load_totals` was wired but
not called on startup. Fixed in 0.7.0. Update to a current release
and the persisted store at
`.storage/hawahooligan_totals_<entry_id>.json` is rehydrated on
every restart.

</details>

---

## Advanced: lifetime totals + utility_meter

Each lifetime sensor carries `state_class=total_increasing`, so the
Home Assistant recorder keeps long-term statistics automatically.
That's also the exact interface HA's built-in
[`utility_meter`](https://www.home-assistant.io/integrations/utility_meter/)
integration consumes — it gives you daily / weekly / monthly / yearly
buckets for free, no Python, no template sensors.

### Quick path (HA UI, per sensor)

1. **Settings → Devices & Services → Helpers → Create helper →
   Utility Meter**
2. Source: pick any `sensor.hawahooligan_lifetime_*`
3. Cycle: `daily`, `weekly`, `monthly`, `yearly` …

The result is `sensor.<your_helper>` with your weekly km / TSS /
etc., resetting at the cycle boundary.

### Bulk path (one YAML block, all the buckets you actually want)

Paste this into `configuration.yaml` and restart HA. You get sixteen
ready-made aggregations across the four metrics most dashboards
actually need:

```yaml
utility_meter:
  hawahooligan_distance_daily:
    name: HAWahooligan distance (daily)
    source: sensor.hawahooligan_lifetime_distance
    cycle: daily
  hawahooligan_distance_weekly:
    name: HAWahooligan distance (weekly)
    source: sensor.hawahooligan_lifetime_distance
    cycle: weekly
  hawahooligan_distance_monthly:
    name: HAWahooligan distance (monthly)
    source: sensor.hawahooligan_lifetime_distance
    cycle: monthly
  hawahooligan_distance_yearly:
    name: HAWahooligan distance (yearly)
    source: sensor.hawahooligan_lifetime_distance
    cycle: yearly
  hawahooligan_duration_weekly:
    name: HAWahooligan duration (weekly)
    source: sensor.hawahooligan_lifetime_duration
    cycle: weekly
  hawahooligan_duration_monthly:
    name: HAWahooligan duration (monthly)
    source: sensor.hawahooligan_lifetime_duration
    cycle: monthly
  hawahooligan_duration_yearly:
    name: HAWahooligan duration (yearly)
    source: sensor.hawahooligan_lifetime_duration
    cycle: yearly
  hawahooligan_workouts_weekly:
    name: HAWahooligan workouts (weekly)
    source: sensor.hawahooligan_lifetime_workouts
    cycle: weekly
  hawahooligan_workouts_monthly:
    name: HAWahooligan workouts (monthly)
    source: sensor.hawahooligan_lifetime_workouts
    cycle: monthly
  hawahooligan_workouts_yearly:
    name: HAWahooligan workouts (yearly)
    source: sensor.hawahooligan_lifetime_workouts
    cycle: yearly
  hawahooligan_tss_weekly:
    name: HAWahooligan TSS (weekly)
    source: sensor.hawahooligan_lifetime_tss
    cycle: weekly
  hawahooligan_tss_monthly:
    name: HAWahooligan TSS (monthly)
    source: sensor.hawahooligan_lifetime_tss
    cycle: monthly
  hawahooligan_calories_weekly:
    name: HAWahooligan calories (weekly)
    source: sensor.hawahooligan_lifetime_calories
    cycle: weekly
  hawahooligan_calories_monthly:
    name: HAWahooligan calories (monthly)
    source: sensor.hawahooligan_lifetime_calories
    cycle: monthly
  hawahooligan_ascent_monthly:
    name: HAWahooligan ascent (monthly)
    source: sensor.hawahooligan_lifetime_ascent
    cycle: monthly
  hawahooligan_work_monthly:
    name: HAWahooligan work (monthly)
    source: sensor.hawahooligan_lifetime_work
    cycle: monthly
```

### Rolling vs calendar buckets — which one to use

`utility_meter` cycles are **calendar-aligned**: a `weekly` bucket
resets every Sunday at midnight. If you want a **rolling 7-day
window** that includes "the last 7 days ending right now", that's
what the `rolling_*` sensors (shipped 0.7.20+) cover directly:

| Question | Right sensor |
|---|---|
| "How much have I ridden THIS week (Mon–Sun)?" | `utility_meter` weekly bucket |
| "How much have I ridden in the LAST 7 days?" | `sensor.hawahooligan_rolling_distance_7d` |
| "Monthly training load this calendar month?" | `utility_meter` monthly bucket on lifetime TSS |
| "28-day rolling training load (CTL-like)?" | `sensor.hawahooligan_rolling_tss_28d` |

See [docs/dashboard-extras.md](docs/dashboard-extras.md) for ready-made
Lovelace cards built on top of both flavors.

### Indoor / outdoor breakdown

Indoor / outdoor sub-sums ride along as `outdoor` and `indoor`
attributes on both the lifetime and the rolling sensors. The example
dashboard renders them as a compact Markdown table that picks up
your locale automatically via `state_attr('sensor.X', 'friendly_name')`
(German HA → "Distanz insgesamt"). Each cell falls back to a hard-coded
English label when the entity isn't loaded yet, so the table stays
render-safe during HA startup instead of throwing
`UndefinedError: 'None' has no attribute 'name'`.

---

## Development

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e ".[test-integration]"
.venv/bin/pytest tests -v
```

Tier-1 covers the pure-Python modules (`fit.py`, `totals.py`,
`power_zones.py`, `rate_limit.py`, `manifest.py`) via `importlib`,
with no Home Assistant dependency. Tier-2 (`tests/integration/`)
loads a real HA stack via `pytest-homeassistant-custom-component` —
that's where the dashboard entity-id regression test lives.

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
├── manifest.py             # picker workouts.json accumulator (Tier-1 testable)
├── power_zones.py          # /v1/power_zones parser (Tier-1 testable)
├── rate_limit.py           # rolling-window budget + 429-bail guard (Tier-1)
├── sensor.py
├── select.py               # workout-picker SelectEntity
├── services.py             # render_workout / select_workout / full_backfill / cleanup_geojson
├── services.yaml
├── strings.json
├── totals.py               # lifetime totals + indoor / outdoor split
├── translations/en.json
├── translations/de.json
└── web/map.html            # Leaflet viewer with no-GPS overlay
```

---

## License

[MIT](https://github.com/mrebbert/hawahooligan/blob/main/LICENSE).
