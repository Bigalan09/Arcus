-- Admin-managed slug blocklist.
CREATE TABLE IF NOT EXISTS blocklist (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    word       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_blocklist_word ON blocklist (word);
