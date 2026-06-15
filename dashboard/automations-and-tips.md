# Dashboard automations & tips

What didn't fit in [`dashboard.yaml`](./dashboard.yaml) but is still
worth wiring up: an event-driven PR notifier plus a short
troubleshooting list for the cards in the main dashboard.

## Personal-record notifications

HAWahooligan fires a `hawahooligan_personal_record` event whenever
a newly-polled workout sets a record in distance, duration,
average power, or TSS. Indoor and outdoor records are tracked
separately — your treadmill record doesn't reset your outdoor
record.

Minimal notification automation:

```yaml
alias: Wahoo PR notifier
trigger:
  - platform: event
    event_type: hawahooligan_personal_record
action:
  - service: notify.persistent_notification
    data:
      title: "New {{ trigger.event.data.kind }} record!"
      message: >-
        {% set d = trigger.event.data %}
        {{ d.value | round(1) }}
        {%- if d.previous_value is not none %}
          (previous: {{ d.previous_value | round(1) }})
        {%- else %}
          (first workout of its kind)
        {%- endif %}
        — {{ 'indoor' if d.indoor else 'outdoor' }}
```

Three things worth knowing:

- **Backfill doesn't fire events.** The full-history backfill
  service and the boot-time recent-page catch-up populate the
  baseline silently — importing 1000 historical workouts won't
  blast your notifications.
- **First workout in a class IS a PR.** No warmup period. Your
  first-ever outdoor ride fires events for every populated
  metric. `previous_value` is `null` in that case.
- **One workout can fire multiple events.** A breakthrough
  century ride can beat your distance, duration AND TSS records
  at once — three events, three notifications.

## Troubleshooting

- **Rolling sensors all read 0**: the integration hasn't
  backfilled yet, or `full_backfill` hasn't run. Trigger it from
  Developer Tools → Services → `hawahooligan.full_backfill` and
  wait for the progress events to settle.
- **`utility_meter` sensors don't appear after a YAML paste**:
  the block needs to land at the root of `configuration.yaml`
  (same indent level as `homeassistant:`), not inside another
  component block. Full HA restart after.
- **`statistics-graph` is empty**: long-term statistics need ≥ a
  few hours of recorder history. Give it a day.
