-- StreamGenie — per-user "hide this genre from Discover" filters.
-- Opt-in per user (Kids / Reality / Anime), so people who like these still see them.
-- Idempotent / safe to re-run.
--
-- Run at: https://supabase.com/dashboard/project/mqiulsjmizygkaompypu/sql/new

CREATE TABLE IF NOT EXISTS genre_excludes (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    genre_key TEXT NOT NULL,                 -- 'kids' | 'reality' | 'anime'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, genre_key)
);

CREATE INDEX IF NOT EXISTS idx_genre_excludes_user ON genre_excludes(user_id);

ALTER TABLE genre_excludes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users view own genre excludes"   ON genre_excludes;
DROP POLICY IF EXISTS "Users insert own genre excludes" ON genre_excludes;
DROP POLICY IF EXISTS "Users delete own genre excludes" ON genre_excludes;

CREATE POLICY "Users view own genre excludes"
    ON genre_excludes FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own genre excludes"
    ON genre_excludes FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users delete own genre excludes"
    ON genre_excludes FOR DELETE USING (auth.uid() = user_id);
