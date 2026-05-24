# Changelog

## Unreleased (codex/compact-assignment-suite-ui) - 2026-05-24

- Implement compact suite UI improvements (frontend changes on branch).
- Preserved backend assignment validation rules in `Assignment.clean` (room, isolator, work-area rules, APS validation, isolator operator cap).
- Added permissions audit: `docs/permissions_audit.md`.
- Added tests:
  - Permission-related tests for `daily_rota` (anonymous redirect and superuser POST).
  - Existing workflow tests remain passing (9 existing tests + new ones).

Notes:

- Migrations unchanged; run `python manage.py migrate` after deployment.
