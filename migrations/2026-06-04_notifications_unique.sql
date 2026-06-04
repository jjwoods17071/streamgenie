-- Stop duplicate notifications/emails at the database level.
-- Multiple app instances (old deploy containers) can fire the 8:00 AM reminder job
-- concurrently; a check-then-insert guard in Python loses that race. A unique index
-- makes the insert itself the lock: only one writer wins, and only the winner emails.
--
-- Run at: https://supabase.com/dashboard/project/mqiulsjmizygkaompypu/sql/new

-- 1) Remove any existing duplicates (keep the oldest of each group)
DELETE FROM notifications a
USING notifications b
WHERE a.id > b.id
  AND a.user_id = b.user_id
  AND a.notification_type = b.notification_type
  AND a.related_show_id IS NOT DISTINCT FROM b.related_show_id
  AND a.message = b.message;

-- 2) One notification per (user, type, show, message).
-- NULLS NOT DISTINCT so digest notifications (related_show_id = NULL) also dedup.
CREATE UNIQUE INDEX IF NOT EXISTS notifications_dedup_idx
  ON notifications (user_id, notification_type, related_show_id, message)
  NULLS NOT DISTINCT;
