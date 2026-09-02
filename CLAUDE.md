# StreamGenie — working agreement

Read `PRODUCT.md` first. It defines what this app is for; this file is how we build it.

## 0. Posture

**Treat this as a product, not a personal script** (decided 2026-09-01). Other people's
accounts exist in it, and a broken page counts as a real failure. In practice: no
unverified pushes to main, data changes always previewed and backed up, and a bias toward
confirming the shape of a change before writing it.

**Ask before building anything that touches layout or navigation.** Confirm the shape
first, even when the request seems clear — the cost of asking is one message; the cost of
building the wrong shape is a day. Routine calls inside an agreed shape don't need asking.

## 1. Clarify before building

This project has one job (see PRODUCT.md) and a lot of surface area. Most rework here has
come from building the right thing in the wrong place, not from bad code.

**Ask before writing code when:**
- The request names a UI change but not the user problem behind it ("add a filter" — for
  what question the user is trying to answer?).
- Two readings would produce materially different work — e.g. "hide caught-up shows"
  could mean hide everywhere, or hide from Watch but keep in the library. That one
  actually mattered.
- The change touches data (a migration, a bulk UPDATE) — always preview and confirm.
- Scope is ambiguous AND the work is large. Small and reversible? Just do it and say so.

**Don't ask when** the answer is discoverable from the code, or a sensible default exists
and the change is easy to undo. State the assumption and proceed.

**When a layout question comes up, check the reference apps** (PRODUCT.md) before
inventing. "How does Apple TV handle this?" has settled several arguments here already.

## 2. Verification is not optional

**`python selftest.py` before every push.** ~39 checks, ~50s, against real data. CI runs
it on push to main (`.github/workflows/selftest.yml`).

The suite has three layers and they exist for specific reasons:

| layer | catches | why it exists |
|---|---|---|
| static | undefined names, Streamlit API misuse | `st.image(use_container_width=)` isn't in the pinned 1.39 and shipped to prod |
| engine | recs, milestones, movies, newsletter | logic regressions against real data |
| **render** | anything Streamlit raises at draw time | three crashes reached the user before this existed |

**Prove a new check can fail before trusting it.** Twice in this project a green result
came from a broken harness rather than working code — once from an exec slice that left a
helper undefined (silently "all clear" on 82 rows), once from a bug reintroduction that
didn't actually reintroduce the bug. A check that has never failed has not been tested.

**Every user-reported bug gets a regression test in the same commit as the fix.**

## 3. Keep logic out of the UI

Native iOS/Android is the direction (PRODUCT.md). `recs.py`, `milestones.py`, `movies.py`,
`tmdb.py`, `newsletter.py` are UI-agnostic and import no streamlit — they are the future
API. `app.py` is the disposable layer.

New behaviour goes in a module and is called from `app.py`, not written inline. If it
needs `st.` to work, it's presentation; if it doesn't, it belongs in a module where the
self-test can reach it.

## 4. Environment facts

- **The hosted app IS the dev environment.** `git push` to main auto-deploys to Streamlit
  Cloud. There is no staging.
- **One Supabase project.** Local scripts, hosted app and the cron all share it. A "local
  test" writes to production data.
- Streamlit is **pinned at 1.39.0** — check a widget's signature against the installed
  version, not against current docs.

## 5. Deploying

`git push` to main auto-deploys, but **Streamlit Cloud caches imported modules**. `app.py`
is the script and re-executes every run; `tmdb.py`, `recs.py` and the rest are imports,
loaded once into `sys.modules` and NOT reloaded when their source changes.

So a commit that adds a function to a module AND calls it from app.py can land as new
app.py against a stale module, surfacing as
`AttributeError: module 'tmdb' has no attribute 'fetch_shows'` partway down a page.

**After any deploy that changes a module (not just app.py), reboot the app:**
Manage app → ⋮ → Reboot app.

A guard at the top of app.py checks `_MODULE_CONTRACT` and shows that instruction instead
of a raw AttributeError. Add to the contract when a module gains a function app.py depends
on; the self-test keeps the manifest honest.

## 6. Provider logos — settled, do not re-derive

**TMDB is the source.** `providers.WIKIPEDIA_LOGOS` is a five-entry **exception list**, not
a replacement: only Max, AMC+, MGM+, Starz and PBS, whose TMDB image was co-branded or
missing. Every other service keeps the tile it has always had. A self-test pins the list in
both directions, because the first attempt at this replaced all twelve and changed logos
that were never broken. **Fix what was reported, not the whole category.**

- TMDB's catalogue is organised around **listings, not brands**. A service sold as an
  add-on has a co-branded image (the mark badged with Amazon's); channel-only services have
  none at all. That is why those five needed replacing and the rest didn't.
- **Never show a co-branded mark.** A service shows its own logo or none. `build_catalogue`
  excludes resold listings outright.
- **Do not fetch Wikipedia logos at runtime.** `pageimages` returns the page's lead image,
  which for Prime Video is a 1.6MB screenshot; filename heuristics pick `Commons-logo.svg`
  and the retired "CBS All Access" mark. Pick by hand, verify by LOOKING at the image,
  freeze the URL.
- **Only the Wikipedia marks get the white chip** (`logo_needs_light_tile`). They are
  transparent print assets, often solid black (Max is), and vanish on the dark theme.
  TMDB's tiles are already dark-UI artwork and render bare.
- **One lookup only.** `provider_logo_url` is it; `get_provider_logo_url` is a shim. A
  second implementation is what kept the co-branded icons alive after the first fix.

## 7. Gotchas that have bitten us

- `set_page_config` must be the FIRST Streamlit call. `st.secrets` *renders* an element
  before it raises, so a try/except around it doesn't stop it claiming that slot.
- Columns nest **one level only**. The poster grids already use their own; wrapping a view
  in `st.columns` makes it three deep and crashes the page.
- Writing a widget's own `session_state` key inline after the widget exists raises. Use an
  `on_click` callback.
- `if st.button(): work(); st.rerun()` runs the script twice. Use `on_click`.
- Caching on a *tuple of ids* means adding or removing one item invalidates everything.
  Prefer per-id storage.
- Cache the lowest-level fetch. `tv_details` uncached meant four higher caches each
  re-fetched the same show — 235 TMDB calls for 82 shows.
- In a 5,000-line file, "unique-looking" text anchors often aren't (`get_show_meta` and
  `get_show_seasons` end identically). Prefer line-addressed edits; syntax-check after.
- Never `git add -A` without reading `git status` — a screenshot got committed that way.

## 8. Reviewing alignment

`python review.py` asks a model whether recent changes serve the product objective, and
what QA is missing. **Advisory only — it never fails a build.** Use it before a batch of
work lands, or when a feature has grown past what it was asked to do.
