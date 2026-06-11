# Contributing to HAWahooligan

Thanks for taking the time to look into contributing — this is a hobby project, but every clean PR or well-described bug report makes it better.

## Before opening an issue or PR

- For **questions, setup help, dashboard tinkering, automation ideas**: please use [GitHub Discussions](https://github.com/mrebbert/hawahooligan/discussions) (if enabled) or the [Home Assistant Community Forum](https://community.home-assistant.io/) instead of an issue.
- For **bug reports** and **feature requests**: open an issue. The repo has templates for both — please fill the requested fields (HA version, integration version, Wahoo API tier, logs).
- Search [existing issues](https://github.com/mrebbert/hawahooligan/issues?q=is%3Aissue) and [pull requests](https://github.com/mrebbert/hawahooligan/pulls) first to avoid duplicates.
- Skim the README's [Troubleshooting / FAQ](https://github.com/mrebbert/hawahooligan#troubleshooting--faq) before filing — most upgrade-state, cache, and rate-limit scenarios are already documented.

## What's in scope, what isn't

HAWahooligan is an **unofficial integration** built on top of the [Wahoo Cloud API](https://cloud-api.wahooligan.com/). The API is documented but enforces tight rate limits, especially on the Sandbox tier. That has consequences:

- **In scope:** anything the documented Wahoo Cloud API exposes — workout summaries, FIT downloads, power-zones, user profile. Sensor entities, services, dashboard UX, picker/viewer improvements, and bundled-viewer accessibility.
- **Out of scope:** Phase 5 write endpoints (`routes_write`, `plans_write`, `workout_file_uploads`) — explicitly deferred for now. If you have a strong use case, please open a Discussion before writing code.
- **Out of scope (other projects' problem):** Home Assistant core bugs, HACS bugs, Wahoo Cloud API bugs, Leaflet bugs, `fitdecode` bugs — report those upstream.

If you're unsure whether your idea fits, open a Discussion or a draft PR before sinking time into it.

## Local development setup

Requires **Python 3.13** (matches the Home Assistant runtime) and `git`.

```bash
git clone https://github.com/mrebbert/hawahooligan
cd hawahooligan

# Create a virtual environment and install both test tiers
python3.13 -m venv .venv
.venv/bin/pip install -e ".[test-integration]"

# Activate pre-commit hooks for automatic ruff lint/format on every commit
.venv/bin/pre-commit install

# Run the full test suite (Tier-1 + Tier-2)
.venv/bin/pytest tests -v
```

The `.venv/` directory is gitignored — it stays local.

### Running the linters and formatter

`ruff` is the single source of truth for lint and format; pre-commit runs it automatically against the version pinned in `.pre-commit-config.yaml`. To run manually:

```bash
.venv/bin/pre-commit run --all-files     # Recommended — matches CI exactly
.venv/bin/ruff check custom_components/ tests/
.venv/bin/ruff format custom_components/ tests/
```

Why `pre-commit run` over plain `ruff`? The pre-commit config pins a specific ruff version; CI uses the same. Calling `ruff` from a fresh `pip install` may format slightly differently and create churn.

## Testing

The suite is split into two tiers (see `tests/conftest.py` for the loader trick that keeps Tier-1 HA-free):

### Tier-1 — pure helpers, no Home Assistant required

```bash
.venv/bin/pip install -e ".[test]"        # lighter dependency set
.venv/bin/pytest tests/test_*.py -v       # everything outside tests/integration/
```

Tier-1 covers the pure-Python modules: `fit.py`, `totals.py`, `power_zones.py`, `rate_limit.py`, `manifest.py`. They run in milliseconds and don't need HA installed.

### Tier-2 — real Home Assistant, mocked Wahoo API

```bash
.venv/bin/pip install -e ".[test-integration]"
.venv/bin/pytest tests/integration -v
```

Tier-2 loads a real Home Assistant instance via `pytest-homeassistant-custom-component`. It exercises the config flow, coordinators, services, sensor + select platforms, and the picker manifest end-to-end with the Wahoo API mocked. The dependency set is heavier (HA itself plus a numpy / sqlalchemy stack), so it's opt-in.

### What to test when you change something

- **Pure helpers** (e.g. anything in `manifest.py`, `totals.py`, `rate_limit.py`): add cases under `tests/test_<module>.py`.
- **Sensor / select / services behavior:** add cases under `tests/integration/test_<area>.py` with the Wahoo API mocked.
- **Dashboard YAML** changes that touch sensor IDs or attributes: the `tests/integration/test_dashboard_entity_ids.py` regression catches drift — make sure it still passes (or extend it).
- **Don't loosen existing tests just to make a change pass.** If a test in the way is wrong, fix it in a separate commit and explain why.

## Pull request workflow

1. **Branch from `main`**: `git checkout -b feat/some-short-name` (or `fix/...`, `docs/...`, `chore/...`, `test/...`, `refactor/...`).
2. **Keep PRs small.** One concern per PR — easier to review and revert if needed.
3. **Run pre-commit + pytest locally** before pushing. CI runs the same checks.
4. **Update the docs** if you change user-visible behaviour: `README.md`, `dashboard/dashboard.yaml`, and the dashboard README.
5. **Don't bump the version in `manifest.json`** unless the PR is itself a release prep — the maintainer handles versioning at release time.
6. **Open the PR** against `main`. The repo runs three checks automatically: `Validate` (HACS + hassfest), `Tests` (pytest + ruff via pre-commit), and `CodeQL` (security and code-quality). All three should pass before merge.

## Translations

The integration ships English (`translations/en.json`) and German (`translations/de.json`); `strings.json` mirrors `en.json` for the config-flow UI. When you add a new entity, service, or config-flow string:

1. Add the new key to `strings.json` (English is the primary file).
2. Mirror the key in `translations/en.json` and `translations/de.json`.
3. If your German is rough, mark the value as `<<TODO: de>>` and the maintainer (or another contributor) will polish it before merge.

The integration relies on `pre-commit` running `check json` to flag malformed translation files.

## Code style notes

- Python 3.13 syntax (`type` aliases, PEP 695 generics, `datetime.UTC`).
- Pure helpers stay HA-free: `manifest.py`, `totals.py`, `power_zones.py`, `rate_limit.py`, `fit.py`. They are the only easily-Tier-1-testable surface — don't import `homeassistant.*` into them.
- All blocking I/O (file writes, FIT parsing) goes through `hass.async_add_executor_job`. The coordinator's `_manifest_lock` serializes the picker manifest's read-modify-write across the regular poll, full-backfill, and cleanup paths — please don't add a fourth writer without holding it.
- New sensor entities follow the description-based pattern (`SUMMARY_SENSORS`, `LIFETIME_SENSORS`, the `_WahooDescriptionEntity` base). New services follow the schema-validated handler shape in `services.py`.
- Bail-out logic against Wahoo's rate limits goes through `ConsecutiveLimitGuard` (one place, two callers — keep it that way).

## Releases

Releases are cut by the maintainer. There's no obligation for contributors to bump versions or tag — just open a clean PR; the manifest bump and release notes happen at merge / release time. Release notes live on GitHub (no `CHANGELOG.md` file).

## License

By contributing you agree that your contribution will be licensed under the [MIT License](LICENSE) of this repository.
