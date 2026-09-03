-- Drop the provider-logo override tables.
--
-- WHY: logo_overrides was a THIRD source of truth for a service's brand mark, and it sat
-- FIRST in the chain — get_provider_logo_url consulted it before anything else. Five rows
-- written 2025-11-03 (peacock x2, paramount+ x2, fandango at home) pointed at JustWatch
-- icons, so those services rendered one mark on a show card and a different one in the
-- filter, and every subsequent logo fix was silently overridden for them.
--
-- It existed to work around logos we didn't have. We have them now: providers.logo_for is
-- the single lookup (TMDB, with five hand-picked Wikipedia pins for the services whose
-- TMDB image was co-branded or missing). A self-test now fails if any function with
-- "logo" in its name reads a table or session_state.
--
-- deleted_providers goes with it: it was admin-only state for the same removed screen,
-- and providers.py owns the provider taxonomy now.
--
-- The app no longer reads either table, so this is housekeeping — nothing breaks if it
-- waits. Run at:
-- https://supabase.com/dashboard/project/mqiulsjmizygkaompypu/sql/new
--
-- The five rows, should they ever be wanted back (also in
-- ~/backups/streamgenie/2026-09-02-221407-logo_overrides.json):
--   peacock premium   https://images.justwatch.com/icon/194173870/s100/peacocktv.avif
--   peacock           https://images.justwatch.com/icon/194173870/s100/peacocktv.avif
--   paramount+        https://images.justwatch.com/icon/242706661/s100/paramountplus.avif
--   paramount plus    https://images.justwatch.com/icon/242706661/s100/paramountplus.avif
--   fandango at home  https://images.justwatch.com/icon/322380782/s100/vudu.avif

DROP TABLE IF EXISTS public.logo_overrides;
DROP TABLE IF EXISTS public.deleted_providers;

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name IN ('logo_overrides', 'deleted_providers');
-- expect: zero rows
