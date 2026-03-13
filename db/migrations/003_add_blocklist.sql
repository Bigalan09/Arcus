-- Admin-managed slug blacklist.
CREATE TABLE IF NOT EXISTS blacklist (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    word       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_blacklist_word ON blacklist (word);
