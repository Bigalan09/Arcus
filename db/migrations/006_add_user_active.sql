-- Arcus migration 006: add user activation state

ALTER TABLE users
ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
