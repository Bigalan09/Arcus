# Origin Health Visibility Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and expose last-known origin health snapshots so Arcus users can see whether a configured origin is reachable.

**Architecture:** Add health snapshot fields to `Subdomain`, implement a small origin probe helper that tests plain HTTP reachability, refresh the snapshot when origins are saved or manually checked, and expose the result consistently through the existing subdomain API and dashboard. Keep the feature request-scoped only; no background polling.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Jinja2, vanilla JavaScript, pytest

---

## Chunk 1: Tests First

### Task 1: Add failing tests for origin health snapshots

**Files:**
- Modify: `api/tests/test_subdomains.py`
- Create: `api/tests/test_origin_checks.py`

- [ ] **Step 1: Write failing probe helper tests**

Add tests that prove:

- a successful HTTP probe returns a healthy snapshot with status code and latency
- a connection failure returns an unreachable snapshot with an error message

- [ ] **Step 2: Run the new helper tests to verify they fail**

Run: `source venv/bin/activate && pytest api/tests/test_origin_checks.py -v`

Expected: fail because the probe helper does not exist yet.

- [ ] **Step 3: Write failing route tests for origin save and manual re-check**

Add tests that prove:

- saving an origin stores health fields in the response
- a failed probe still returns `200` and persists an unreachable status
- manual re-check refreshes the snapshot
- manual re-check without a saved origin returns `409`

- [ ] **Step 4: Run the targeted route tests to verify they fail**

Run: `source venv/bin/activate && pytest api/tests/test_subdomains.py -v`

Expected: the new route tests fail because the API does not yet expose or update health snapshots.

## Chunk 2: Persistence And Probe Logic

### Task 2: Add subdomain health fields and probe helper

**Files:**
- Modify: `api/models.py`
- Modify: `api/schemas.py`
- Create: `api/utils/origin_health.py`
- Add: `db/migrations/009_add_origin_health_to_subdomains.sql`

- [ ] **Step 1: Add the new `Subdomain` columns and response fields**

Persist the last-known health snapshot on subdomains and expose the fields on `SubdomainResponse`.

- [ ] **Step 2: Implement the probe helper**

Create a small helper that performs an HTTP GET to `http://host:port/`, measures latency, and returns a structured snapshot.

- [ ] **Step 3: Run helper-focused tests**

Run: `source venv/bin/activate && pytest api/tests/test_origin_checks.py -v`

Expected: helper tests pass while route tests still fail.

## Chunk 3: Route Integration

### Task 3: Refresh origin health on save and manual check

**Files:**
- Modify: `api/routes/subdomains.py`

- [ ] **Step 1: Update `POST /subdomains/{slug}/origin`**

After validating and saving the origin, run the probe and persist the resulting snapshot before returning the subdomain.

- [ ] **Step 2: Add `POST /subdomains/{slug}/origin/check`**

Require ownership or admin access, return `409` when no origin is configured, otherwise refresh the stored snapshot and return the updated subdomain.

- [ ] **Step 3: Run the targeted route tests**

Run: `source venv/bin/activate && pytest api/tests/test_subdomains.py api/tests/test_origin_checks.py -v`

Expected: route and helper tests pass.

## Chunk 4: Dashboard Exposure

### Task 4: Show health state in the dashboard and add a manual check action

**Files:**
- Modify: `api/templates/dashboard.html`

- [ ] **Step 1: Render origin health summary in the subdomain list**

Show `Healthy`, `Unreachable`, or `Unknown` based on the response fields.

- [ ] **Step 2: Add a `Check origin` action**

Wire the button to the new API endpoint and refresh the subdomain list on success.

- [ ] **Step 3: Run focused regression tests**

Run: `source venv/bin/activate && pytest api/tests/test_subdomains.py api/tests/test_frontend_admin_access.py -v`

Expected: targeted tests remain green.

## Chunk 5: Final Verification

### Task 5: Verify the full change

**Files:**
- No new files

- [ ] **Step 1: Run the targeted regression suite**

Run: `source venv/bin/activate && pytest api/tests/test_origin_checks.py api/tests/test_subdomains.py -v`

Expected: all targeted tests pass.

- [ ] **Step 2: Run the full suite**

Run: `source venv/bin/activate && pytest`

Expected: full suite passes.

- [ ] **Step 3: Review the diff before commit**

Run: `git status --short && git diff --stat`

Expected: only the intended feature files are changed.
