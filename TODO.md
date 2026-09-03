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

- [ ] **`logo_overrides` is a THIRD logo source and it wins.** 5 rows written Nov 2025
      (peacock ×2, paramount+ ×2, fandango at home) pointing at JustWatch. The URLs still
      resolve, but `get_provider_logo_url` checks that table FIRST, so those services show
      a different mark on show cards than in the filter — and any future logo fix is
      silently overridden for them. Decide: delete the rows and the admin UI, or make it
      the documented top of the chain in `providers.logo_for`. The "one lookup" self-test
      missed it because it only inspects functions with `logo_url` in the name.
- [ ] **5 database writes whose failure is invisible** (`app.py` 1624/2383/2418,
      `dismissed.py:40`, `movies.py:294`) — `except: pass` around an insert/update. This
      is the exact shape that hid the genre bug for weeks. At minimum they should return
      a success flag the caller can surface.

- [ ] **`genre_excludes` migration is obsolete** — `filter_prefs` replaced it and carries
      the data forward. The file stays only as history; don't run it.

- [ ] **`render_notifications_panel` lives in `notifications.py`** but is Streamlit
      rendering. Those modules are the future native API and must stay import-safe;
      presentation belongs in app.py. (Flagged by `review.py`.) Its dead sibling
      `render_notifications_ui` is gone — the orphan check now scans every module.
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
