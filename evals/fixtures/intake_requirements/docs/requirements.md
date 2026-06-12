# Requirements — Reminders Module

## Executive Summary
A reminders module lets users schedule, list, and dismiss time-based reminders.

## Target Users
Individuals tracking recurring personal tasks who want lightweight notifications.

## Problem Statement
Users miss recurring tasks because the app has no scheduling or notification surface.

## Feature Specifications
- Create a reminder with a title, due time, and optional repeat rule.
- List upcoming and past reminders.
- Dismiss or snooze an active reminder.

## User Stories
- As a user, I can create a reminder so that I am notified at the right time.
- As a user, I can list my reminders so that I can review what is due.
- As a user, I can dismiss a reminder so that it stops notifying me.

## API Contract
- `POST /reminders` — create a reminder.
- `GET /reminders` — list reminders.
- `DELETE /reminders/{id}` — dismiss a reminder.

## Non-Functional Requirements
- p95 list latency < 200ms for 1k reminders per user.
- Reminders survive process restart (persisted).

## Out of Scope
- Push-notification delivery infrastructure.
- Cross-device sync.
