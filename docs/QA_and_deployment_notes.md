# QA & Deployment Notes

Quick QA checklist
- Run test suite: `python manage.py test` (all tests passed locally).
- Smoke-test UI: start dev server `python manage.py runserver` and verify suite overview, daily rota, and work-area pages render.
- Permissions: verify users with `rota_manager` can POST to `daily_rota`, `rota_viewer` can view but cannot edit.
- Assignment rules: attempt invalid assignments (e.g., non-supervisor to room) to confirm validation messages.

Deployment checklist
- Ensure migrations are applied: `python manage.py migrate`.
- Collect static assets: `python manage.py collectstatic --noinput`.
- Restart application server / uwsgi/gunicorn after deploy.
- Tag release with branch name and changelog entry.

Rollback guidance
- If unexpected validation changes occur, revert to previous release and inspect `Assignment.clean` and recent templates affecting form submission.
