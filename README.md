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
