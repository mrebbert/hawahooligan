# Wahoo Cloud API — CLI cookbook

A hands-on guide for hitting the [Wahoo Cloud API](https://cloud-api.wahooligan.com/)
from a terminal. Useful when you want to:

- **Debug** what the HAWahooligan integration sees (or doesn't).
- **Inspect** the raw JSON shape of a workout before writing a template
  sensor or automation.
- **Explore** endpoints the integration doesn't surface yet (e.g. the
  Phase 5 write endpoints).
- **Verify** rate-limit headers and quota state.

> All examples use [`curl`](https://curl.se/) for the HTTP call and
> [`jq`](https://jqlang.github.io/jq/) to format / filter the JSON
> response. Install both before continuing.

## Contents

- [Prerequisites](#prerequisites)
- [Get a bearer token](#get-a-bearer-token)
  - [1. Register a Wahoo developer app](#1-register-a-wahoo-developer-app)
  - [2. Authorize your app (one-time)](#2-authorize-your-app-one-time)
  - [3. Exchange the code for tokens](#3-exchange-the-code-for-tokens)
  - [4. Persist the tokens](#4-persist-the-tokens)
  - [5. Refresh the access token](#5-refresh-the-access-token)
- [Read endpoints](#read-endpoints)
  - [`GET /v1/user`](#get-v1user)
  - [`GET /v1/workouts`](#get-v1workouts)
  - [`GET /v1/workouts/{id}`](#get-v1workoutsid)
  - [Download the FIT file](#download-the-fit-file)
  - [`GET /v1/power_zones`](#get-v1power_zones)
- [Write endpoints (Phase 5 — deferred)](#write-endpoints-phase-5--deferred)
- [Account hygiene](#account-hygiene)
  - [`DELETE /v1/permissions`](#delete-v1permissions)
- [Rate limits and error responses](#rate-limits-and-error-responses)
- [Useful `jq` recipes](#useful-jq-recipes)

---

## Prerequisites

```bash
curl --version  # any reasonably modern build
jq --version    # jq-1.6 or newer
```

The whole flow assumes a POSIX-y shell. On Windows, use WSL or Git Bash.

---

## Get a bearer token

The Wahoo API uses OAuth 2.0 Authorization Code. Five steps total —
steps 1 and 2 happen once, steps 3–5 you may need to repeat.

### 1. Register a Wahoo developer app

1. Sign in at <https://cloud-api.wahooligan.com/>.
2. **My Apps → + Add a new app**.
3. Fill in:
   - **Type:** `Confidential`
   - **Redirect URI:** `https://localhost/callback` (any URL whose
     redirect you can see — we'll read the `?code=…` straight from
     the browser address bar).
   - **Scopes** (tick the ones you need):
     - `user_read` — `GET /v1/user`
     - `workouts_read` — `GET /v1/workouts`, `GET /v1/workouts/{id}`
     - `power_zones_read` — `GET /v1/power_zones`
     - `offline_data` — required for refresh tokens (which is what you
       want for a CLI; otherwise the access token expires in 2 hours
       with no way to renew without going through the browser again)
   - **Environment:** Sandbox is the default for new apps (25 / 5 min,
     100 / hour, 250 / day). Production (200 / 5 min, 1000 / hour,
     5000 / day) requires review.
4. Save. Note the **client_id** and **client_secret** values — you'll
   only see the secret once.

```bash
# Stash them in your shell for the rest of this guide.
export WAHOO_CLIENT_ID='YOUR_CLIENT_ID'
export WAHOO_CLIENT_SECRET='YOUR_CLIENT_SECRET'
export WAHOO_REDIRECT_URI='https://localhost/callback'
```

> **Don't commit these to git.** A leaked client_secret + a captured
> refresh token gives someone full read access to your Wahoo workouts.
> Put them in `~/.bashrc` / `~/.zshrc` or use a secret manager.

### 2. Authorize your app (one-time)

Build the authorization URL and open it in a browser:

```bash
SCOPES='user_read workouts_read power_zones_read offline_data'
SCOPE_ENCODED=$(printf %s "$SCOPES" | jq -sRr @uri)
echo "https://api.wahooligan.com/oauth/authorize?\
client_id=${WAHOO_CLIENT_ID}\
&redirect_uri=$(printf %s "$WAHOO_REDIRECT_URI" | jq -sRr @uri)\
&response_type=code\
&scope=${SCOPE_ENCODED}"
```

Open the URL → log in at Wahoo → click **Authorize**.

Wahoo redirects to your `redirect_uri` with `?code=…`. The browser
will probably complain about `https://localhost/callback` not being
reachable — that's fine. Look at the URL bar:

```
https://localhost/callback?code=ABC123XYZ…
```

Copy the `code` value.

```bash
export WAHOO_AUTH_CODE='ABC123XYZ…'
```

### 3. Exchange the code for tokens

```bash
curl -s -X POST https://api.wahooligan.com/oauth/token \
  -d "client_id=${WAHOO_CLIENT_ID}" \
  -d "client_secret=${WAHOO_CLIENT_SECRET}" \
  -d "grant_type=authorization_code" \
  -d "code=${WAHOO_AUTH_CODE}" \
  -d "redirect_uri=${WAHOO_REDIRECT_URI}" \
  | jq
```

Expected response:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiJ9…",
  "refresh_token": "abc123…",
  "token_type": "bearer",
  "expires_in": 7200,
  "scope": "user_read workouts_read power_zones_read offline_data",
  "created_at": 1749758400,
  "user": { "id": 12345 }
}
```

### 4. Persist the tokens

```bash
export WAHOO_ACCESS_TOKEN='eyJhbGciOiJIUzI1NiJ9…'
export WAHOO_REFRESH_TOKEN='abc123…'
```

The access token is valid for `expires_in` seconds (typically 7200 =
2 hours). After that you'll see `401 Unauthorized`.

> Tip: pipe the response straight into env vars to avoid copy-paste:
>
> ```bash
> read -r WAHOO_ACCESS_TOKEN WAHOO_REFRESH_TOKEN <<<"$(curl -s -X POST \
>   https://api.wahooligan.com/oauth/token \
>   -d "client_id=${WAHOO_CLIENT_ID}" \
>   -d "client_secret=${WAHOO_CLIENT_SECRET}" \
>   -d "grant_type=authorization_code" \
>   -d "code=${WAHOO_AUTH_CODE}" \
>   -d "redirect_uri=${WAHOO_REDIRECT_URI}" \
>   | jq -r '.access_token, .refresh_token' | xargs)"
> export WAHOO_ACCESS_TOKEN WAHOO_REFRESH_TOKEN
> ```

### 5. Refresh the access token

When the access token expires, get a new one with the refresh token —
no browser round-trip required.

```bash
curl -s -X POST https://api.wahooligan.com/oauth/token \
  -d "client_id=${WAHOO_CLIENT_ID}" \
  -d "client_secret=${WAHOO_CLIENT_SECRET}" \
  -d "grant_type=refresh_token" \
  -d "refresh_token=${WAHOO_REFRESH_TOKEN}" \
  | jq
```

Wahoo **rotates** the refresh token on every refresh — the response
contains a NEW `refresh_token` you must store. The old one is dead.

```bash
# Convenience wrapper:
wahoo_refresh() {
  local resp
  resp=$(curl -s -X POST https://api.wahooligan.com/oauth/token \
    -d "client_id=${WAHOO_CLIENT_ID}" \
    -d "client_secret=${WAHOO_CLIENT_SECRET}" \
    -d "grant_type=refresh_token" \
    -d "refresh_token=${WAHOO_REFRESH_TOKEN}")
  export WAHOO_ACCESS_TOKEN=$(jq -r .access_token <<<"$resp")
  export WAHOO_REFRESH_TOKEN=$(jq -r .refresh_token <<<"$resp")
  echo "Token refreshed; expires in $(jq -r .expires_in <<<"$resp")s"
}
```

> Wahoo expires unused refresh tokens after **60 days**. If you don't
> use the API for two months, you have to go back to step 2.

---

## Read endpoints

A reusable curl alias keeps the rest of the doc tidy:

```bash
wahoo() {
  curl -sH "Authorization: Bearer ${WAHOO_ACCESS_TOKEN}" "$@"
}
```

### `GET /v1/user`

Profile of the authenticated user. Surfaced by the integration to pick
the OAuth-2 `unique_id`.

```bash
wahoo https://api.wahooligan.com/v1/user | jq
```

```json
{
  "id": 12345,
  "first": "Jane",
  "last": "Doe",
  "email": "you@example.com",
  "gender": 1,
  "weight": 78.5,
  "height": 1.85,
  "birth": "1984-03-15",
  "created_at": "2023-04-12T08:21:42.000Z"
}
```

### `GET /v1/workouts`

Paginated list of the authenticated user's workouts, newest first.

```bash
wahoo "https://api.wahooligan.com/v1/workouts?per_page=5" | jq
```

```json
{
  "workouts": [
    {
      "id": 99887766,
      "starts": "2026-06-10T07:23:00.000Z",
      "minutes": 75,
      "name": "Morning ride",
      "workout_type_id": 0,
      "workout_summary": {
        "id": 22334455,
        "ascent_accum": "215.0",
        "distance_accum": "31420.5",
        "duration_active_accum": "4505",
        "duration_total_accum": "4670",
        "duration_paused_accum": "165",
        "power_avg": "212",
        "power_bike_np_last": "228",
        "power_bike_tss_last": "85",
        "heart_rate_avg": "148",
        "cadence_avg": "82",
        "speed_avg": "6.97",
        "work_accum": "955800",
        "calories_accum": "768",
        "file": {
          "url": "https://wahoo-cloud-production.s3.amazonaws.com/…/Morning_ride.fit?…"
        },
        "manual": false
      }
    }
  ]
}
```

Pagination:

```bash
# Page 3, 50 entries per page
wahoo "https://api.wahooligan.com/v1/workouts?per_page=50&page=3" | jq

# Pull just the ids of every workout on a page
wahoo "https://api.wahooligan.com/v1/workouts?per_page=50&page=1" \
  | jq '.workouts[].id'
```

### `GET /v1/workouts/{id}`

Full detail for one workout — same shape as the listing, but Wahoo
sometimes returns richer `workout_summary` (e.g. `file.url` only
appears reliably here).

```bash
WORKOUT_ID=99887766
wahoo "https://api.wahooligan.com/v1/workouts/${WORKOUT_ID}" | jq
```

### Download the FIT file

The `workout_summary.file.url` from the detail response is a
pre-signed S3 URL. It's **not** a Wahoo API call — it doesn't count
against your rate limit, doesn't need the Bearer token, and is valid
for a few hours.

```bash
FIT_URL=$(wahoo "https://api.wahooligan.com/v1/workouts/${WORKOUT_ID}" \
  | jq -r '.workout_summary.file.url')

curl -sL -o "${WORKOUT_ID}.fit" "${FIT_URL}"
file "${WORKOUT_ID}.fit"
# 99887766.fit: Flexible and Interoperable Data Transfer (FIT)
```

To convert to GeoJSON the way the integration does, the project ships
`custom_components/hawahooligan/fit.py` as a standalone helper. With
the dev venv set up (see `CONTRIBUTING.md`):

```bash
.venv/bin/python -c "
from pathlib import Path
from custom_components.hawahooligan.fit import parse_fit_to_geojson, write_geojson
feature = parse_fit_to_geojson(Path('${WORKOUT_ID}.fit').read_bytes())
write_geojson(Path('.'), '${WORKOUT_ID}', feature)
"
jq '.geometry.coordinates | length' "${WORKOUT_ID}.geojson"
```

### `GET /v1/power_zones`

Returns all of your power-zone bracket sets (FTP, critical power,
zone 1–7). Wahoo returns one entry per discipline + per profile, so
real responses can have several entries.

```bash
wahoo https://api.wahooligan.com/v1/power_zones | jq
```

```json
{
  "power_zones": [
    {
      "id": 7777,
      "ftp": 245,
      "critical_power": 295,
      "zone_count": 7,
      "zone_1": 134,
      "zone_2": 184,
      "zone_3": 220,
      "zone_4": 257,
      "zone_5": 294,
      "zone_6": 343,
      "zone_7": 588,
      "workout_type_id": 0,
      "workout_type_family_id": 0,
      "updated_at": "2026-04-30T07:21:42.000Z"
    }
  ]
}
```

The integration picks the most recently `updated_at` entry that has a
non-zero `ftp`. See `power_zones.py` for the full tie-breaker logic.

---

## Write endpoints (Phase 5 — deferred)

The integration is **read-only** for now. The endpoints below are
documented for completeness; using them needs additional OAuth scopes
that trigger a fresh authorization round.

| Method | Path | Scope | Notes |
|---|---|---|---|
| `POST` / `PUT` / `DELETE` | `/v1/routes` | `routes_write` | Upload FIT-format routes; they sync to the ELEMNT head unit but NOT the ELEMNT companion app. |
| `POST` / `PUT` / `DELETE` | `/v1/plans` | `plans_write` | Structured workouts; must be attached to a future-dated workout in the next 6 days to show on the head unit. |
| `POST` | `/v1/workout_file_uploads` | `workouts_write` | Push an external FIT into Wahoo's cloud. |

If you need to test one of these from the CLI, repeat the
[authorization step](#2-authorize-your-app-one-time) with the extra
scope added to the `scope=…` query parameter.

---

## Account hygiene

### `DELETE /v1/permissions`

Revoke the current OAuth grant (i.e. deauthorize the app). The
integration calls this when you remove the config entry so the token
slot frees up. There are **10 token slots per account** — if you keep
re-authorizing without revoking, you'll run out.

```bash
wahoo -X DELETE https://api.wahooligan.com/v1/permissions -w '%{http_code}\n'
# 204
```

A `204` means it worked. After this, your access + refresh tokens are
dead and the entry vanishes from <https://cloud-api.wahooligan.com/oauth/applications/authorized>.

---

## Rate limits and error responses

Wahoo enforces three caps simultaneously:

| Tier | 5-minute window | hourly | daily |
|---|---|---|---|
| **Sandbox** (default) | 25 | 100 | **250** |
| **Production** (after review) | 200 | 1000 | 5000 |

When the daily quota is exhausted, **every** call (including a single
`GET /v1/user`) returns `429` until the next 00:00 UTC reset.

```bash
wahoo -i https://api.wahooligan.com/v1/user | head -20
# HTTP/2 429
# retry-after: 250
# …
```

Useful one-liner to monitor your quota during testing:

```bash
wahoo -i https://api.wahooligan.com/v1/user 2>/dev/null \
  | grep -i 'retry-after\|^HTTP'
```

Common HTTP statuses:

| Status | Meaning | What to do |
|---|---|---|
| `200` | OK | — |
| `204` | OK, no body | (used by `DELETE /v1/permissions`) |
| `400` | Bad request — usually a malformed OAuth grant | Re-check the params |
| `401` | Token invalid / expired | [Refresh it](#5-refresh-the-access-token) |
| `403` | Token valid but scope insufficient | Re-authorize with the right scope |
| `404` | Workout id doesn't exist (or doesn't belong to you) | — |
| `429` | Rate limit | Wait for the `Retry-After` window (or the next 00:00 UTC for daily) |

---

## Useful `jq` recipes

```bash
# Total km across the last 100 listed workouts
wahoo "https://api.wahooligan.com/v1/workouts?per_page=100" \
  | jq '[.workouts[].workout_summary.distance_accum | tonumber] | add / 1000'

# All outdoor rides (workout_type_id 0) from page 1 with name + minutes
wahoo "https://api.wahooligan.com/v1/workouts?per_page=50&page=1" \
  | jq '.workouts[] | select(.workout_type_id == 0) | {id, starts, name, minutes}'

# Workouts that don't have a renderable FIT (manual entries, indoor sessions)
wahoo "https://api.wahooligan.com/v1/workouts?per_page=50" \
  | jq '.workouts[] | select(.workout_summary.file.url == null) | {id, name, manual: .workout_summary.manual}'

# Dump every workout summary field as a flat key=value list (handy for
# spotting fields the integration doesn't surface yet)
wahoo "https://api.wahooligan.com/v1/workouts/${WORKOUT_ID}" \
  | jq -r '.workout_summary | to_entries[] | "\(.key)=\(.value)"' \
  | sort

# Walk pagination until the listing returns an empty array
page=1
while :; do
  body=$(wahoo "https://api.wahooligan.com/v1/workouts?per_page=50&page=${page}")
  count=$(jq '.workouts | length' <<<"$body")
  [[ "$count" -eq 0 ]] && break
  jq -r '.workouts[] | "\(.id)\t\(.starts)\t\(.name)"' <<<"$body"
  page=$((page + 1))
done
```

---

## Where to go next

- Project [README](../README.md) — Home Assistant integration setup.
- [Wahoo Cloud API official reference](https://cloud-api.wahooligan.com/) — Wahoo's own docs (when they're up to date).
- HAWahooligan source: `custom_components/hawahooligan/api.py` is the
  exact shape every endpoint call takes inside the integration —
  matching it to a curl request is the fastest way to A/B test a
  change.
