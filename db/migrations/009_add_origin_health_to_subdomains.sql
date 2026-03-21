-- Migration 009: add persisted origin health snapshots to subdomains.

ALTER TABLE subdomains
ADD COLUMN IF NOT EXISTS origin_health_status TEXT NOT NULL DEFAULT 'unknown';

ALTER TABLE subdomains
ADD COLUMN IF NOT EXISTS origin_health_checked_at TIMESTAMPTZ;

ALTER TABLE subdomains
ADD COLUMN IF NOT EXISTS origin_health_status_code INTEGER;

ALTER TABLE subdomains
ADD COLUMN IF NOT EXISTS origin_health_latency_ms INTEGER;

ALTER TABLE subdomains
ADD COLUMN IF NOT EXISTS origin_health_error TEXT;

UPDATE subdomains
SET origin_health_status = 'unknown'
WHERE origin_health_status IS NULL;
