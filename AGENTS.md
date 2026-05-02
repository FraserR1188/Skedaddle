# Skedaddle coding instructions

Skedaddle is a Django rota management system for an NHS aseptic suite.

Development priorities:

- Preserve audit trail behaviour.
- Preserve rota_manager and rota_viewer permissions.
- Preserve AM/PM shift_block conflict rules.
- Keep Assignment.clean() as the backend source of truth.
- Do not move business rules into templates or frontend code.
- Do not remove existing models without explicit approval.
- Prefer small, reviewable changes.
- Add or update tests where practical.
- Run python manage.py check after changes.
- For larger changes, produce a plan before implementation.

Regulated environment expectations:

- Changes should be traceable.
- Avoid broad unreviewed refactors.
- Keep commits logical and descriptive.
- Summarise risks and assumptions after each task.
