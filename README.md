# Skedaddle

## Aseptic Rotating Management System

## Repository

To access the repository please click this [link](https://github.com/FraserR1188/Skedaddle)

# Table of Contents

## Overview

Skedaddle is an internal rota and validation management system designed for the
Medicines Manufacturing Centre (MMC) which is an aseptic manufacturing
environment/facility.

The platform provides a visual structure for AM/PM shift allocation, isolator
assignment control, operator validation tracking and controlled publication workflows
to support a compliant, efficient rota management within a regulated healthcare
setting.

The system enforces business rules aligned with operational constraints in
cleanroom and isolator-based production areas.

## Purpose

Skedaddle replaces manual rota spreadsheets with a structured, rule-driven system
that:

- Visually appealing (easier to read than an Excel spreadsheet)
- Prevents invalid operator allocations
- Enforces AM/PM shift uniqueness
- Tracks validation eligibility per operator
- Provides audit traceability for rota changes
- Supports publish/republish workflow with notifications
- Enables operator to quick search their assignments for the week
- Operators can request shift swap with their rota manager

This system is designed with future scalability toward broader production
management tooling.

## Core Features

Rota Management

- Daily and Monthly rota views
- AM / PM shift separation
- Crew-based operator selection
- Supervisor allocation (AM/PM specific)
- Assignment uniqueness rules

Isolator Controls

- Operator limits per isolator
- Planned downtime RAG (Red/Amber/Green) system
- Room vs Isolator Assignment separation

Validation Module

- Operator validation to enable production in isolators which carry out that
  procedure.
- Validation count (0/3)
- Quick update modal workflow
- Enforced eligibility rules for assignment

Publication Workflow

- Draft and published rota states
- Republish functionality with comments
- Email notification system
- Per-day audit trail of changes

Access Control

- Role-Based permissions:
  - Superuser
  - Rota Manager
  - Rota Viewer
- Controlled validation updates

## User Stories

### Rota Manager

The Rota Manager is responsible for building, validating, and publishing the rota for
the aseptic suite. They must ensure operational coverage, enforce business rules,
and prevent invalid allocations. They are time-pressured and accountable for staffing
compliance.

As a Rota Manager, I want to assign operators and supervisors to AM/PM shifts with
enforced business rules, so that I can confidently publish a rota that is operationally
safe and compliant.

Acceptance Criteria:

- The system must clearly separate AM and PM shifts.
- An operator cannot be assigned to more than one area within the same time block.
- Supervisors can be assigned to either room level supervisory role or manufacturing.
- Isolator assignments must require isolator selection.
- Capacity limits per isolator must be enforced.
- Validation eligibility must be checked before assignment.
- Validation errors must be clear and readable.
- Publish button only appears if rota passes all validation checks.
- A full audit trail logs all changes before publication.

Edge Cases / Constraints

- Attempting to assign the same operator twice in AM.
- Assigning an operator who lacks isolator validation.
- Exceeding isolator capacity.
- Editing a rota after publication (must trigger republish flow).

### Rota User (Computer Literate)

An experienced operator who is comfortable using digital systems. They regularly
check schedules online and expect efficiency.

As an Operator, who is digitally confident, I want to quickly view my assigned shifts
and isolator allocations.

Acceptance Criteria:

- User can log in securely
- Dashboard clearly displays:
  - Assigned date.
  - AN/PM shifts.
  - Location (Room / Isolator)
- Validation status is visible
- Navigation is minimal and initutive
- Page loads quickly.
- System is mobile-repsonsive

Edge Cases / Constraints

- Use should not see other operators private data throughout the site.
- Only the newest draft should be visible.

### Rota User (Computer Ill-Literate / Low Confidence)

An operator with low digital literacy. May struggle with complex navigation,
dropdowns or cluttered interfaces. Needs clarity and reassurance.

This persona is useful to accommodate as it is critical in healthcare environments.

As an operator with low digital confidence, I want a very clear and simple way to see
where I am working so that I do not feel confused or anxious about the system.

Acceptance Criteria:

- Interface must see:
  - Large readable text (or have an option to increase text size for that user).
  - Clear labels (AM Shift / PM Shift)
  - Minimal technical terminology
- Only essential information shown on dashboard.
- No nested navigation required to see assignment.
- Colour coding must be meaningful but not the only indicator (accessibility).
- System must avoid ambiguous abbreviations.
- Error message must be written in plain language.

Edge Cases / Constraints

- User forgets password – clear reset flow.
- User accesses on older device – UI must still respond correctly.
- No hidden logic that requires advanced understanding.

### Senior Level Manager (Operational Oversight)

Senior manager overseeing production output, compliance, and staffing risk.
Interested in operational visibility, compliance assurance and high-level reporting.
They do not build the rota but need to have confidence in it.

As Senior Management, I want visibility of rota coverage, validation status, and
staffing risks, so that I can ensure operational continuity and regulatory compliance.

Acceptance Criteria:

- Manager can view monthly rota overview.
- RAG (Red/Amber/Green) isolator status visible.
- Validation coverage summary available.
- Supervisor coverage clearly indicated.
- Audit trail accessible for review.
- Published vs draft clearly differentiated.
- No editing capability (view-only mode).

Edge Cases / Constraints

- Sudden staff shortage – easy identification of gaps.
- High validation expiry – visible risk indicator.
- Compliance review which would require export capability.
