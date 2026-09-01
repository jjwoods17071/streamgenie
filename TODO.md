# StreamGenie — open work

Replaces PRODUCT_ROADMAP.md, which was leftover chat text from May, not a roadmap.
Current as of 2026-09-01. See PRODUCT.md for what the app is for, CLAUDE.md for how we
work on it.

## Waiting on a decision

- [ ] **Collapse the sidebar?** Since nav moved above the content it holds only At a
      glance, Rebuild caches, the settings toggle, login and the TMDB attribution.
      Dropping it gives the poster grids the full window width.
- [ ] **Service filter is single-select** (a radio, as asked). You can no longer filter to
      "Netflix OR Hulu". Fine if that was never the use case — but it's a deliberate loss,
      not an oversight.
- [ ] **Trust `/Users/jjwoods/oks`** in Claude Code — the last directory still prompting.

## Parked deliberately

- [ ] **`show_cache` table.** Design, measurements and limits are in SCALING.md; the swap
      point is `tmdb.fetch_shows`. Build it when a second real user appears, or when cold
      loads become annoying. It will NOT reduce AI token use — that was measured and is a
      separate system.

## Known gaps

- [ ] **`render_notifications_panel` lives in `notifications.py`** but is Streamlit
      rendering. Those modules are the future native API and must stay import-safe;
      presentation belongs in app.py. (Flagged by `review.py`.)
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
