# Skedaddle coding instructions

This is a Django rota management system for an aseptic manufacturing suite.

Priorities:

- Preserve audit trail behaviour.
- Preserve rota_manager / rota_viewer permissions.
- Preserve AM/PM shift_block conflict rules.
- Do not move business rules into templates or frontend code.
- Keep Assignment.clean() as the backend source of truth.
- Do not remove existing models without explicit approval.
- Prefer small, reviewable changes.
- Before large refactors, produce a plan first.
- Run python manage.py check after changes.
- Add or update tests where practical.
