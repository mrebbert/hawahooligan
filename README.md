# HAWahooligan

Home Assistant custom integration for the [Wahoo Cloud API](https://cloud-api.wahooligan.com/).

Imports cycling workouts (summary + GPS track) recorded by Wahoo hardware
(ELEMNT, KICKR, …) into Home Assistant as sensors and a GeoJSON map layer.

> Project skeleton — implementation in progress. See `tasks/` (local) for the
> phased build plan.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Manual setup (HACS repo, Wahoo Developer App, OAuth credentials) | docs pending |
| 1 | Skeleton + OAuth + polling sensors | not started |
| 2 | FIT → GeoJSON | not started |
| 3 | `ha-map-card` dashboard | not started |
| 4 | Analytics (utility_meter, FTP, …) | optional |
| 5 | Write endpoints (routes, plans, uploads) | optional |

## License

See [LICENSE](LICENSE).
