<!--
Thanks for sending a PR! A few notes that save round-trips:

- Single-maintainer project; tone is friendly but the bar for merging
  is: must pass CI, must come with tests, must keep the README + dashboard
  YAML in sync if behavior changes.
- New / changed user-visible behavior bumps the manifest version. Pure
  internal refactors don't.
- Phase 5 (write endpoints — routes / plans / uploads) is explicitly
  deferred — please open a discussion first before sinking time into
  a PR for it.
-->

## Summary

<!-- 1-3 sentences. What does this PR do and why? Link related issues. -->

Closes #

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing
      behavior to change — entity IDs, service signatures, etc.)
- [ ] Documentation only
- [ ] Internal refactor / test infra (no user-visible change)

## Test coverage

<!--
What did you add to `tests/` to lock this down? "Existing tests
already cover it" is a fine answer for trivial refactors; for
user-visible changes please add at least one regression test that
would have caught the bug before the fix.
-->

- [ ] New tests added (`tests/test_*.py` or `tests/integration/test_*.py`)
- [ ] Existing tests cover the change
- [ ] No tests needed (docs / config only — explain why below)

## Checklist

- [ ] `.venv/bin/pre-commit run --all-files` is green locally.
- [ ] `.venv/bin/pytest tests` is green locally.
- [ ] README updated for any user-visible change (sensors, services,
      dashboard YAML, troubleshooting cases).
- [ ] If the manifest version bumps, the commit message states it
      explicitly and the GitHub release notes are drafted.
- [ ] Translations updated in **both** `en.json` and `de.json` if any
      entity name / service description changed (or noted as
      "translator help wanted").

## Notes for reviewer

<!--
Anything I should pay particular attention to? Tradeoffs you considered?
Concerns about backwards compatibility? Free-form — this is the
"what's worth saying out loud" box.
-->
