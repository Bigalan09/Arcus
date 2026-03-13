-- Migration 004: Add webhooks table for event-driven notifications.
--
-- Webhooks are used to notify external services when events occur (e.g. a user
-- requests credits).  Only admins may manage webhooks via the API.

CREATE TABLE webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url TEXT NOT NULL,
    secret TEXT,
    events TEXT NOT NULL DEFAULT 'credit.request',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_webhooks_active ON webhooks (active);
