-- StreamGenie — "Not Interested" dismissals for the discovery carousels.
-- Run once in the streamgenie2 Supabase SQL Editor. Idempotent / safe to re-run.

CREATE TABLE IF NOT EXISTS dismissed_shows (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tmdb_id INTEGER NOT NULL,
    dismissed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, tmdb_id)
);

CREATE INDEX IF NOT EXISTS idx_dismissed_user ON dismissed_shows(user_id);

ALTER TABLE dismissed_shows ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users view own dismissed"   ON dismissed_shows;
DROP POLICY IF EXISTS "Users insert own dismissed" ON dismissed_shows;
DROP POLICY IF EXISTS "Users delete own dismissed" ON dismissed_shows;

CREATE POLICY "Users view own dismissed"
    ON dismissed_shows FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own dismissed"
    ON dismissed_shows FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users delete own dismissed"
    ON dismissed_shows FOR DELETE USING (auth.uid() = user_id);
