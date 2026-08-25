-- Movies alongside TV shows and sports.
--
-- WHY A COLUMN AND NOT AN ID TRICK: sports follows are namespaced by NEGATIVE tmdb_id
-- (sports.encode_id), and ~20 places in app.py read "tmdb_id > 0" as "this is a TV
-- show". Namespacing movies into any numeric band would silently break every one of
-- them. TMDB also reuses ids across media types — movie 550 is Fight Club, tv 550 is a
-- different title entirely — so a row's real identity is (tmdb_id, media_type).
--
-- Idempotent: re-running this changes nothing.
-- Run at: https://supabase.com/dashboard/project/mqiulsjmizygkaompypu/sql/new

-- 1) The column. Existing rows are TV by definition (that's all the app tracked).
ALTER TABLE shows ADD COLUMN IF NOT EXISTS media_type text NOT NULL DEFAULT 'tv';

-- 2) Label the sports follows, which are already distinguishable by negative id.
UPDATE shows SET media_type = 'sports' WHERE tmdb_id < 0 AND media_type <> 'sports';

-- 3) Only these three kinds exist; a typo'd media_type would make rows invisible to
--    every view rather than failing loudly.
ALTER TABLE shows DROP CONSTRAINT IF EXISTS shows_media_type_check;
ALTER TABLE shows ADD CONSTRAINT shows_media_type_check
  CHECK (media_type IN ('tv', 'movie', 'sports'));

-- 4) Widen the uniqueness invariant from (user, tmdb_id) to include media_type, so
--    tv/550 and movie/550 can both exist for one user. Replaces the index created by
--    2026-06-29_shows_one_row_per_user_tmdb.sql.
CREATE UNIQUE INDEX IF NOT EXISTS shows_user_tmdb_media_unique_idx
  ON shows (user_id, tmdb_id, media_type);
DROP INDEX IF EXISTS shows_user_tmdb_unique_idx;

-- 5) Verify.
SELECT media_type, count(*) FROM shows GROUP BY media_type ORDER BY media_type;
