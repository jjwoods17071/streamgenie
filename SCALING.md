# Scaling notes — the show cache we deliberately did NOT build

Measured 2026-08-31, at 3 users / 99 watchlist rows. Written down so the next person
(or the next me) doesn't re-derive it.

## The idea

Cache TMDB show records in a shared Supabase table so a cold page load is one query
instead of ~100 HTTP calls. **Deferred** — see "When to build it".

## What measuring changed

**A show cache saves no AI tokens.** These are unrelated systems. Every model call in the
app is: `rank_recommendations` (1 per For You rebuild, 6h cache), `interpret_search`
(1 per search, only for queries of 4+ words), `generate_editorial` (1 per user per week),
and `genie.chat` (1 per message). Genie is never given show metadata — it receives titles
and the user's 👍/👎 and ranks them. Caching TMDB data would not remove a single call.

**"Top N popular shows" is the wrong set.** The shows that matter are the ones on
watchlists, which skew obscure — War Machine: World War II, Titans: The Rise of
Hollywood, Barbecue Showdown. A top-100 cache would miss almost all of them.

**Dedup saves nothing yet.** 89 distinct tmdb_ids across 89 rows; zero shows are tracked
by more than one user. The master-list design is still right — show popularity is a power
law, so overlap climbs fast with users — but it cannot be demonstrated at n=3.

**Cache the SHAPED record, not raw TMDB.**

    raw TMDB payload      3.07 KB/show
    shaped (app fields)   1.66 KB/show    46% smaller

`_shape_meta` already defines the 13 fields the app uses. Halving the payload halves
storage AND egress, and egress is the binding constraint (below).

## Design, if/when it's built

One master table keyed by `(tmdb_id, media_type)` — composite because TMDB reuses ids
across media types, the same reason `shows` needed `media_type`.

    show_cache
      tmdb_id, media_type    composite PK
      payload    jsonb       shaped record, ~1.7 KB
      status     text        denormalized, drives the refresh tier
      fetched_at, refresh_after  timestamptz
      index on refresh_after

**Refresh by volatility, not on a blanket schedule.** Of 25 shows sampled, 9 were Ended
or Canceled — those records are immutable and refreshing them nightly is pure waste.

    Returning, episode within 14d   daily
    Returning, no date              weekly
    Ended / Canceled                monthly

**Time-boxed, oldest-first batching** is what prevents ever hitting a wall:
select `WHERE refresh_after <= now() ORDER BY refresh_after LIMIT n`, process in chunks of
~40 through `tmdb.parallel_map`, bulk-upsert per chunk, and stop at a wall-clock budget
(~8 min of the cron's 15-min timeout). The work is never all-or-nothing, so at any scale
the job refreshes what it can and resumes next run; staleness grows gradually instead of
the job failing.

## Limits

Storage — not binding for a long time (Supabase free tier is 500 MB):

    1,000 shows       1.7 MB
    10,000           17 MB
    50,000           85 MB
    250,000 (all TMDB TV)  424 MB

Throughput — measured 82 shows in 1.9s at 8 workers (~40/s); assume 25/s. An 8-minute
window is ~12,000 shows/night. With volatility tiering only ~60% need daily refresh, so
this supports roughly **20,000 distinct shows** before staleness grows — about 2,000
active users at 100 shows each with realistic overlap.

Egress — **the ceiling that binds first.** 5 GB/month on free tier; a cold load reading
100 shaped shows is ~170 KB, so ~30,000 cold loads/month ≈ **1,000 daily-active users**.
Raw payloads would halve that.

Read batching — PostgREST puts `.in_()` ids in the URL, so batch reads at **500 ids** to
stay under URL length limits. Not an issue below that.

TMDB — no published hard limit; ~50 req/s is safe. `tmdb.MAX_WORKERS = 8` is ~40/s peak
and already conservative. Leave it.

## When to build it

Either a second real user appears (dedup starts paying, cold starts multiply), or cold
load becomes annoying enough to justify ~80 lines plus a migration.

What made deferring safe: caching `tv_details` took a cold Watch render from 30.6s/235
calls to 19.0s/104, and a warm one from 8.5s/50 to 2.9s/4. The remaining pain is
Streamlit Cloud cold starts only.

`app.fetch_show_records()` is the single swap point — it is the only place that turns
tmdb_ids into shaped records, so pointing it at `show_cache` (with TMDB as the miss path)
is a one-function change.
