#!/usr/bin/env python3
"""
StreamGenie self-test — verify a change before (or after) it reaches the live app.

There is ONE environment: local scripts, the hosted app, and the GitHub Actions cron all
talk to the same Supabase project. So "test it locally first" isn't isolation, and a bad
push is immediately live for every user. This is the safety net that replaces a staging
environment: it exercises the real engines against the real data, headlessly, in seconds.

    python selftest.py            # everything except paid model calls
    python selftest.py --genie    # also exercise the Claude/Gemini ranking (costs cents)
    python selftest.py --user <uuid>

Exit code 0 = all passed, 1 = something failed. Wired into CI by
.github/workflows/selftest.yml so every push to main is checked.
"""
import argparse
import os
import subprocess
import sys
import traceback

FAILURES, PASSES, SKIPS = [], [], []
DEFAULT_USER = "d10fc919-ec74-42c0-846e-16d763eac844"


def check(name):
    """Decorator: run a check, record pass/fail, never let one failure stop the run."""
    def deco(fn):
        try:
            result = fn()
            if result is None or result is True:
                PASSES.append(name)
                print(f"  \033[32mPASS\033[0m  {name}")
            else:
                SKIPS.append(name)
                print(f"  \033[33mSKIP\033[0m  {name} — {result}")
        except AssertionError as e:
            FAILURES.append((name, str(e)))
            print(f"  \033[31mFAIL\033[0m  {name}\n        {e}")
        except Exception:
            FAILURES.append((name, traceback.format_exc(limit=3)))
            print(f"  \033[31mFAIL\033[0m  {name}\n{traceback.format_exc(limit=3)}")
        return fn
    return deco


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genie", action="store_true", help="also exercise the model ranking (costs money)")
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--email", default="jjwoods@gmail.com",
                    help="real email of --user; a wrong value rewrites their profile row")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    except Exception:
        pass

    UID = args.user
    # MUST match the account's real email. app.py calls auth.ensure_user_record() on every
    # load, which upserts public.users ON ID — so a placeholder email here silently
    # rewrites the real profile row. It did exactly that before this was noticed.
    REAL_EMAIL = args.email

    _memo = {}

    def once(key, fn):
        """Compute an expensive fixture once per run and share it across checks."""
        if key not in _memo:
            _memo[key] = fn()
        return _memo[key]

    # ---------------- static ----------------
    print("\n\033[1mStatic\033[0m")

    @check("every module parses")
    def _():
        import ast, glob
        for f in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "*.py")):
            ast.parse(open(f).read(), filename=f)

    @check("no undefined names introduced")
    def _():
        try:
            out = subprocess.run([sys.executable, "-m", "pyflakes", "app.py", "recs.py",
                                  "milestones.py", "genie.py", "newsletter.py", "selftest.py"],
                                 capture_output=True, text=True, timeout=120).stdout
        except Exception:
            return "pyflakes not installed"
        undef = [l for l in out.splitlines() if "undefined name" in l]
        assert not undef, "undefined names:\n        " + "\n        ".join(undef)

    @check("module contract matches what the modules actually export")
    def _():
        """The stale-module guard in app.py only helps if its manifest is true. This keeps
        the manifest honest — a typo in it would fire the guard on a healthy deploy and
        tell the user to reboot forever."""
        import ast as _a, importlib
        tree = _a.parse(open("app.py").read())
        contract = None
        for node in _a.walk(tree):
            if (isinstance(node, _a.Assign) and node.targets
                    and getattr(node.targets[0], "id", "") == "_MODULE_CONTRACT"):
                contract = node.value
        assert contract is not None, "_MODULE_CONTRACT not found in app.py"
        missing = []
        for k, v in zip(contract.keys, contract.values):
            mod = importlib.import_module(k.id)
            for elt in v.elts:
                if not hasattr(mod, elt.value):
                    missing.append(f"{k.id}.{elt.value}")
        assert not missing, f"contract names things that don't exist: {missing}"

    @check("no session_state dict-methods beyond get/subscript")
    def _():
        """st.session_state.setdefault() raised AttributeError on Streamlit Cloud while
        working locally on the pinned 1.39.0. The proxy's dict-method surface is not
        stable across versions; membership tests and subscripts are."""
        import io, re as _re, tokenize
        # Strip comments and docstrings first — otherwise the check trips on the comment
        # explaining why the call isn't there.
        code = []
        with open("app.py", "rb") as fh:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                    code.append(tok.string)
        risky = _re.findall(r"st\.session_state\.(setdefault|items|keys|values|popitem)",
                            " ".join(code).replace(" . ", ".").replace(" ", ""))
        assert not risky, f"fragile session_state methods: {sorted(set(risky))}"

    @check("set_page_config is the first Streamlit command")
    def _():
        src = open("app.py").read()
        cfg = src.index("st.set_page_config(")
        before = src[:cfg]
        # any st.<call> before it re-breaks the app wherever secrets are absent
        import re
        bad = [m.group(0) for m in re.finditer(r"^st\.[a-z_]+\(", before, re.M)]
        assert not bad, f"Streamlit call(s) before set_page_config: {bad}"

    @check("every Streamlit call matches the installed API")
    def _():
        """The runtime checks below never render, so a wrong keyword for the PINNED
        streamlit version sails through them and crashes in the browser. That is exactly
        how `st.image(use_container_width=...)` shipped: valid in newer Streamlit, absent
        in the 1.39.0 this app pins, and every pre-existing call used use_column_width.
        """
        import ast as _ast, inspect
        import streamlit as _st

        def resolve(node):
            """st.image -> the function; st.sidebar.radio -> the function; else None."""
            parts = []
            while isinstance(node, _ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if not isinstance(node, _ast.Name) or node.id != "st":
                return None
            obj = _st
            for p in reversed(parts):
                obj = getattr(obj, p, None)
                if obj is None:
                    return None
            return obj if callable(obj) else None

        problems = []
        for path in ("app.py",):
            tree = _ast.parse(open(path).read())
            for n in _ast.walk(tree):
                if not isinstance(n, _ast.Call) or not n.keywords:
                    continue
                fn = resolve(n.func)
                if fn is None:
                    continue
                try:
                    params = inspect.signature(fn).parameters
                except (ValueError, TypeError):
                    continue
                if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
                    continue
                for kw in n.keywords:
                    if kw.arg and kw.arg not in params:
                        problems.append(f"{path}:{n.lineno} {getattr(fn,'__name__',fn)}"
                                        f"() has no keyword '{kw.arg}'")
        assert not problems, "\n        " + "\n        ".join(problems[:12])

    # ---------------- config ----------------
    print("\n\033[1mConfig\033[0m")

    @check("required env vars present")
    def _():
        missing = [k for k in ("SUPABASE_URL", "SUPABASE_KEY", "TMDB_API_KEY") if not os.getenv(k)]
        assert not missing, f"missing: {missing}"

    @check("TMDB key works")
    def _():
        import requests
        r = requests.get("https://api.themoviedb.org/3/tv/1396",
                         params={"api_key": os.getenv("TMDB_API_KEY")}, timeout=15)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert r.json().get("name") == "Breaking Bad"

    # ---------------- data ----------------
    print("\n\033[1mData\033[0m")
    from supabase import create_client
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    @check("shows table reachable and has expected columns")
    def _():
        rows = client.table("shows").select("*").limit(1).execute().data
        assert rows, "no rows returned"
        for col in ("user_id", "tmdb_id", "title", "provider_name", "next_air_date"):
            assert col in rows[0], f"missing column {col}"

    @check("test user has a watchlist")
    def _():
        rows = client.table("shows").select("tmdb_id").eq("user_id", UID).execute().data
        assert len(rows) > 5, f"only {len(rows)} rows — wrong user id?"

    # ---------------- engines ----------------
    print("\n\033[1mEngines\033[0m")
    import recs, milestones, newsletter

    @check("milestones.classify handles all milestone kinds")
    def _():
        cases = [
            ({"air_date": "2027-01-01", "season_number": 3, "episode_number": 1}, None, "season_premiere"),
            ({"air_date": "2027-01-01", "season_number": 1, "episode_number": 1}, None, "series_premiere"),
            ({"air_date": "2027-01-01", "season_number": 4, "episode_number": 9,
              "episode_type": "finale"}, "Returning Series", "season_finale"),
            ({"air_date": "2027-01-01", "season_number": 4, "episode_number": 9,
              "episode_type": "finale"}, "Ended", "series_finale"),
        ]
        for ep, status, want in cases:
            got = milestones.classify(ep, status)
            assert got and got["kind"] == want, f"{ep} -> {got}, wanted {want}"
        assert milestones.classify({"air_date": "2027-01-01", "season_number": 2,
                                    "episode_number": 7}) is None, "plain episode flagged"
        assert milestones.classify(None) is None

    @check("renewal placeholders don't inflate the season count")
    def _():
        # TMDB adds an empty Season N+1 the moment a show is renewed and counts it, so
        # "Stuart Fails to Save the Universe" (one aired season) reported "2 seasons".
        renewed = {"number_of_seasons": 2, "seasons": [
            {"season_number": 1, "episode_count": 10, "air_date": "2026-07-23"},
            {"season_number": 2, "episode_count": 0, "air_date": None}]}
        assert milestones.real_season_count(renewed) == 1, "placeholder still counted"
        assert [s["season_number"] for s in milestones.real_seasons(renewed)] == [1]

        specials = {"number_of_seasons": 5, "seasons": [
            {"season_number": 0, "episode_count": 4, "air_date": "2010-01-01"},
            {"season_number": 1, "episode_count": 7, "air_date": "2010-02-01"}]}
        assert milestones.real_season_count(specials) == 1, "specials counted as a season"

        # a payload with the count but no seasons array must not collapse to zero
        assert milestones.real_season_count({"number_of_seasons": 5}) == 5
        assert milestones.real_season_count({}) == 0

    @check("season count is unchanged for established shows")
    def _():
        import requests as _rq
        for tid, want in ((1396, 5), (60059, 6)):        # Breaking Bad, Better Call Saul
            d = _rq.get(f"https://api.themoviedb.org/3/tv/{tid}",
                        params={"api_key": os.getenv("TMDB_API_KEY")}, timeout=15).json()
            got = milestones.real_season_count(d)
            assert got == want, f"tv/{tid}: got {got}, wanted {want}"

    @check("recs seeds from most-watched shows")
    def _():
        rows = client.table("shows").select("tmdb_id,title,next_air_date").eq("user_id", UID).execute().data
        wc = recs.fetch_watched_counts(client, UID)
        assert wc, "no watched episodes — engagement ranking untestable"
        seeds = recs.seed_shows(rows, wc, max_seeds=4)
        assert seeds, "no seeds produced"
        counts = [wc.get(s["tmdb_id"], 0) for s in seeds]
        assert counts == sorted(counts, reverse=True), f"seeds not by engagement: {counts}"

    @check("recs produces attributed picks (deterministic path)")
    def _():
        out = once("recs", lambda: recs.for_user(client, UID, limit=8, use_genie=False))
        picks = out["picks"]
        assert picks, "no picks"
        assert out["pool_size"] > 0
        for p in picks:
            assert p.get("why"), f"{p['title']} has no attribution"
            assert p["why"].startswith("Because you watch"), p["why"]
            assert p.get("tmdb_id") and p.get("title")

    @check("recs never recommends something already on the watchlist")
    def _():
        owned = {r["tmdb_id"] for r in
                 client.table("shows").select("tmdb_id").eq("user_id", UID).execute().data}
        out = once("recs", lambda: recs.for_user(client, UID, limit=8, use_genie=False))
        dupes = [p["title"] for p in out["picks"] if p["tmdb_id"] in owned]
        assert not dupes, f"already on watchlist: {dupes}"

    @check("recs degrades rather than raising when the pool is empty")
    def _():
        out = recs.for_user(client, "00000000-0000-0000-0000-000000000000", limit=5, use_genie=False)
        assert out["picks"] == [], "expected empty picks for a user with no shows"

    @check("genie ranking returns picks drawn from the candidate pool")
    def _():
        if not args.genie:
            return "use --genie to run (costs a model call)"
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("GEMINI_API_KEY")):
            return "no model API key configured"
        out = recs.for_user(client, UID, limit=5, use_genie=True)
        assert out["ranked_by"] == "genie", f"fell back to {out['ranked_by']}"
        for p in out["picks"]:
            assert p.get("blurb"), f"{p['title']} has no blurb"

    @check("wildcard walks the pool instead of repeating")
    def _():
        pool = [{"tmdb_id": i, "title": f"T{i}", "seeds": ["s"], "vote": 9 - i * 0.1,
                 "sources": {"rec"}} for i in range(5)]
        rolls = [recs.wildcard(pool, roll=r)["title"] for r in range(5)]
        assert len(set(rolls)) == 5, f"repeats within one cycle: {rolls}"
        assert recs.wildcard(pool, roll=5)["title"] == rolls[0], "should cycle back round"

    @check("wildcard skips what was already shown")
    def _():
        pool = [{"tmdb_id": i, "title": f"T{i}", "seeds": ["s"], "vote": 9 - i * 0.1,
                 "sources": {"rec"}} for i in range(5)]
        pick = recs.wildcard(pool, shown_ids=[0, 1, 2])
        assert pick["tmdb_id"] not in (0, 1, 2), pick

    @check("wildcard degrades on an empty pool")
    def _():
        assert recs.wildcard([]) is None
        # everything already shown -> recycle rather than return nothing
        pool = [{"tmdb_id": 1, "title": "T", "seeds": ["s"], "vote": 8, "sources": {"rec"}}]
        assert recs.wildcard(pool, shown_ids=[1]) is not None

    @check("search interpretation skips short queries (no wasted model call)")
    def _():
        import genie
        assert genie.interpret_search("Sicario") is None
        assert genie.interpret_search("") is None

    @check("fetch_shows shapes records and survives bad ids")
    def _():
        import tmdb as _t
        assert _t.fetch_shows([]) == {}, "empty input should be empty output"
        got = _t.fetch_shows([1396, -1])          # Breaking Bad + a nonexistent id
        assert 1396 in got and -1 not in got, f"bad id lost the batch: {sorted(got)}"
        rec = got[1396]
        for k in ("name", "status", "seasons", "next_episode_to_air"):
            assert k in rec, f"shaped record missing {k}"

    # ---------------- movies ----------------
    print("\n\033[1mMovies\033[0m")
    import movies

    @check("movie search returns normalized rows")
    def _():
        res = movies.search("Michael Clayton", 3)
        assert res, "no results"
        m = res[0]
        for k in ("tmdb_id", "media_type", "title", "year", "poster_path", "vote"):
            assert k in m, f"missing {k}"
        assert m["media_type"] == "movie"

    @check("movie recommendations work")
    def _():
        res = movies.search("Sicario", 1)
        assert res, "seed search failed"
        recs_out = movies.recommendations(res[0]["tmdb_id"], 5)
        assert recs_out, "no recommendations"
        assert all(r["media_type"] == "movie" for r in recs_out)

    @check("media_type migration has been applied")
    def _():
        if not movies.media_type_available(client):
            return "migrations/2026-08-24_media_type.sql not run yet"

    @check("movies never leak into the TV row fetch")
    def _():
        if not movies.media_type_available(client):
            return "migration not run — nothing to leak yet"
        rows = movies.fetch_tv_rows(client, UID, "tmdb_id,title")
        bad = [r for r in rows if (r.get("media_type") or "tv") == "movie"]
        assert not bad, f"{len(bad)} movie rows leaked into the TV fetch"

    @check("movie ids can coexist with TV ids")
    def _():
        if not movies.media_type_available(client):
            return "migration not run"
        # the whole reason for the media_type column: TMDB reuses ids across types
        tv_ids = {r["tmdb_id"] for r in movies.fetch_tv_rows(client, UID, "tmdb_id,title")}
        mv_ids = {m["tmdb_id"] for m in movies.list_movies(client, UID)}
        overlap = tv_ids & mv_ids
        assert isinstance(overlap, set), "unreachable"

    @check("release_info classifies streaming availability")
    def _():
        # Superman 2025: theatrical Jul, PVOD Aug 15, HBO Max Sep 19 — the named-service
        # entry is the one that matters, and it must not be confused with the PVOD date.
        i = movies.release_info(1061474)
        assert i["theatrical"], "no theatrical date"
        assert i["digital"], "no digital date"
        assert i["streaming_service"], "named streaming service not picked up"
        assert i["streaming"] != i["digital"], \
            "streaming date collapsed onto the PVOD date"
        assert i["status"] in ("streaming", "coming"), i["status"]

    @check("an old film is not reported as in theaters")
    def _():
        # Michael Clayton (2007) has no digital entries; without a recency window it
        # claimed to be in cinemas forever.
        i = movies.release_info(4566)
        assert i["status"] != "theaters", "old film still reads as in theaters"

    @check("status_label covers every status")
    def _():
        for s in movies.STATUS_ORDER:
            lbl = movies.status_label({"status": s, "streaming": "2026-01-01", "providers": []})
            assert lbl and not lbl.startswith("None"), f"no label for {s}"

    @check("group_by_status keeps every movie and drops empty groups")
    def _():
        fake = [{"title": t, "info": {"status": s, "streaming": None}}
                for t, s in [("A", "streaming"), ("B", "coming"), ("C", "streaming")]]
        groups = movies.group_by_status(fake)
        assert [g[0] for g in groups] == ["streaming", "coming"], groups
        assert sum(len(g[2]) for g in groups) == 3

    # ---------------- writes ----------------
    # Every check above this point is a read or a pure function. The operations a user
    # performs constantly — add, delete, mark watched, dismiss, vote — had ZERO coverage,
    # because there is one environment and testing them meant writing to real data.
    # These run against a dedicated empty auth user instead.
    print("\n\033[1mWrite paths\033[0m")

    SANDBOX = "6a8419b6-b9b2-48e7-b1e4-0910d96cb42e"     # selftest@streamgenie.local
    TEST_TV, TEST_MOVIE = 1396, 550                      # Breaking Bad / Fight Club

    def sandbox_ok():
        """Refuse to write anywhere near a real account. A bug in a cleanup filter is how
        a test suite eats someone's watchlist."""
        assert SANDBOX != UID, "sandbox id equals the read-test user"
        rows = client.table("shows").select("tmdb_id").eq("user_id", SANDBOX).execute().data
        assert len(rows) < 50, f"sandbox has {len(rows)} rows — refusing to treat as scratch"

    def sweep():
        """Leave nothing behind, including after a crashed earlier run."""
        for tbl, col in (("shows", "user_id"), ("watched_episodes", "user_id"),
                         ("dismissed_shows", "user_id"), ("rec_feedback", "user_id")):
            try:
                client.table(tbl).delete().eq(col, SANDBOX).execute()
            except Exception:
                pass

    sandbox_ok()
    # A user created in the Supabase dashboard can authenticate but has no public.users
    # row, and shows/watched_episodes/rec_feedback all FK onto it — so every insert fails
    # until the app's own provisioning runs. This is what first login would do.
    try:
        client.table("users").upsert(
            {"id": SANDBOX, "email": "selftest@streamgenie.local",
             "username": "selftest_sandbox"}, on_conflict="id").execute()
    except Exception as e:
        print(f"  sandbox provisioning: {e}")
    sweep()

    @check("a show can be added and removed")
    def _():
        try:
            client.table("shows").insert({
                "user_id": SANDBOX, "tmdb_id": TEST_TV, "media_type": "tv",
                "title": "Breaking Bad", "region": "US", "on_provider": True,
                "provider_name": "Netflix"}).execute()
            got = client.table("shows").select("title,provider_name,media_type")\
                .eq("user_id", SANDBOX).eq("tmdb_id", TEST_TV).execute().data
            assert len(got) == 1, f"expected 1 row, got {len(got)}"
            assert got[0]["media_type"] == "tv" and got[0]["provider_name"] == "Netflix"
            client.table("shows").delete().eq("user_id", SANDBOX)\
                .eq("tmdb_id", TEST_TV).execute()
            left = client.table("shows").select("tmdb_id").eq("user_id", SANDBOX).execute().data
            assert not left, f"{len(left)} rows survived the delete"
        finally:
            sweep()

    @check("the same tmdb_id can be a show AND a film at once")
    def _():
        # The entire reason media_type exists: TMDB reuses ids across media types, so the
        # unique index has to be (user, tmdb_id, media_type) or the second add overwrites
        # the first. This is the check that would catch a migration regression.
        try:
            for mt, title in (("tv", "tv-550"), ("movie", "movie-550")):
                client.table("shows").insert({
                    "user_id": SANDBOX, "tmdb_id": TEST_MOVIE, "media_type": mt,
                    "title": title, "region": "US", "on_provider": True}).execute()
            rows = client.table("shows").select("media_type,title")\
                .eq("user_id", SANDBOX).eq("tmdb_id", TEST_MOVIE).execute().data
            assert len(rows) == 2, f"both media types should coexist, got {len(rows)}"
            assert {r["media_type"] for r in rows} == {"tv", "movie"}
        finally:
            sweep()

    @check("movies.add / movies.remove round-trip")
    def _():
        try:
            m = movies.search("Fight Club", 1)
            assert m, "search returned nothing"
            assert movies.add(client, SANDBOX, m[0]), "add reported failure"
            mine = movies.list_movies(client, SANDBOX)
            assert len(mine) == 1 and mine[0]["media_type"] == "movie", mine
            # a film must never reach the TV surfaces
            tv_rows = movies.fetch_tv_rows(client, SANDBOX, "tmdb_id,title")
            assert not tv_rows, f"film leaked into the TV fetch: {tv_rows}"
            assert movies.remove(client, SANDBOX, m[0]["tmdb_id"]), "remove reported failure"
            assert not movies.list_movies(client, SANDBOX), "film survived removal"
        finally:
            sweep()

    @check("marking episodes watched updates counts and last-watched")
    def _():
        import watched as _w
        try:
            for ep in (1, 2, 3):
                assert _w.set_watched(client, SANDBOX, TEST_TV, 2, ep, True), f"S2E{ep} failed"
            counts = _w.watched_counts(client, SANDBOX)
            assert counts.get(TEST_TV) == 3, f"expected 3 watched, got {counts.get(TEST_TV)}"
            assert _w.last_watched(client, SANDBOX).get(TEST_TV) == (2, 3), "wrong furthest episode"
            assert _w.set_watched(client, SANDBOX, TEST_TV, 2, 3, False), "unmark failed"
            assert _w.watched_counts(client, SANDBOX).get(TEST_TV) == 2, "unmark didn't take"
        finally:
            sweep()

    @check("dismissing a show hides it from discovery")
    def _():
        import dismissed as _d
        try:
            _d.dismiss(client, SANDBOX, TEST_TV)
            assert TEST_TV in _d.get_dismissed(client, SANDBOX), "dismissal didn't persist"
        finally:
            sweep()

    @check("a rec vote persists and is readable as taste")
    def _():
        try:
            client.table("rec_feedback").upsert(
                {"user_id": SANDBOX, "tmdb_id": TEST_TV, "title": "Breaking Bad",
                 "verdict": "down"}, on_conflict="user_id,title").execute()
            taste = recs.taste_signals(client, SANDBOX)
            assert "Breaking Bad" in taste["disliked"], taste
            # upsert, not insert — voting twice must not create a second row
            client.table("rec_feedback").upsert(
                {"user_id": SANDBOX, "tmdb_id": TEST_TV, "title": "Breaking Bad",
                 "verdict": "up"}, on_conflict="user_id,title").execute()
            taste = recs.taste_signals(client, SANDBOX)
            assert taste["liked"] == ["Breaking Bad"] and not taste["disliked"], taste
        finally:
            sweep()

    @check("progress can be recorded to a specific episode")
    def _():
        """"I watched season 1 up to episode 3" — the shape a voice command would take.
        Deterministic: calls the tool directly rather than paying for intent parsing."""
        import genie as _g
        try:
            client.table("shows").insert(
                {"user_id": SANDBOX, "tmdb_id": 97546, "media_type": "tv",
                 "title": "Ted Lasso", "region": "US", "on_provider": True}).execute()
            out = _g._exec_tool(client, SANDBOX, "mark_caught_up",
                                {"tmdb_id": 97546, "through_season": 1, "through_episode": 3})
            assert "3 aired episode" in out, out
            import watched as _w
            assert _w.watched_counts(client, SANDBOX).get(97546) == 3, "wrong episode count"
            assert _w.last_watched(client, SANDBOX).get(97546) == (1, 3), "wrong furthest episode"
            # and the whole-season form must still work
            out = _g._exec_tool(client, SANDBOX, "mark_caught_up",
                                {"tmdb_id": 97546, "through_season": 1})
            assert _w.watched_counts(client, SANDBOX).get(97546, 0) > 3, \
                "whole-season form regressed"
        finally:
            sweep()

    @check("the sandbox is left clean")
    def _():
        for tbl in ("shows", "watched_episodes", "dismissed_shows", "rec_feedback"):
            try:
                n = len(client.table(tbl).select("user_id").eq("user_id", SANDBOX).execute().data)
            except Exception:
                continue
            assert n == 0, f"{n} rows left behind in {tbl}"

    # ---------------- newsletter ----------------
    print("\n\033[1mNewsletter\033[0m")

    @check("build_sections returns the full contract")
    def _():
        s = once("sections", lambda: newsletter.build_sections(client, UID))
        for k in ("week_start", "week_end", "airing", "highlights", "games", "leaving",
                  "coming", "rec_candidates", "recs", "rec_feedback", "watchlist_titles"):
            assert k in s, f"missing section {k}"
        for r in s["recs"]:
            assert "seed" in r, "rec missing seed (genie._week_payload depends on it)"

    @check("render_html produces a complete email")
    def _():
        s = once("sections", lambda: newsletter.build_sections(client, UID))
        html = newsletter.render_html(s)
        assert html.startswith("\n    <html>") or "<html>" in html
        assert "</html>" in html, "unterminated html"
        assert len(html) > 500, f"suspiciously short: {len(html)} bytes"
        if s["coming"]:
            assert "Coming Eventually" in html, "coming section built but not rendered"

    @check("coming-eventually is ranked by engagement, not alphabetically")
    def _():
        s = once("sections", lambda: newsletter.build_sections(client, UID))
        if len(s["coming"]) < 2:
            return "fewer than 2 undated shows to compare"
        counts = [c.get("watched", 0) for c in s["coming"]]
        assert counts == sorted(counts, reverse=True), f"not engagement-ranked: {counts}"

    # ---------------- render ----------------
    # The engine checks above never draw anything, so layout bugs sail straight through
    # them and land in the browser — that is exactly how st.image(use_container_width)
    # and a three-deep column nest both shipped green. These render the real app.
    print("\n\033[1mRender\033[0m")

    import genie as _genie_mod
    from streamlit.testing.v1 import AppTest

    # Neutralise the model calls: layout is what's under test, and a render per view
    # would otherwise cost real tokens on every run.
    _genie_mod.rank_recommendations = lambda *a, **k: None
    _genie_mod.interpret_search = lambda *a, **k: None

    # ONE AppTest reused across views — st.cache_data survives between at.run() calls, so
    # the TMDB work is paid once. Separate instances cost ~150s instead of ~35s.
    _at = AppTest.from_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"),
                            default_timeout=180)
    _at.session_state["user"] = {"id": UID, "email": REAL_EMAIL}

    def _render(**state):
        for k, v in state.items():
            _at.session_state[k] = v
        _at.run()
        return _at

    for _label in ("📺 Watch", "✨ Discover", "🏈 Sports"):
        def _make(lbl):
            @check(f"renders: {lbl}")
            def _():
                at = _render(nav_view=lbl, _wild_on=False, find_q="")
                assert not at.exception, str(at.exception[0].value)[:300]
        _make(_label)

    @check("renders: Watch / Calendar view")
    def _():
        # The dated agenda used to be its own block; the merge made it a view mode, so
        # it needs its own render or a crash there would go unseen.
        at = _render(nav_view="📺 Watch", wl_view_mode="🗓️ Calendar")
        assert not at.exception, str(at.exception[0].value)[:300]
        _render(wl_view_mode="▦ Grid")      # leave the shared instance on the default

    @check("no unreachable render_ functions")
    def _():
        """The Watch/All Shows merge left render_catch_up defined but never called — and
        it owned the "last watched S2E10" marker, so that feature silently disappeared.
        Dead UI code is how a merge loses a feature without anything going red."""
        import ast as _a
        src_ = open("app.py").read()
        tree = _a.parse(src_)
        defined = {n.name for n in tree.body
                   if isinstance(n, _a.FunctionDef) and n.name.startswith("render_")}
        called = {n.func.id for n in _a.walk(tree)
                  if isinstance(n, _a.Call) and isinstance(n.func, _a.Name)}
        orphans = sorted(defined - called)
        assert not orphans, f"defined but never called: {orphans}"

    @check("renders: Wildcard")
    def _():
        at = _render(nav_view="📺 Watch", _wild_on=True)
        assert not at.exception, str(at.exception[0].value)[:300]

    @check("renders: Find results")
    def _():
        at = _render(nav_view="📺 Watch", _wild_on=False, find_q="Sicario")
        assert not at.exception, str(at.exception[0].value)[:300]

    @check("the logo returns you home from anywhere")
    def _():
        at = _render(nav_view="🏈 Sports", find_q="Sicario")
        home = [b for b in at.button if "StreamGenie" in (b.label or "")]
        assert home, "no home anchor rendered"
        home[0].click().run()
        assert not at.exception, str(at.exception[0].value)[:300]
        assert at.session_state["nav_view"] == "📺 Watch", at.session_state["nav_view"]
        assert not at.session_state["find_q"], "query survived going home"
        # go_home clears four keys; asserting one of them is not testing the function
        assert not at.session_state["_wild_on"], "wildcard survived going home"
        assert not at.session_state["_genie_on"], "genie chat survived going home"

    @check("renders: film detail page")
    def _():
        # Films had no detail page at all — ?show= is the TV PDP, and TMDB reuses ids
        # across media types, so opening a movie there loaded an unrelated series.
        at = _render(nav_view="📺 Watch", find_q="", _wild_on=False)
        at.query_params["movie"] = "4566"        # Michael Clayton
        at.run()
        assert not at.exception, str(at.exception[0].value)[:300]
        at.query_params.clear()

    @check("clearing Find doesn't write a live widget's state")
    def _():
        # Assigning st.session_state["find_q"] inline after the text_input exists raises
        # StreamlitAPIException. The Clear button must go through an on_click callback.
        at = _render(nav_view="📺 Watch", find_q="Sicario")
        clear = [b for b in at.button if "Clear" in (b.label or "")]
        assert clear, "Clear button not rendered while a query is active"
        clear[0].click().run()
        assert not at.exception, str(at.exception[0].value)[:300]
        assert not at.session_state["find_q"], "query not cleared"

    # ---------------- summary ----------------
    print("\n" + "=" * 62)
    print(f"\033[1m{len(PASSES)} passed, {len(FAILURES)} failed, {len(SKIPS)} skipped\033[0m")
    if FAILURES:
        print("\nFailures:")
        for name, err in FAILURES:
            print(f"  • {name}: {err.splitlines()[0] if err else ''}")
    print("=" * 62)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
