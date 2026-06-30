#!/usr/bin/env python3
"""
De-duplicate the `shows` table: collapse multiple rows for the same
(user_id, tmdb_id) down to a single keeper row.

WHY: the table is UNIQUE(user_id, tmdb_id, provider_name), so the same show
added under different provider names ("Hulu" vs "Multiple Providers" vs "FX")
produces several rows for one show. The app treats ownership as per-tmdb_id,
so those extra rows are duplicates — and caused a StreamlitDuplicateElementKey
crash in the catch-up tab.

KEEPER RULE (best row wins, the rest are deleted):
  1. on_provider = True  beats False         (it's actually streamable)
  2. real provider_name  beats placeholder   (not NULL / "Multiple Providers")
  3. earliest created_at                      (the original tracking row)

SAFETY:
  - DRY RUN by default. Prints counts + a sample. Writes nothing.
  - Set APPLY=1 to perform deletes. A full JSON backup of every row that will
    be deleted is written to ~/backups/streamgenie/ before anything is removed.
"""
import os
import sys
import json
import datetime as dt
from collections import defaultdict

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
URL = os.getenv("SUPABASE_URL")
KEY = os.getenv("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("SUPABASE_URL / SUPABASE_KEY not set (check .env)")

APPLY = os.getenv("APPLY") == "1"
PLACEHOLDER_PROVIDERS = {None, "", "Multiple Providers"}

client = create_client(URL, KEY)


def fetch_all_shows():
    """Page through the whole shows table (Supabase caps at 1000/req)."""
    rows, start, page = [], 0, 1000
    while True:
        resp = (client.table("shows")
                .select("id, user_id, tmdb_id, title, region, provider_name, "
                        "on_provider, created_at")
                .order("created_at")
                .range(start, start + page - 1)
                .execute())
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        start += page
    return rows


def keeper_sort_key(r):
    """Lower tuple sorts first → the row we KEEP. Inverse of 'best'."""
    on_provider_rank = 0 if r.get("on_provider") else 1
    provider_rank = 1 if r.get("provider_name") in PLACEHOLDER_PROVIDERS else 0
    created = r.get("created_at") or "9999"
    return (on_provider_rank, provider_rank, created)


def main():
    all_rows = fetch_all_shows()
    groups = defaultdict(list)
    for r in all_rows:
        groups[(r["user_id"], r["tmdb_id"])].append(r)

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    to_delete = []
    for (_uid, _tid), members in dup_groups.items():
        members_sorted = sorted(members, key=keeper_sort_key)
        # keep members_sorted[0]; delete the rest
        to_delete.extend(members_sorted[1:])

    print("=" * 64)
    print("  STREAMGENIE  shows  DE-DUPE  " + ("[APPLY]" if APPLY else "[DRY RUN]"))
    print("=" * 64)
    print(f"  Total rows in `shows`        : {len(all_rows)}")
    print(f"  Distinct (user, tmdb_id)     : {len(groups)}")
    print(f"  Duplicated show groups       : {len(dup_groups)}")
    print(f"  Rows that would be DELETED   : {len(to_delete)}")
    print(f"  Rows remaining after dedupe  : {len(all_rows) - len(to_delete)}")
    print("-" * 64)

    # Sample: up to 8 duplicate groups, showing keeper vs deletes
    shown = 0
    for (uid, tid), members in dup_groups.items():
        if shown >= 8:
            print(f"  ... and {len(dup_groups) - shown} more groups")
            break
        members_sorted = sorted(members, key=keeper_sort_key)
        keep, drops = members_sorted[0], members_sorted[1:]
        title = (keep.get("title") or "?")[:40]
        print(f"  tmdb {tid}  “{title}”  (user {uid[:8]}…)  {len(members)} rows")
        print(f"      KEEP   provider={keep.get('provider_name')!r:24} "
              f"on_provider={keep.get('on_provider')}  {keep.get('created_at')}")
        for d in drops:
            print(f"      delete provider={d.get('provider_name')!r:24} "
                  f"on_provider={d.get('on_provider')}  {d.get('created_at')}")
        shown += 1
    print("-" * 64)

    if not to_delete:
        print("  Nothing to do — no duplicates found. ✅")
        return

    if not APPLY:
        print("  DRY RUN — no changes made. Re-run with APPLY=1 to delete the rows above.")
        return

    # --- APPLY path: backup first, then delete by id ---
    backup_dir = os.path.expanduser("~/backups/streamgenie")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    backup_path = os.path.join(backup_dir, f"{stamp}-shows-dedupe-deleted.json")
    with open(backup_path, "w") as f:
        json.dump(to_delete, f, indent=2, default=str)
    print(f"  Backup of {len(to_delete)} rows → {backup_path}")

    deleted = 0
    for r in to_delete:
        client.table("shows").delete().eq("id", r["id"]).execute()
        deleted += 1
        if deleted % 50 == 0:
            print(f"    deleted {deleted}/{len(to_delete)}…")
    print(f"  ✅ Deleted {deleted} duplicate rows. Kept one per (user, tmdb_id).")


if __name__ == "__main__":
    main()
