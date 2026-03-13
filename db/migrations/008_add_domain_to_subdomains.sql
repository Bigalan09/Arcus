-- Migration 008: add per-subdomain domain column for multi-domain support
--
-- Existing rows are assigned the default domain 'bigalan.dev'.  If your
-- deployment uses a different BASE_DOMAIN run the following after this
-- migration to update existing records:
--
--   UPDATE subdomains SET domain = 'your-base-domain.com';

-- Add the domain column (NOT NULL with a default for existing rows).
ALTER TABLE subdomains ADD COLUMN IF NOT EXISTS domain TEXT NOT NULL DEFAULT 'bigalan.dev';

-- Remove the previous unique constraint that covered only slug.
ALTER TABLE subdomains DROP CONSTRAINT IF EXISTS subdomains_slug_key;

-- The uniqueness constraint is now on the (slug, domain) pair so the same
-- slug can be purchased on different configured domains.
ALTER TABLE subdomains ADD CONSTRAINT uq_subdomains_slug_domain UNIQUE (slug, domain);

-- Index to speed up domain-filtered queries.
CREATE INDEX IF NOT EXISTS idx_subdomains_domain ON subdomains (domain);
