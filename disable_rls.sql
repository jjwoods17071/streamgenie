-- Disable Row Level Security for development
-- This allows the anon key to insert/update/delete data
-- In production with auth, you would keep RLS enabled

ALTER TABLE shows DISABLE ROW LEVEL SECURITY;
ALTER TABLE logo_overrides DISABLE ROW LEVEL SECURITY;
ALTER TABLE deleted_providers DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings DISABLE ROW LEVEL SECURITY;

-- Verify RLS is disabled
SELECT
    tablename,
    rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
AND tablename IN ('shows', 'logo_overrides', 'deleted_providers', 'user_settings');
