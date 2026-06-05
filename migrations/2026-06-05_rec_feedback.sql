-- 👍/👎 feedback on Genie's newsletter recommendations — the self-improving
-- taste loop. One row per (user, title); re-votes update the verdict.
-- Run at: https://supabase.com/dashboard/project/mqiulsjmizygkaompypu/sql/new

CREATE TABLE IF NOT EXISTS rec_feedback (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tmdb_id integer,
  title text NOT NULL,
  verdict text NOT NULL CHECK (verdict IN ('up','down')),
  seed text,
  created_at timestamptz DEFAULT now(),
  UNIQUE (user_id, title)
);
