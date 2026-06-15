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
> **Single-user project — use at your own risk.**
> HAWahooligan is in active 0.x development with one real-world user
> (the author). Expect breaking changes between minor versions and
> the odd rough edge: entity IDs, services, dashboard YAML, even the
> default zone factors may still move around in response to live use.
> The integration now does **one** write call to the Wahoo Cloud API
> (`hawahooligan.set_power_zones`) — every other endpoint is read-only,
> so the impact on your Wahoo account stays bounded. Pin a known-good
> release if you depend on stability, and please open an
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

- **32 sensors** covering every ride metric (distance, ascent,
  durations, power, NP, TSS, HR, cadence, work, calories), plus
  lifetime totals (utility_meter-ready), trailing 7d/28d windows,
  workout streak, FTP, and critical power.
- **Workout picker** as a `SelectEntity` — pick a ride, sensors and
  map follow. Indoor / manual rides supported (no-GPS overlay
  instead of an empty map).
- **Bundled Leaflet map viewer** at `/local/hawahooligan/map.html`,
  drops into a built-in iframe card. No HACS frontend cards needed.
- **Auto-render on pick + bulk-render the full history** via the
  `full_backfill` service. Sandbox rate-limit safe, 3-strike 429
  bail-out, resumes after quota reset.
- **PR events on the HA bus** for distance / duration / avg power /
  TSS — automation-ready.
- **Write FTP + zones to Wahoo from HA** via `set_power_zones`
  (0.7.26+). No Postman detour.
- **OAuth handled by HA.** Local install, no public DNS / TLS.
  English + German translations.

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

A single device **HAWahooligan** with 32 sensors plus the workout
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

```yaml
action: hawahooligan.set_power_zones
data:
  ftp: 250
```

The seven zones derive from FTP via Wahoo's own factors (matching
the app's auto-derivation). Override any zone, set
`critical_power`, or pass `workout_type_id: 2` for indoor cycling
when you need to.

For an inline FTP slider on the dashboard, see
[`dashboard/helpers.yaml`](https://github.com/mrebbert/hawahooligan/blob/main/dashboard/helpers.yaml)
— one `input_number` + one script that wraps this service.

> **Why this service exists:** Wahoo's `/v1/power_zones` is
> **app-scoped** — records written via a different OAuth client
> (e.g. Postman) are invisible to HA. The service writes through
> HA's own session so the record is always visible.

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
<summary><strong>"Reauthentication required" notification after upgrading</strong></summary>

A scope was added in a newer release. Click **Configure** and walk
through OAuth — config entry, history, and lifetime totals survive.

</details>

<details>
<summary><strong>Map shows last week's ride, or a thin strip, or an old in-iframe dropdown</strong></summary>

Browser cache on the iframe. Hard-refresh: `Cmd+Shift+R` (macOS),
`Ctrl+Shift+F5` (Windows / Linux). If it's a thin strip in a
`sections` view, set `grid_options.rows: 9` (shipped YAML does).

</details>

<details>
<summary><strong>HTTP 429 — Too Many Requests</strong></summary>

Sandbox limits: 25 / 5 min, 100 / hour, 250 / day. Backfill bails
after 3 consecutive 429s and resumes on next run. Daily quota
exhausted → wait for 00:00 UTC reset or upgrade to Production at
Wahoo.

</details>

<details>
<summary><strong>Wahoo says "token revoked"</strong></summary>

Wahoo expires unused refresh tokens after 60 days. Click
**Configure** and re-authorize.

</details>

<details>
<summary><strong>Sensor cards show "unavailable" — pre-0.7.8 German install</strong></summary>

Old German installs registered e.g. `…_kritische_leistung` instead
of `…_critical_power`. Rename at **Settings → Devices & Services →
HAWahooligan → entity → ⚙ → Entity ID**.

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

### Bulk path (one YAML block, all the buckets)

Per-sensor in the UI gets tedious fast. Pattern for
`configuration.yaml`:

```yaml
utility_meter:
  hawahooligan_distance_weekly:
    name: HAWahooligan distance (weekly)
    source: sensor.hawahooligan_lifetime_distance
    cycle: weekly
  hawahooligan_distance_monthly:
    name: HAWahooligan distance (monthly)
    source: sensor.hawahooligan_lifetime_distance
    cycle: monthly
  # …repeat for duration / workouts / tss / calories / ascent / work
```

Replace `distance` with each lifetime metric you care about
(`duration`, `workouts`, `tss`, `calories`, `ascent`, `work`) and
pick the cycles you actually use (`daily` / `weekly` / `monthly` /
`yearly`). Restart HA, the helpers show up immediately.

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

See [dashboard/automations-and-tips.md](dashboard/automations-and-tips.md) for the PR-notifier automation and troubleshooting tips.

### Indoor / outdoor breakdown

`outdoor` and `indoor` ride along as attributes on lifetime and
rolling sensors. The example dashboard renders them via Markdown;
labels follow the user's HA locale automatically.

---

## Development

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e ".[test-integration]"
.venv/bin/pytest tests -v
```

Tier-1 covers the pure-Python helpers (`fit.py`, `totals.py`,
`power_zones.py`, `rate_limit.py`, `manifest.py`, `rolling.py`,
`streak.py`, `records.py`, `zones.py`) via `importlib`, no HA
dependency. Tier-2 (`tests/integration/`) loads a real HA stack via
`pytest-homeassistant-custom-component`.

---

## License

[MIT](https://github.com/mrebbert/hawahooligan/blob/main/LICENSE).
