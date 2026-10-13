# StreamGenie — open work

**Sequencing lives in ROADMAP.md** (Now / Near / Next). This file is the flat list.

Replaces PRODUCT_ROADMAP.md, which was leftover chat text from May, not a roadmap.
Current as of 2026-09-01. See PRODUCT.md for what the app is for, CLAUDE.md for how we
work on it.

## Waiting on a decision

- [ ] **Trust `/Users/jjwoods/oks`** in Claude Code — the last directory still prompting.

## Parked deliberately

- [ ] **`show_cache` table.** Design, measurements and limits are in SCALING.md; the swap
      point is `tmdb.fetch_shows`. Build it when a second real user appears, or when cold
      loads become annoying. It will NOT reduce AI token use — that was measured and is a
      separate system.

## Known gaps

- [ ] **The API has nowhere to run.** `api.py` works and is tested, but Streamlit Cloud
      hosts one process. Needs Railway / Fly / Render — the first recurring cost in this
      project. Until then nothing can consume it.
- [ ] **No API test uses a real token.** Every route is proven CLOSED (401 without a valid
      one), but the authenticated paths are unverified end-to-end. Needs a signed-in
      user's JWT; set `SUPABASE_TEST_JWT` and the check can extend to cover them.

- [ ] **`SUPABASE_ANON_KEY` is not in CI.** The RLS check skips without it, so CI is
      currently green on a check that never runs. Add it as a GitHub Actions secret
      (it is public by design — it ships in any browser client).
- [ ] **Leaving Soon's Add button still does `st.button(): work(); st.rerun()`** — two
      full passes. Unlike the delete beside it, it validates and has two outcomes to
      report, so on_click needs the message routed through session_state.

- [ ] **Run `migrations/2026-09-02_drop_logo_overrides.sql`** — the code that read
      `logo_overrides` / `deleted_providers` is gone, so the tables are inert; this just
      drops them. Backup of the 5 rows is in the migration header and in
      `~/backups/streamgenie/2026-09-02-221407-logo_overrides.json`.

- [ ] **`genre_excludes` migration is obsolete** — `filter_prefs` replaced it and carries
      the data forward. The file stays only as history; don't run it.

- [ ] **Deploys that change an imported module need a manual reboot** (Manage app → ⋮ →
      Reboot). Streamlit Cloud caches imports; only app.py re-executes. A guard now
      detects it and says so, but the reboot is still manual. Worth checking whether the
      Cloud API can be poked from CI after a push.
- [ ] **Streamlit Cloud cold start is ~15s** before anything paints. Nothing is broken —
      the container sleeps. The `show_cache` above fixes what happens after boot, not the
      boot itself.

## Roadmap, never built

- [ ] **Catch-up nudges** — spoiler-free, bell only. The one remaining item from the
      original approved roadmap.
- [ ] **Sports stakes lines on tiles** — "win and they clinch" context for followed teams.
- [ ] **Native iOS/Android.** The modules (`recs`, `milestones`, `movies`, `tmdb`,
      `newsletter`) import no streamlit and are already the API; `app.py` is the throwaway
      layer. Keep new logic out of app.py so this stays true.

## Settled — do not reopen without cause

- **Licensing.** TMDB's standard licence forbids commercial use; we are open source and
  non-commercial, which keeps us inside it. Attribution renders in the sidebar and is
  required — don't remove it. Revisit only if monetisation returns (PRODUCT.md).
- **Movies are not a destination.** Media type is a filter, not a place to navigate to.
- **Caught-up-with-no-date is hidden from Watch** but always counted, and kept in
  All Shows. Hiding without stating the number is how people stop trusting a list.
