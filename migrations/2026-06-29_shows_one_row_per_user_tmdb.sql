-- Enforce ONE row per (user_id, tmdb_id) at the database level.
--
-- WHY: the original constraint was UNIQUE(user_id, tmdb_id, provider_name), so the
-- same show added under different provider names ("Max" vs "Prime Video" vs
-- "Multiple Providers") created multiple rows for one show — which crashed the
-- catch-up tab (StreamlitDuplicateElementKey). upsert_show() now keeps one row per
-- show in code; this constraint makes it impossible for ANY path (or an old deploy
-- container) to reintroduce duplicates.
--
-- SAFE TO RUN NOW: the shows table is already deduplicated. Step 1 is a no-op guard.
-- Idempotent: re-running this changes nothing.
--
-- Run at: https://supabase.com/dashboard/project/mqiulsjmizygkaompypu/sql/new

-- 1) Safety net: collapse any duplicate (user_id, tmdb_id) rows, keeping the
--    oldest row of each group. (No-op if already clean.)
DELETE FROM shows a
USING shows b
WHERE a.id > b.id
  AND a.user_id = b.user_id
  AND a.tmdb_id = b.tmdb_id;

-- 2) Drop the old 3-column unique constraint (the one that allowed provider dupes).
--    Done via a lookup so it's robust to Postgres's auto-generated constraint name.
DO $$
DECLARE c text;
BEGIN
  FOR c IN
    SELECT con.conname
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE rel.relname = 'shows'
      AND con.contype = 'u'
      AND (
        SELECT array_agg(att.attname::text ORDER BY att.attname::text)
        FROM unnest(con.conkey) AS k(attnum)
        JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k.attnum
      ) = ARRAY['provider_name', 'tmdb_id', 'user_id']
  LOOP
    EXECUTE format('ALTER TABLE shows DROP CONSTRAINT %I', c);
  END LOOP;
END $$;

-- 3) Enforce the new invariant: one row per (user_id, tmdb_id).
CREATE UNIQUE INDEX IF NOT EXISTS shows_user_tmdb_unique_idx
  ON shows (user_id, tmdb_id);
