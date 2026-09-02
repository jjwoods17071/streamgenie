-- Filters that can be SUSPENDED for a while, not just switched off.
--
-- The problem: "hide kids' content" is right 360 days a year and wrong the evening a niece
-- visits. Every service treats preferences as permanent, so the only options are live with
-- it or turn it off and forget to turn it back on. A suspension expires by itself.
--
-- Also replaces genre_excludes, which was designed but never created — which is why
-- hidden genres have silently been session-only and reset on every reload.
--
-- Idempotent. Run at:
-- https://supabase.com/dashboard/project/mqiulsjmizygkaompypu/sql/new

CREATE TABLE IF NOT EXISTS public.filter_prefs (
    user_id          uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    filter_key       text        NOT NULL,   -- 'genre:kids', 'lang:original', ...
    enabled          boolean     NOT NULL DEFAULT true,
    value            jsonb,                  -- filter-specific, e.g. ["en","ko"] for language
    suspended_until  timestamptz,            -- NULL = in force; past = expired, back in force
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, filter_key)
);

-- Same posture as every other table (see 2026-09-01_enable_rls.sql): the app connects
-- with service_role and bypasses RLS, so this only closes the door to the anon key.
ALTER TABLE public.filter_prefs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS filter_prefs_own_rows ON public.filter_prefs;
CREATE POLICY filter_prefs_own_rows ON public.filter_prefs FOR ALL TO authenticated
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- Carry over anything from genre_excludes if that table was ever created.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema = 'public' AND table_name = 'genre_excludes') THEN
    INSERT INTO public.filter_prefs (user_id, filter_key, enabled)
    SELECT user_id, 'genre:' || genre_key, true FROM public.genre_excludes
    ON CONFLICT (user_id, filter_key) DO NOTHING;
  END IF;
END $$;

SELECT filter_key, enabled, suspended_until FROM public.filter_prefs ORDER BY filter_key;
