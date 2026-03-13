# Admin Subdomain Filter Bypass Toggle Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-only dashboard toggle that bypasses slug content filters during availability checks and subdomain purchase when explicitly enabled.

**Architecture:** Keep the backend as the source of truth by extending the shared slug assessment path with an explicit content-filter bypass flag. Thread that flag through the existing dashboard availability and purchase flow, and reject any non-admin attempt to use it.

**Tech Stack:** FastAPI, Pydantic, Jinja2, vanilla JavaScript, pytest

---

## Chunk 1: Tests First

### Task 1: Add API tests for the bypass flag

**Files:**
- Modify: `api/tests/test_profanity.py`
- Modify: `api/tests/test_subdomain_check.py`
- Modify: `api/tests/test_subdomains.py`

- [ ] **Step 1: Write the failing check-endpoint tests**

Add tests that prove:

- an admin can check a profanity/blocklisted slug with `ignore_content_filters=true` and get `available=True` when nothing else blocks it
- a normal user gets `403` if they send `ignore_content_filters=true`

- [ ] **Step 2: Run the targeted check-endpoint tests to verify they fail**

Run: `venv/bin/python -m pytest api/tests/test_profanity.py api/tests/test_subdomain_check.py -v`

Expected: new bypass tests fail because the API does not support or enforce the flag yet.

- [ ] **Step 3: Write the failing purchase-path tests**

Add tests that prove:

- an admin can purchase a profanity/blocklisted slug with `ignore_content_filters=true`
- a normal user gets `403` if they attempt to purchase with `ignore_content_filters=true`

- [ ] **Step 4: Run the targeted purchase tests to verify they fail**

Run: `venv/bin/python -m pytest api/tests/test_subdomains.py api/tests/test_profanity.py -v`

Expected: new bypass purchase tests fail.

### Task 2: Add frontend rendering tests for the toggle

**Files:**
- Modify: `api/tests/test_frontend_admin_access.py`

- [ ] **Step 1: Write the failing dashboard rendering tests**

Add tests that prove:

- an admin dashboard response includes the bypass toggle copy/field
- a normal-user dashboard response does not include it

- [ ] **Step 2: Run the targeted frontend tests to verify they fail**

Run: `venv/bin/python -m pytest api/tests/test_frontend_admin_access.py -v`

Expected: the new dashboard assertions fail because the toggle is not rendered.

## Chunk 2: Backend

### Task 3: Extend the API schema and slug policy

**Files:**
- Modify: `api/schemas.py`
- Modify: `api/utils/slug_policy.py`

- [ ] **Step 1: Add the bypass field to request models**

Add `ignore_content_filters: bool = False` to the purchase schema, and allow the check endpoint to accept the same query flag.

- [ ] **Step 2: Extend slug assessment with a bypass option**

Update `assess_slug(...)` so it can skip only the built-in profanity and blocklist checks while keeping all other validation intact.

- [ ] **Step 3: Run targeted tests**

Run: `venv/bin/python -m pytest api/tests/test_profanity.py api/tests/test_subdomain_check.py api/tests/test_subdomains.py -v`

Expected: some tests still fail until route enforcement is added.

### Task 4: Enforce admin-only use in routes

**Files:**
- Modify: `api/routes/subdomains.py`

- [ ] **Step 1: Gate the bypass flag on the check endpoint**

When `ignore_content_filters=true`, require an authenticated admin. Otherwise keep the endpoint public.

- [ ] **Step 2: Gate the bypass flag on the purchase endpoint**

Reject any non-admin caller that sends the bypass flag.

- [ ] **Step 3: Thread the flag into slug assessment**

Pass the flag through both the availability and purchase paths.

- [ ] **Step 4: Run the targeted API tests**

Run: `venv/bin/python -m pytest api/tests/test_profanity.py api/tests/test_subdomain_check.py api/tests/test_subdomains.py -v`

Expected: all new API bypass tests pass.

## Chunk 3: Dashboard UI

### Task 5: Add the admin-only toggle to the dashboard

**Files:**
- Modify: `api/templates/dashboard.html`

- [ ] **Step 1: Render the admin-only toggle and helper copy**

Add a warning-toned toggle inside the subdomain creation form, visible only to admins.

- [ ] **Step 2: Update the dashboard JavaScript**

Make the form:

- reset the toggle when hidden
- include the flag in slug checks when enabled
- include the flag in purchase requests when enabled

- [ ] **Step 3: Run the dashboard-focused tests**

Run: `venv/bin/python -m pytest api/tests/test_frontend_admin_access.py -v`

Expected: the new admin/non-admin dashboard assertions pass.

## Chunk 4: Final Verification

### Task 6: Verify end-to-end behaviour

**Files:**
- No new files

- [ ] **Step 1: Run the targeted regression suite**

Run: `venv/bin/python -m pytest api/tests/test_profanity.py api/tests/test_subdomain_check.py api/tests/test_subdomains.py api/tests/test_frontend_admin_access.py -v`

Expected: all targeted tests pass.

- [ ] **Step 2: Run the full suite**

Run: `venv/bin/python -m pytest`

Expected: full suite passes.

- [ ] **Step 3: Rebuild the local docker stack from the feature worktree**

Run: `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build`

Expected: rebuild completes successfully.

- [ ] **Step 4: Verify runtime health**

Run:

- `docker compose -f docker-compose.yml -f docker-compose.local.yml ps`
- `curl -fsS http://localhost:8000/health`
- `curl -fsS http://localhost:8001/health`

Expected: API, router, and postgres are healthy; both health endpoints return `{"status":"ok"}`.
