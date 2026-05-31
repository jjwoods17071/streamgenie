-- StreamGenie — watched-episode tracking (#1)
-- Run once in the streamgenie2 Supabase SQL Editor. Idempotent / safe to re-run.

CREATE TABLE IF NOT EXISTS watched_episodes (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tmdb_id INTEGER NOT NULL,
    season_number INTEGER NOT NULL,
    episode_number INTEGER NOT NULL,
    watched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, tmdb_id, season_number, episode_number)
);

CREATE INDEX IF NOT EXISTS idx_watched_user_show ON watched_episodes(user_id, tmdb_id);

ALTER TABLE watched_episodes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users view own watched"   ON watched_episodes;
DROP POLICY IF EXISTS "Users insert own watched" ON watched_episodes;
DROP POLICY IF EXISTS "Users delete own watched" ON watched_episodes;

CREATE POLICY "Users view own watched"
    ON watched_episodes FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users insert own watched"
    ON watched_episodes FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users delete own watched"
    ON watched_episodes FOR DELETE USING (auth.uid() = user_id);
