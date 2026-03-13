-- Arcus migration 007: add webhook reference tag

ALTER TABLE webhooks
ADD COLUMN IF NOT EXISTS reference TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_webhooks_user_reference_unique
ON webhooks (user_id, reference);
