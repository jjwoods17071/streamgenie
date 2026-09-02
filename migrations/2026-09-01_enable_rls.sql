-- Close the "table publicly accessible" hole Supabase flagged on 2026-08-31.
--
-- WHY THIS IS SAFE FOR THE APP: StreamGenie connects with the SERVICE_ROLE key, which
-- bypasses RLS entirely. Enabling RLS changes nothing for the running app, the cron, or
-- the self-test. What it does is close the door for the ANON key, which today can read,
-- edit and delete every row in every table.
--
-- WHY IT MATTERS HERE SPECIFICALLY: the GitHub repo is PUBLIC and the project ref
-- (mqiulsjmizygkaompypu) appears in app.py and in these migration files. The only thing
-- standing between that and the data is "nobody has fetched the anon key" — which is not
-- a security model, it's a coincidence. Supabase's design assumes RLS is the boundary.
--
-- Enabling RLS with no matching policy is DENY by default for anon/authenticated. The
-- per-user policies below exist so the app still works if it ever moves off service_role.
--
-- Idempotent. Run at:
-- https://supabase.com/dashboard/project/mqiulsjmizygkaompypu/sql/new

-- 1) Per-user tables: a row belongs to exactly one user.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['shows', 'watched_episodes', 'notifications',
                           'notification_preferences', 'dismissed_shows',
                           'user_settings', 'rec_feedback']
  LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = t) THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_own_rows', t);
      EXECUTE format(
        'CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
        'USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid())',
        t || '_own_rows', t);
    END IF;
  END LOOP;
END $$;

-- 2) users: the row IS the identity, so it keys on id rather than user_id.
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_own_row ON public.users;
CREATE POLICY users_own_row ON public.users FOR ALL TO authenticated
  USING (id = auth.uid()) WITH CHECK (id = auth.uid());

-- 3) Shared reference data — app-wide, not owned by anyone. Readable by signed-in users;
--    writes stay service_role only (which bypasses RLS), so admin tooling is unaffected.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['logo_overrides', 'deleted_providers', 'leaving_soon']
  LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = t) THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_read_all', t);
      EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO authenticated '
                     'USING (true)', t || '_read_all', t);
    END IF;
  END LOOP;
END $$;

-- 4) Verify: every public table should report rowsecurity = true.
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY rowsecurity, tablename;
