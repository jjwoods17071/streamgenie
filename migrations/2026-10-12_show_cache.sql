-- Shared cache of shaped TMDB show records. Design and measurements: SCALING.md.
--
-- WHY NOW: a cold Watch render was 235 TMDB calls before tv_details was cached and is
-- ~104 now; the remaining cost multiplies with every client. The API (api.py) and a
-- future phone are additional consumers of the same fan-out that one Streamlit session
-- currently absorbs alone.
--
-- WHY (tmdb_id, media_type) AND NOT tmdb_id: TMDB reuses ids across media types — 550 is
-- both Fight Club and an unrelated series. Same reason `shows` needed the column.
--
-- WHY THE SHAPED RECORD, NOT RAW: measured 1.66 KB shaped vs 3.07 KB raw, 46% smaller.
-- Egress is the binding constraint on the free tier (5 GB/month), not storage.
--
-- Idempotent. Run at:
-- https://supabase.com/dashboard/project/mqiulsjmizygkaompypu/sql/new

CREATE TABLE IF NOT EXISTS public.show_cache (
    tmdb_id        bigint      NOT NULL,
    media_type     text        NOT NULL DEFAULT 'tv',
    payload        jsonb       NOT NULL,          -- tmdb.shape_show() output
    status         text,                          -- denormalized; drives the refresh tier
    fetched_at     timestamptz NOT NULL DEFAULT now(),
    refresh_after  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tmdb_id, media_type),
    CONSTRAINT show_cache_media_type_check CHECK (media_type IN ('tv', 'movie'))
);

-- The refresh job selects WHERE refresh_after <= now() ORDER BY refresh_after, so this
-- index is what keeps that cheap as the table grows.
CREATE INDEX IF NOT EXISTS idx_show_cache_refresh ON public.show_cache (refresh_after);

-- SHARED reference data, unlike every other table here: there is no user_id, and every
-- signed-in user may read all of it. Writes have NO policy at all, so only the service
-- role (the app and the cron) can write. Same shape as the read-all tables in
-- 2026-09-01_enable_rls.sql.
ALTER TABLE public.show_cache ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS show_cache_read_all ON public.show_cache;
CREATE POLICY show_cache_read_all ON public.show_cache
    FOR SELECT TO authenticated USING (true);

SELECT count(*) AS rows_cached FROM public.show_cache;
-- expect: 0 on a fresh install
