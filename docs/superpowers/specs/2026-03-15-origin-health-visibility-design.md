# Origin Health Visibility Design

**Date:** 2026-03-15

## Goal

Add lightweight origin health visibility to Arcus so trusted-circle users can tell whether a configured origin is actually reachable.

The feature should:

- probe an origin when it is saved
- store the last-known health snapshot on the subdomain
- allow a manual re-check through the API
- expose the snapshot in the API response and dashboard

This is meant to improve onboarding and operator visibility. It is not meant to turn Arcus into a full monitoring product.

## Current Behaviour

- Subdomains can be created and assigned an `origin_host` and `origin_port`.
- Origin validation only checks that the host is syntactically valid and not private in production mode.
- Arcus does not record whether the origin is reachable after configuration.
- The dashboard only shows `host:port` or `No origin configured`.
- A user can save a broken origin and gets no immediate structured feedback beyond validation errors.

## Approved Approach

Persist a small origin-health snapshot on each subdomain and refresh it whenever the origin is updated.

The snapshot should include:

- a status
- when the last probe ran
- the last HTTP status code, when a response exists
- the last error message, when the probe fails
- approximate latency in milliseconds

Also add a manual re-check endpoint so the dashboard and API clients can refresh the snapshot without changing the saved origin.

## Behaviour Design

### Probe semantics

Arcus should probe the same transport model the router already uses: plain HTTP to `http://origin_host:origin_port/`.

Treat the probe as healthy when Arcus successfully receives any HTTP response, including `2xx`, `3xx`, `4xx`, or `5xx`. The purpose is reachability, not application correctness.

Treat timeouts, DNS failures, and connection failures as unhealthy.

### Save behaviour

Saving an origin must not fail just because the probe fails. Rejecting saves would be hostile to legitimate cases where the service is still booting or temporarily offline.

Instead:

- validate the host as today
- save the origin
- run the probe
- store the health snapshot
- return the subdomain with the updated snapshot

### Manual re-check behaviour

Add a dedicated authenticated endpoint to re-check the saved origin for a subdomain.

- owners can re-check their own subdomains
- admins can re-check any subdomain
- return `409` if no origin has been configured yet

## Data Model

Add the following nullable columns to `subdomains`:

- `origin_health_status`
- `origin_health_checked_at`
- `origin_health_status_code`
- `origin_health_latency_ms`
- `origin_health_error`

Use a small text status set:

- `unknown`
- `healthy`
- `unreachable`

Newly purchased subdomains remain `unknown` until an origin is saved or checked.

## API Design

### `SubdomainResponse`

Extend the existing response model with the persisted health fields so list and mutation responses all expose the same shape.

### Manual check endpoint

Add:

`POST /subdomains/{slug}/origin/check`

Optional `domain` query parameter matches the existing origin-update route.

Response shape should be the same `SubdomainResponse` object after the health snapshot is refreshed.

## Dashboard Design

Keep the current subdomain list layout, but add a small origin-health line under the origin address.

Display:

- `Healthy` with latency and HTTP status when available
- `Unreachable` with the stored error when the probe fails
- `Unknown` when no probe has run yet

Add a `Check origin` action next to the existing origin controls.

## Testing Strategy

Add targeted tests for:

- the probe helper returning healthy and unreachable snapshots
- setting an origin persists a health snapshot
- failed probes do not block origin save
- manual re-check permissions
- manual re-check on subdomains without an origin returns `409`
- API responses include the new health fields

## Non-Goals

- no background scheduler or recurring health polling
- no alerting, notifications, or status pages
- no TLS probing of upstream origins
- no traffic analytics
