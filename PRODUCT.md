# StreamGenie — what this is for

## The job to be done

People subscribe to six services and lose track of what they were watching. The
question this product answers, every time it's opened, is:

> **"What do I watch tonight, and where is it?"**

Everything else — recommendations, sports, the newsletter — is secondary to that one
sentence. If a change doesn't make that question faster to answer, it needs a reason.

## Who it's for

Someone with a lot of shows across a lot of services who has stopped being able to hold
it in their head. Not a cinephile cataloguing a collection; a normal person trying to
resume something on a Tuesday night.

## Principles

1. **Actionable before complete.** The default view shows what you can watch now. Things
   with nothing to do about them are hidden — but the count is always stated, because
   silently dropping a third of someone's list is how they stop trusting it.
2. **Answer, then inventory.** Every page opens with a summary, not a wall of rows.
3. **Say where you left off.** "Last watched S2E10" beats "3 unwatched".
4. **Poster art is the interface.** Text is the exception, not the default. See below.
5. **Never guess at availability.** If we don't know where something streams, say so
   rather than showing a plausible-looking wrong service.
6. **Degrade, don't fail.** No model key, no TMDB, no migration — the feature gets
   quieter, it doesn't crash.

## Reference implementations to borrow from

When a layout question comes up, look at what these already solved rather than inventing:

- **tv.apple.com** — dense poster grids (~9–10 across at 1456px), zero text per tile, dark
  ground so artwork carries the page, horizontal shelves for discovery.
- **Netflix browse** — rows by intent ("Continue Watching" first), hover/click for detail
  rather than inline synopsis, and no synopsis anywhere in browse.
- **Both** — the media type is never a destination you navigate to. You don't pick
  "TV or films" before you can look for anything.

Where we deliberately differ: we are **multi-service**, so "where is it?" is a first-class
question those apps never have to answer. Provider is load-bearing here in a way it isn't
for them.

## Non-goals (for now)

- Not a review site, not a social network, not a catalogue to browse for its own sake.
- Not a player. We never stream anything; we point at where to.
- Not a sports scores app. Teams are followed like shows — schedule, not live scores.

## Where this is going

Native iOS/Android for progress tracking across services. That has a hard consequence for
how we build now: **business logic must stay out of the Streamlit layer.** `recs.py`,
`milestones.py`, `movies.py`, `tmdb.py`, `newsletter.py` are already UI-agnostic and would
become the API behind a native client. `app.py` is the throwaway part. Keep it that way —
anything that ends up only in `app.py` has to be rewritten twice.

## Licensing — open source, non-commercial (decided 2026-08-31)

TMDB's standard API licence **prohibits commercial use** and requires a separate written
agreement. Their terms list charging users, selling the app, and running ads alongside
TMDB-powered features as commercial use.

**Decision: this stays open source and non-commercial for now**, which keeps us inside the
standard licence. That is a real constraint on the roadmap, not a formality:

- No paid tier, no ads, no "pro" features, no selling the app — any of those require a
  written agreement with TMDB first.
- **Attribution is required even non-commercially**: the TMDB logo plus the notice
  "This product uses the TMDB API but is not endorsed or certified by TMDB."
- Open question worth asking TMDB directly if this ever gets serious: their terms also
  list "using TMDB content with LLMs, chatbots, or AI systems" under the commercial
  clause. Genie is given TMDB titles and overviews to rank. Non-commercially this is
  probably fine, but it is the one item where our reading could differ from theirs.

If monetisation comes back on the table, the sequence is: contact TMDB for a commercial
agreement, or move to a differently-licensed data source. Don't build paid features on the
assumption it will be granted.
