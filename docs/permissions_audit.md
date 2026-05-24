**Permissions Audit**

## Summary

- **Scope**: quick audit of `rota_manager` and `rota_viewer` permissions and where they are defined/used.
- **Outcome**: permissions are defined on `StaffMember` and are actively used in views, templates and tests. No immediate issues found.

## Findings

- **Defined:** custom permissions are declared on `StaffMember` in models: [rota/models.py](rota/models.py#L75).
- **Migration:** included in initial migration: [rota/migrations/0001_initial.py](rota/migrations/0001_initial.py#L69).
- **Helper:** `is_rota_manager` helper used by views to gate edits: [rota/views.py](rota/views.py#L41).
- **View restrictions:** many views require the permissions, e.g. validation views use `@permission_required('rota.rota_manager')`: [validation/views.py](validation/views.py#L22).
- **Template checks:** templates guard UI elements with `perms.rota.rota_viewer` / `perms.rota.rota_manager`, e.g. base and work-area templates: [rota/templates/rota/base.html](rota/templates/rota/base.html#L56), [rota/templates/rota/base.html](rota/templates/rota/base.html#L71), [rota/templates/rota/work_area_assignment.html](rota/templates/rota/work_area_assignment.html#L118).
- **Tests:** tests reference the permission codenames to set up users: [rota/tests.py](rota/tests.py#L17), [validation/tests.py](validation/tests.py#L13).

## Notes & Recommendations

- Keep `rota_manager` and `rota_viewer` present in `StaffMember` Meta (already done).
- When changing UI access, prefer view-level `@permission_required` or `is_rota_manager()` checks rather than relying solely on templates.
- Add a short test ensuring only users with `rota_manager` can POST edits to `daily_rota` (if not already present).
- Consider documenting role setup steps for Dev/Prod (how to grant `rota_manager` / `rota_viewer` to users) in the README or deployment notes.

## References

- `StaffMember` permissions: [rota/models.py](rota/models.py#L75)
- `is_rota_manager` helper: [rota/views.py](rota/views.py#L41)
- Example view protection: [validation/views.py](validation/views.py#L22)
- Template guards: [rota/templates/rota/base.html](rota/templates/rota/base.html#L56)
- Test usage: [rota/tests.py](rota/tests.py#L17)

Generated: automated quick-audit (May 24, 2026)
