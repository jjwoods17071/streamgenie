-- Pin This: keep actively-watched shows at the top of the Upcoming tab.
-- One boolean per show row; the app reads/writes shows.pinned per (user_id, tmdb_id).
-- Safe to run more than once.
ALTER TABLE shows ADD COLUMN IF NOT EXISTS pinned boolean NOT NULL DEFAULT false;

-- Optional: speed up the "my pinned shows" lookup.
CREATE INDEX IF NOT EXISTS idx_shows_user_pinned ON shows (user_id) WHERE pinned;
