# Dashboard extras — period stats & comparisons

Copy-paste Lovelace cards that build on HAWahooligan's lifetime totals,
rolling-window sensors, and `utility_meter` calendar buckets. None of
this requires HACS frontend cards — everything below uses Home
Assistant's built-in card types.

Prerequisites:

- HAWahooligan ≥ 0.7.20 installed (`rolling_*` sensors).
- The `utility_meter` YAML block from
  [README → Bulk path](../README.md#bulk-path-one-yaml-block-all-the-buckets-you-actually-want)
  pasted into `configuration.yaml` and HA restarted (only needed for
  the calendar-bucket cards).

---

## 1. Rolling-window stat tiles

A four-up grid that answers "what have I done lately?" at a glance.
Uses the trailing-window sensors directly — no helper config required.

```yaml
type: grid
columns: 2
square: false
cards:
  - type: tile
    entity: sensor.hawahooligan_rolling_distance_7d
    name: Distance (7d)
    icon: mdi:map-marker-distance
  - type: tile
    entity: sensor.hawahooligan_rolling_duration_7d
    name: Saddle time (7d)
    icon: mdi:timer-outline
  - type: tile
    entity: sensor.hawahooligan_rolling_workouts_7d
    name: Workouts (7d)
    icon: mdi:run-fast
  - type: tile
    entity: sensor.hawahooligan_rolling_tss_28d
    name: Training load (28d)
    icon: mdi:chart-bell-curve
```

The 7d sensors are **rolling** — "the last 7 days ending now", not
"this calendar week". For Monday-to-Sunday buckets use the
`utility_meter` sensors instead (next section).

## 2. This calendar week vs this calendar month

Requires the `utility_meter` block from the README. Both buckets reset
on schedule (Sunday/end-of-month) and show progress since the reset.

```yaml
type: entities
title: Calendar buckets
entities:
  - entity: sensor.hawahooligan_distance_weekly
    name: Distance this week
  - entity: sensor.hawahooligan_distance_monthly
    name: Distance this month
  - entity: sensor.hawahooligan_distance_yearly
    name: Distance this year
  - entity: sensor.hawahooligan_duration_weekly
    name: Saddle time this week
  - entity: sensor.hawahooligan_workouts_monthly
    name: Workouts this month
  - entity: sensor.hawahooligan_tss_weekly
    name: Training stress this week
```

## 3. Rolling 28-day trend graph

A history graph for the 28d distance window — shows how this month's
training load builds and bleeds. Great for spotting under-training
weeks before they turn into a rut.

```yaml
type: history-graph
title: Rolling 28-day distance
hours_to_show: 168
entities:
  - entity: sensor.hawahooligan_rolling_distance_28d
    name: Distance (28d)
```

The line goes UP when a workout completes and DOWN when an old
workout falls out of the trailing window. A flat line = no activity
in the last 28 days.

## 4. Weekly vs monthly comparison (statistics-graph card)

HA's `statistics-graph` card aggregates the long-term-statistics
recorder data. Works well for "last 12 weeks" or "last 12 months"
overviews on the utility_meter sensors.

```yaml
type: statistics-graph
title: Weekly distance — last 12 weeks
period: week
days_to_show: 84
stat_types:
  - max
entities:
  - sensor.hawahooligan_distance_weekly
```

The card uses `stat_types: max` because `utility_meter` buckets are
cumulative within their cycle — the peak value at cycle end is what
you actually rode. Swap `period: week` → `period: month` and
`days_to_show: 84` → `days_to_show: 365` for the yearly view.

## 5. Indoor vs outdoor breakdown (Markdown)

The lifetime and rolling sensors both carry `outdoor` / `indoor`
sub-sums as attributes. A Markdown card reads them directly:

```yaml
type: markdown
content: |
  ### Last 7 days

  |          | Outdoor | Indoor |
  |----------|---------|--------|
  | Distance | {{ state_attr('sensor.hawahooligan_rolling_distance_7d', 'outdoor') | round(1) }} km | {{ state_attr('sensor.hawahooligan_rolling_distance_7d', 'indoor') | round(1) }} km |
  | Duration | {{ state_attr('sensor.hawahooligan_rolling_duration_7d', 'outdoor') | int }} min | {{ state_attr('sensor.hawahooligan_rolling_duration_7d', 'indoor') | int }} min |
  | Workouts | {{ state_attr('sensor.hawahooligan_rolling_workouts_7d', 'outdoor') }} | {{ state_attr('sensor.hawahooligan_rolling_workouts_7d', 'indoor') }} |
```

## 6. Personal-record awareness (template sensor)

Until the planned PR-detection event ships natively (Quick Win #3
in `tasks/todo.md`), you can roll your own "longest ride this month"
indicator with a template sensor. Add to `configuration.yaml`:

```yaml
template:
  - sensor:
      - name: Wahoo longest ride this month
        unit_of_measurement: km
        state: >
          {% set d = states('sensor.hawahooligan_distance') | float(0) %}
          {% set m = states('sensor.hawahooligan_distance_monthly') | float(0) %}
          {{ [d, m] | max | round(1) }}
```

Then add a tile card pointed at `sensor.wahoo_longest_ride_this_month`.

---

## Troubleshooting

- **Rolling sensors all read 0**: the integration hasn't backfilled
  yet, or `full_backfill` hasn't run. Trigger it from
  Developer Tools → Services → `hawahooligan.full_backfill` and wait
  for the progress events to settle.
- **`utility_meter` sensors don't appear after a YAML paste**: the
  block needs to land at the *root* of `configuration.yaml` (same
  indent level as `homeassistant:`), not inside another component
  block. Then full HA restart.
- **`statistics-graph` is empty**: long-term statistics need ≥ a few
  hours of recorder history. Give it a day.
