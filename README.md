# HAWahooligan

Home Assistant custom integration for the [Wahoo Cloud
API](https://cloud-api.wahooligan.com/).

Imports cycling workouts (summary + GPS track) recorded by Wahoo hardware
(ELEMNT, KICKR, …) into Home Assistant. The integration polls the Wahoo
Cloud every 15 min, exposes the most recent ride's summary as native sensors
(distance, duration, power, heart rate, TSS, …) and writes the FIT track as
a GeoJSON file under `<config>/www/hawahooligan/`. A small Leaflet viewer
ships with the integration and is auto-installed alongside the tracks, so
you can drop a map into Lovelace with a plain iframe card — no extra HACS
frontend cards required.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Manual setup (HACS repo, Wahoo Developer App, OAuth credentials) | docs below |
| 1 | Skeleton + OAuth + polling sensors | shipped |
| 2 | FIT → GeoJSON | shipped |
| 3 | Lovelace dashboard (iframe + Leaflet viewer) | shipped |
| 4 | Analytics (utility_meter, FTP, …) | optional, not started |
| 5 | Write endpoints (routes, plans, uploads) | optional, not started |

## Installation

1. **HACS** → Integrations → ⋮ → Custom repositories → add
   `mrebbert/hawahooligan` as type `Integration`. Then install
   "HAWahooligan" and restart Home Assistant. (No additional HACS frontend
   cards are needed — the map viewer is bundled.)
2. **Wahoo Developer Portal** → create a new app
   ([cloud-api.wahooligan.com](https://cloud-api.wahooligan.com/)):
   - Type: Confidential
   - Redirect URI: `https://my.home-assistant.io/redirect/oauth`
   - Environment: Sandbox is enough for personal use; Production only
     unlocks higher rate limits after a Wahoo review.
   - Note the `client_id` and `client_secret` — these are per-installation
     and **not** shared across users.
3. Settings → Devices & Services → Add Integration → **HAWahooligan**.
   - Paste the `client_id` and `client_secret` into the Application
     Credentials dialog on first run.
   - Complete the OAuth round-trip (browser → Wahoo → My Home Assistant →
     your instance). Works on a local network with no public DNS.

## What you get

After the first poll completes (≤ 15 min after a sync from your bike
computer):

- A `HAWahooligan` device with sensors:
  `last_workout` (timestamp), `distance`, `ascent`, `duration`,
  `speed_avg`, `power_avg`, `power_np`, `tss`, `heart_rate_avg`,
  `cadence_avg`, `calories`, `work`.
- The `last_workout` sensor's attributes carry the workout id, name, type,
  indoor flag, manual flag, time zone, and — for outdoor rides — a
  `geojson_url` pointing at the rendered track.
- Files at `<config>/www/hawahooligan/`:
  - `map.html` — the Leaflet viewer (provisioned on first setup)
  - `<workout_id>.geojson` — one per outdoor workout
  - `latest.geojson` — rolling pointer to the most recent track

See [`dashboard/`](./dashboard/) for an example Lovelace view that combines
the sensors with the map.

## Local development

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e ".[test]"          # Tier-1 (pure helpers)
.venv/bin/pip install -e ".[test-integration]"  # Tier-2 (HA stack)
.venv/bin/pytest tests -v
```

`tests/` is split into Tier-1 (pure-Python, fast, runs `fit.py` directly via
`importlib`) and `tests/integration/` (loads Home Assistant via
`pytest-homeassistant-custom-component`).

## License

See [LICENSE](LICENSE).
