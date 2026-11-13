# Sanity Integration

This document describes how the employee portal (Django, Postgres) connects to the company website's content store (Sanity). It covers ownership of each field, data flow, configuration, failure handling, the daily job, and the build order.

---

## 1. Purpose

Everything shown on the public employee page (`www.<domain>/<employee-slug>`) is stored in Sanity and rendered by the website. Employees and HR manage most of this content through the portal, so the portal must keep Sanity up to date. IT can edit content directly in Sanity Studio, so the integration also has to handle changes made there.

## 2. Systems and responsibilities

| System | Used by | Reads | Writes |
|---|---|---|---|
| Employee portal (Django + Postgres) | HR, employees | Postgres only | Postgres, and Sanity (push) |
| Sanity | Website, IT (Studio) | Sanity only (website) | Sanity (Studio, portal push, photo assets) |
| Public website | Visitors | Sanity only | Nothing |

Rules:

- The **website reads only Sanity**.
- The **portal reads only Postgres**. It never reads Sanity to display data, except to verify the outcome of a push.
- Postgres is the **source of truth for every employee field except the photo**.

## 3. Ownership of fields

| Field | Sanity field | Edited by | Source of truth | Flow |
|---|---|---|---|---|
| Name | `name` | HR | Postgres | Pushed immediately |
| Job title | `role` | HR | Postgres | Pushed immediately |
| Department | `department` | HR | Postgres | Pushed immediately |
| Office location | (see section 12, open items) | HR | Postgres | Pushed immediately |
| Primary email | `email` | HR | Postgres | Pushed immediately |
| Show on website | `showOnWebsite` | HR | Postgres | Pushed immediately |
| Phone | (see section 12) | Employee and HR | Postgres | Pushed immediately |
| Other emails | (see section 12) | Employee and HR | Postgres | Pushed immediately |
| LinkedIn | `linkedinUrl` | Employee and HR | Postgres | Pushed immediately |
| Bio (short) | `bio` | Employee and HR | Postgres | Pushed immediately |
| Full profile | `profile` | Employee and HR | Postgres | Pushed immediately |
| Project links | `project.teamMembers` | Employee and HR | Postgres | Pushed immediately |
| Photo | `image` (asset) | Employee and HR | Sanity asset; Postgres stores the URI | Uploaded to Sanity immediately; URI saved in Postgres |
| Portal ID | `externalId` | System | Postgres `User.id` | Set once, read-only in Studio |

Access rights (administrator, VPN, disabled) are never published to Sanity.

## 4. Data model changes in the portal

Added to the employee record (`User` or its profile):

| Column | Type | Purpose |
|---|---|---|
| `sanity_id` | string, nullable, unique | The Sanity `teamMember` document `_id` for this employee |
| `sanity_pending` | boolean, default false | True while the last change has not reached Sanity |
| `sanity_last_error` | text, nullable | Last push error, shown to HR |
| `sanity_synced_at` | datetime, nullable | Time of the last successful push |
| `photo_uri` | string, nullable | Sanity asset URI for the photo |

Other employee-facing fields that must exist in Postgres:

- `other_emails` (list of strings)
- `linkedin_url` (https only, must be on linkedin.com)
- `bio`, `profile_text`
- `project_ids` (links to Sanity `project` documents, see section 8)

Optional: a `sanity_sync_log` table to store the result of each daily run.

Existing fields:

- `photo_url` (data URL) is a fallback until photos are migrated to Sanity. It is removed after migration.

## 5. Immediate push: portal to Sanity

Triggered on every save that changes a Sanity-mapped field.

Steps:

1. The save is validated and written to Postgres in one transaction.
2. The changed fields are sent to Sanity as a `createIfNotExists` plus `patch` mutation on the `teamMember` document `sanity_id`. If `sanity_id` is empty, a document is created with `externalId` set to the Postgres user id.
3. On success: `sanity_pending = false`, `sanity_synced_at = now`, `sanity_last_error = null`.
4. On failure: `sanity_pending = true`, `sanity_last_error` is set, and a retry is scheduled.

Photo upload (separate step, same save):

1. The uploaded image is validated on the server (type, size, dimensions).
2. It is uploaded through the Sanity assets API.
3. The returned asset reference is patched onto `image`, and the asset URI is stored in `photo_uri`.
4. Only the URI is kept in Postgres. The binary is not stored in the database.

Save behaviour:

- The Postgres save always succeeds if validation passes, even when Sanity is unreachable.
- HR and the employee see the status "Not yet live on the website" while `sanity_pending` is true.

## 6. Retry policy

- Retries use exponential backoff: 1 min, 5 min, 15 min, 1 h, then every 6 h.
- A retry job runs every 5 minutes and picks up rows where `sanity_pending = true`.
- After 20 failed attempts, the row stays pending and HR is notified in the daily summary.
- Retries are idempotent: the full set of current portal values is sent, so repeated pushes are harmless.

## 7. Daily sync: Sanity to portal (overwrite and report)

Runs once a day at the time set in `SANITY_SYNC_TIME`. It is a management command, `sanity_daily_sync`, started by cron or a scheduler.

For each `teamMember` in Sanity matched to a portal user via `sanity_id` or `externalId`:

1. Compare each portal-owned field with the Sanity value.
2. If they differ, the portal value is pushed back to Sanity (overwrite). The Sanity value that was replaced is recorded.
3. Refresh `photo_uri` from Sanity, so a Studio photo change is reflected in the portal.
4. Write an audit entry for each overwrite: user, field, Sanity value replaced, portal value restored, time.

For each `teamMember` in Sanity with no matching portal user:

- Report it. Do not delete it. IT or HR decides what to do.

For each portal user with no `sanity_id` after the initial import:

- Create the Sanity document, then set `sanity_id`.

After the run, a summary is sent to HR and IT:

- records checked
- overwrites (field and person)
- photo URIs refreshed
- pending pushes still outstanding
- errors

## 8. Project links

- Project links are stored in Postgres as a list of Sanity `project` document ids (`project_ids`).
- The portal shows the employee the projects they can choose from. The list is cached from Sanity by the daily job, read-only for the portal.
- Changes made in the portal are pushed to Sanity immediately by writing `teamMembers` references on the relevant `project` documents.

Note: this makes the portal a writer of `project` documents. IT must agree before go-live (see section 12).

## 9. Studio rules (IT)

- Portal-owned fields may be edited in Studio, but edits are overwritten on the next push or daily run and reported.
- Recommended: mark portal-owned fields read-only in Studio so overwrites become exceptions.
- `externalId` and `sanity_id` must be read-only.
- Do not create `teamMember` documents by hand. Use the portal, or the initial import, so `externalId` is always set.
- Do not delete `teamMember` documents. Set `showOnWebsite` to false instead, because projects reference them.

## 10. Initial import (one-off)

1. IT exports current `teamMember` documents.
2. HR confirms which of them are current employees.
3. The import matches Sanity documents to portal users by email (case-insensitive).
4. Matches get `sanity_id` set and `externalId` written to Sanity.
5. Unmatched Sanity documents are listed for HR and IT review and are not changed.
6. Portal users with no match get a new Sanity document.

The import runs as a management command, `sanity_initial_import`, with a dry-run mode that prints the plan without writing.

## 11. Leavers and visibility

- When an employee is disabled in the portal, `showOnWebsite` is set to false in Sanity immediately, in the same operation.
- Disabling does not delete the Sanity document, so project history stays intact.
- Re-enabling does not turn visibility back on. HR sets `showOnWebsite` again.
- Deleting an employee in the portal sets `showOnWebsite` to false. The Sanity document is kept and marked with `externalId` of the removed user. It is not removed automatically.

## 12. Open items

These need a decision before go-live:

1. **Phone and other emails in Sanity.** The current `teamMember` schema has no field for them. Either add fields, or keep them portal-only. Phone is currently pushed in the agreed model; confirm whether it should appear on the website at all.
2. **Office location.** The schema has no field for it. Confirm whether it is added to Sanity.
3. **Project links ownership.** Writing `project.teamMembers` from the portal means IT grants the portal write access to `project` documents. Confirm, or fall back to read-only project links in the portal.
4. **Consent.** The schema says visibility must only be ticked for people who have agreed. Decide whether the portal stores a consent date that must be set before `showOnWebsite` can be turned on.
5. **Sanity token scope.** Confirm a write-only token for the portal, limited to `teamMember` and `project` if Sanity allows it.

## 13. Configuration

Add to `.env`: