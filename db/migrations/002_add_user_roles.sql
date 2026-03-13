-- Add role column to users.
-- Roles: normal (default), pro, admin.
-- Only one admin is permitted at a time (enforced at application level).
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'normal'
        CHECK (role IN ('admin', 'pro', 'normal'));
