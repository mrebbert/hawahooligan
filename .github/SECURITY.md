# Security Policy

## Supported versions

Only the latest released version on `main` receives security fixes. If you are running an older release, please update first; the integration is distributed through HACS and follows semantic-version-style tags.

| Version | Supported |
|---------|-----------|
| Latest release on `main` | yes |
| Older releases | no |

## Reporting a vulnerability

**Please do not open a public issue for security problems.** Use one of the following private channels:

- **Preferred:** [GitHub Security Advisory](https://github.com/mrebbert/hawahooligan/security/advisories/new) — encrypted, private, lets us coordinate a fix and assign a CVE if appropriate.
- Alternative: a private DM via the [Home Assistant Community Forum](https://community.home-assistant.io/u/mrebbert) addressed to the same maintainer.

Please include:

- A description of the issue and its impact.
- Steps to reproduce, or a proof-of-concept if possible.
- Your Home Assistant version and the integration version (`manifest.json`).

You can expect an initial response within roughly a week. This is a hobby project — there is no formal SLA, but credible reports get priority.

## Scope

This integration is an unofficial Home Assistant component built against the [Wahoo Cloud API](https://cloud-api.wahooligan.com/). The relevant security surfaces are:

- **In scope:** issues in the integration code itself (`custom_components/hawahooligan/`), the bundled Leaflet viewer (`web/map.html`), the GeoJSON cache directory (`<config>/www/hawahooligan/`), and the published GitHub releases.
- **Out of scope:** vulnerabilities in Home Assistant core, in HACS, in the Wahoo Cloud API itself, in the [`fitdecode`](https://pypi.org/project/fitdecode/) FIT parser, or in [Leaflet](https://leafletjs.com/). Please report those to the respective upstream projects.

## Credential and token handling

The integration uses Home Assistant's standard OAuth2 + Application Credentials flow against the Wahoo Cloud API. Concretely:

- **Wahoo `client_id` / `client_secret`:** stored by Home Assistant in its Application Credentials registry. Never logged, never written to disk by this integration.
- **OAuth access + refresh tokens:** stored in Home Assistant's encrypted config-entry storage. Refresh tokens rotate on every refresh (Wahoo's design). Tokens are never logged at INFO or higher.
- **FIT files:** downloaded from Wahoo's CDN over HTTPS, parsed locally, written as GeoJSON to `<config>/www/hawahooligan/` so the bundled map viewer can fetch them via Home Assistant's `/local/` static file route.

If you are aware of a way credentials, tokens, or FIT bytes could leak — through logs, diagnostics, or unexpected traffic on the wire — that is in scope.

## A note on the `/local/` cache

The GeoJSON tracks under `<config>/www/hawahooligan/` are served by Home Assistant's static file server at `/local/hawahooligan/`. Anything accessible via your Home Assistant URL is **as exposed as your Home Assistant instance is**. If your instance is reachable from the public internet, your workout tracks are too — that's a property of the `/local/` route, not the integration. The bundled `cleanup_geojson` service helps cap exposure by pruning old files; pair it with HA's own access controls for stronger guarantees.
