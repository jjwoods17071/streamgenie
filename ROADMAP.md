# StreamGenie — Now / Near / Next

Written 2026-09-02, revised the same day after a session that changed the priorities. `PRODUCT.md` says what this is for; this says in what order.

The objective hasn't changed: **"what do I watch tonight, and where is it?"** Everything
below is judged against whether it makes that faster to answer, on more devices.

---

## The unlock we already shipped without noticing

Enabling RLS on 2026-09-01 was filed as a security fix. It is also **the thing that makes
native apps cheap**.

With RLS off, every client had to go through a trusted server holding the service_role
key — meaning a native app would have required a full backend before it could show a
single row. With RLS on and per-user policies, a phone can talk to Supabase **directly**
using the public anon key plus the signed-in user's JWT, and the database itself refuses
to hand over anyone else's rows.

So the architecture is a split, not a rewrite:

    phone / web  ──► Supabase directly        watchlist CRUD, progress, prefs
                 └─► small Python API         the things only Python can do:
                                              recommendations, TMDB enrichment,
                                              milestones, the newsletter

That second box is small, and most of it already exists as importable modules. **We are
closer to a native client than the Streamlit UI suggests.**

---

## NOW — stabilise the basics (do these before anything new)

The goal is that we can change things confidently and hear about failures without you
having to paste a traceback.

**What one session actually found (2026-09-02).** Five fixes shipped, and four of them
were the same bug wearing different clothes: **a second implementation whose failure was
silent.** Two logo lookups. Two genre stores. Two definitions of "which row is this
show". A dead renderer nobody called. None of them showed up as an error — they were
hidden by a bare `except`, a `.get()` default, or simply never being called. This is the
project's characteristic defect, and the checks that pass while it happens are the reason
it survives. **Treat "is there a second one?" as the first question in any bug hunt here.**

1. **Sentry.** The single highest-leverage item, and more so after the above: every one of
   those bugs was invisible precisely because nothing reported. Today production failures
   are discovered by Joe, by hand, and a truncated traceback once cost a full
   wrong-root-cause round. Needs: a DSN. Effort: ~30 min.
2. **Prove RLS actually closed the hole.** `service_role` bypasses RLS, so nothing we can
   run today verifies it — the suite would pass identically if RLS were off, which is the
   same shape of problem as everything above. With the anon key we can assert an anon read
   returns nothing and keep it as a permanent check. RLS was on once before and got
   silently disabled. Needs: the anon key (public by design). Effort: ~30 min.
3. **Finish the silent-failure sweep.** The audit is done; the work isn't:
   - `logo_overrides` — **code removed 2026-09-02**; run
     `migrations/2026-09-02_drop_logo_overrides.sql` to drop the tables.
   - **Five writes whose failure is swallowed entirely** (`app.py` 1624/2383/2418,
     `dismissed.py:40`, `movies.py:294`) — `except: pass` around an insert or update.
     `dismissed.py` is the exact shape that hid the genre bug. They should at least
     return a success flag the caller can surface.
   - Every table the code references now exists — that half is clean.
4. **`notifications.py` is half UI.** `render_notifications_panel` is Streamlit rendering
   inside a module a native client would import. The last one; splitting it takes the
   module count to 23/29 and leaves a clean API boundary.
5. ~~Make `upsert_show` / `delete_show` testable.~~ **Done 2026-09-02** — now
   `watchlist.py`, taking `user_id` explicitly. Four checks exercise the real add/remove
   path instead of hand-written inserts, and writing them surfaced a latent silent failure
   in delete. app.py keeps thin wrappers so the 17 call sites didn't change.
6. ~~The small open questions.~~ **Both answered 2026-09-02.** The sidebar is gone
   (branding and settings to a header, TMDB credit and admin tools to a footer); the
   service filter is multi-select and batches into one redraw.

Deliberately NOT now: `show_cache`, preview environments, feature flags. All are answers
to scale we don't have.

### A rule this session earned

**A check that has never failed has not been tested** was already in CLAUDE.md. Add its
sharper form: *a check can pass for the wrong reason.* "There is exactly one logo lookup"
passed for ten months while a third lookup sat in a database table, because it only
compared two functions to each other and never asked where a logo may come FROM. Write
checks against the invariant, not against the shape of the last bug.

---

## NEAR — make the core portable (the real prerequisite)

Nothing here is user-visible. It is what turns "a Streamlit app" into "a product with a
UI attached", and it can be done incrementally while the app keeps running.

1. **Finish decoupling the modules.** 22 of 29 already import no Streamlit — including
   `filters`, `providers`, `genre_prefs` and now `watchlist`, the write paths.
   The remaining ones — `sports`, `watched`, `dismissed`, `notifications`, `discover`,
   `leaving_soon`, `auth` —
   use `@st.cache_data` or `session_state`. Replace those with a caching interface the
   caller provides. **That count is the progress bar for this phase: 22/29 → 29/29.**
2. **Stand up a small HTTP API** (FastAPI) over the decoupled modules. Endpoints follow
   what the UI already asks for: recommendations, wildcard, release info, milestones,
   search. Deploy alongside the Streamlit app; it stays the only consumer at first, which
   is how you find out whether the boundary is right before betting a phone app on it.
3. **Point the Streamlit app at the API.** Same behaviour, one consumer, no new surface.
   If this is painful, the API is wrong — far better to learn that now than from a
   half-built mobile client.
4. **`show_cache`** (SCALING.md) becomes genuinely necessary here: multiple clients
   multiply the TMDB fan-out that one Streamlit session currently absorbs.
5. **Catch-up nudges.** Worth building in this phase specifically because the same
   mechanism becomes push notifications later — a nudge with nowhere to go is still the
   best-tested part of a push pipeline.

---

## NEXT — native clients and stores

Only start once NEAR is done. A native client against an unproven API is the expensive
way to discover the API is wrong.

1. **Resolve the licensing gate FIRST.** TMDB's standard licence forbids commercial use.
   A free, non-commercial app is likely fine; anything paid or ad-supported needs a
   written agreement with them. **Ask TMDB before building, not after** — the answer
   determines whether this is a hobby release or a product, and it is a business question
   with a lead time, not an engineering one.
2. **Pick one client stack** and do one platform properly. React Native or Flutter buys
   both stores from one codebase and is the right default for a two-person effort;
   Swift/Kotlin buys polish nobody has asked for yet.
3. **Store logistics** — worth knowing before committing: Apple Developer Program is a
   recurring annual fee and every build goes through review; Google Play is a one-off fee
   with a lighter process. Both now require privacy disclosures covering exactly what we
   collect (email, viewing history) and TMDB attribution must appear in-app. Verify the
   current specifics when you get there; these change.
4. **Voice (Alexa / Google Home) — narrow, but genuinely ours.** "What do I watch
   tonight?" is a *browsing* question and a bad voice experience: you want posters, not a
   list read aloud. **"What's new tonight?" is a good one** — a short spoken briefing of
   what aired today across your services. That is the one thing this app knows that no
   single streaming service does.
   Check the platform landscape before planning around it: Google retired Conversational
   Actions some time ago and the replacement story has moved more than once. Treat "which
   platform still supports this shape of skill?" as the first task, not an assumption.

---

## The track that matters most: killing manual progress entry

Every watchlist app dies the same way — someone maintains it for three weeks, falls
behind, the list becomes a lie, they stop opening it. No service except Netflix offers a
history export, so the cost of saying "here's where I am" IS the product's survival
problem, not a feature request.

**On Trakt: they are a competitor, not a component.** They track progress by episode, have
an up-next queue, an episode calendar and recommendations — most of what we do. Their moat
is the automatic scrobbling ecosystem (extensions, device integrations) that we lack. Our
moat is the multi-service "where do I watch it?" answer, film streaming-release dates, and
a conversational way to update progress — which they lack.

That shapes the integration precisely:

- **One-way import: yes.** "Bring your Trakt history" is a migration on-ramp. It takes a
  rival's users' data once, gives instant value, and leaves no ongoing dependency — if
  they revoked access tomorrow, nothing we shipped would break.
- **Two-way sync: no.** That makes Trakt the source of truth for progress and us a skin
  over their data, with our core loop hostage to a competitor's API terms.
- **Check their terms before building either.** Not verified as of writing; assume
  competing use may be restricted until confirmed.

### How the incumbent actually does it (researched 2026-09-02)

Worth knowing before costing our own version.

Trakt shipped a first-party **Streaming Scrobbler** in Dec 2024 (iOS/Android) covering
Netflix, Prime Video, Hulu and Apple TV. You link a service; it syncs ~10 minutes later,
then polls **every 24 hours**. That cadence gives the mechanism away: it is not live
playback detection, it periodically reads the service's STORED viewing history — the same
private endpoints the service's own clients call, using the user's authenticated session.
The community browser extension (Universal Trakt Scrobbler) does the same plus real-time
scrobbling, across more services, from inside a logged-in browser.

**This corrects the premise that "only Netflix exposes history".** True of PUBLIC APIs.
Every service has a private history endpoint its own client uses, readable from within the
user's session — which is why this can only live in a browser extension or an app with a
login webview, never on our server.

**And it is a maintenance commitment, not a feature.** The community extension carries open
issues for Netflix and Prime failing to sync; Trakt's own version warns Prime "may not work
well in some regions" and that Hulu returns release dates rather than real timestamps for
older content. Private APIs change without notice, vary by region, and sit in ToS grey
area. Budget ongoing upkeep, not a project with an end date.

That raises the value of a one-way Trakt import: they have already absorbed that
maintenance across four services, and importing once inherits the work without inheriting
the dependency.

Ranked by how much each actually reduces manual entry, and by how independent it leaves us:

| approach | effort | independence | status |
|---|---|---|---|
| Voice / chat: "I watched S4 up to E3" | nearly free | full | **works today** (genie mark_caught_up) |
| Netflix history import | tiny | full | exists, buried in a Discover expander |
| Trakt one-way import | small | full after import | not started |
| **Our own browser extension** | large | **full — this is the moat** | not started |
| Trakt two-way sync | medium | dependent on a rival | not recommended |

**Sequence:** surface the Netflix import where it can be found (it solves the headline
problem and is hidden) → make the conversational form obvious in the UI, since it already
works → Trakt import as an acquisition path → the extension when there is a reason to
invest at that scale.

The extension is the only one that makes the problem *disappear* rather than get faster.
It is also the only one that would give us Trakt's moat instead of borrowing it.

## How to work through this

- **One phase at a time, and finish it.** The failure mode is starting NEXT because it's
  more exciting, on top of a NOW that is still shaky.
- **Every user-reported bug gets a regression test in the same commit as the fix.** That
  rule is why the suite is at 50 checks and none of them are busywork.
- **Prove a check can fail before trusting it.** Twice here a green result came from a
  broken harness rather than working code.
- **Measure before designing.** Counting found that 51 of 71 "Still Watching" shows had
  never been opened, and that a cold render made 235 TMDB calls for 82 shows. Both changed
  the design. Ten minutes of counting has repeatedly beaten an hour of building.
- **Ask before building anything that touches layout or navigation.** The cost of asking
  is one message.
- **Keep decisions written down** — `TODO.md` has a "settled" section, `SCALING.md` keeps
  the numbers behind a deferral. Six months from now the reasoning is the valuable part.
