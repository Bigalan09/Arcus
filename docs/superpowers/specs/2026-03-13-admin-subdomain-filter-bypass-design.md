# Admin Subdomain Filter Bypass Design

**Date:** 2026-03-13

## Goal

Add an admin-only toggle in the dashboard subdomain creation flow that can bypass both slug content filters:

- the built-in profanity filter
- the admin-managed blocklist

The bypass must only apply when an admin explicitly turns it on for that creation attempt. Normal and pro users must never be able to see or use it.

## Current Behaviour

- The dashboard subdomain form checks slug availability through `GET /subdomains/check`.
- Final creation goes through `POST /subdomains/purchase`.
- Both paths share `assess_slug(...)` in `api/utils/slug_policy.py`.
- `assess_slug(...)` blocks slugs that match:
  - the built-in profanity filter
  - the admin blocklist
- The dashboard UI has no way to override those checks for admins.

## Approved Approach

Use a single admin-only toggle in the existing dashboard subdomain form. Keep it off by default. When enabled:

- the availability check bypasses both content filters
- the purchase path bypasses both content filters
- all other checks still apply

The backend remains the source of truth. The UI sends an explicit bypass flag, but the API must reject that flag for any non-admin caller.

## Backend Design

### API contract

Add an optional `ignore_content_filters` boolean to:

- `SubdomainPurchase`
- `GET /subdomains/check`

Default is `False`.

### Enforcement

Only authenticated admins may use `ignore_content_filters=True`.

- `POST /subdomains/purchase` should return `403` if a non-admin sends the flag.
- `GET /subdomains/check` should also require admin authentication when the flag is enabled, and return `403` for non-admins.

The public availability endpoint stays public when the flag is absent or `False`.

### Slug assessment

Extend `assess_slug(...)` with an option that skips only the two content checks:

- built-in profanity
- blocklist

The following checks must remain unchanged:

- configured domain validation
- slug format
- reserved slug rejection
- taken slug detection

## Frontend Design

### Visibility

Render the toggle only when `user.role == "admin"`.

### Placement

Place it inside the existing subdomain creation card near the slug input and availability state, so the override is visible at the moment the admin is choosing the slug.

### Copy

Use warning-toned copy that is direct and unambiguous. The UI should make clear that enabling the toggle skips both the profanity filter and the blocklist for this creation flow.

### Behaviour

- Off by default when the form opens.
- Reset to off when the form closes.
- When enabled, include the bypass flag in both the slug check request and the purchase request.
- Availability text should still show the real API result for the chosen mode.

## Test Strategy

Add targeted tests for:

- admin availability checks with bypass enabled
- non-admin attempts to use bypass on the check endpoint
- admin purchases with bypass enabled
- non-admin attempts to use bypass on purchase
- dashboard rendering:
  - admin sees the toggle
  - non-admin does not

## Non-Goals

- No bypass for reserved slugs
- No bypass for invalid slug format
- No bypass for already-taken slugs
- No new admin page or separate workflow
