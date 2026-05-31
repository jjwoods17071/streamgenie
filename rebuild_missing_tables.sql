-- StreamGenie — rebuild tables missing after the streamgenie2 restore (2026-05-30)
-- Restored OK: users, user_settings, shows, logo_overrides, deleted_providers, notification_preferences
-- Missing (recreated below): notifications, leaving_soon
-- Run this in the streamgenie2 Supabase SQL Editor. Idempotent / safe to re-run.

-- ============================================================
-- notifications
-- ============================================================
CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_type TEXT NOT NULL, -- 'new_episode', 'reminder', 'status_change', 'system'
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    related_show_id INTEGER,
    related_show_title TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    sent_email BOOLEAN DEFAULT FALSE,
    sent_push BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    read_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
    ON notifications(user_id, is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON notifications(user_id, created_at DESC);

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own notifications"   ON notifications;
DROP POLICY IF EXISTS "Users can update own notifications" ON notifications;
DROP POLICY IF EXISTS "System can insert notifications"    ON notifications;
DROP POLICY IF EXISTS "Users can delete own notifications" ON notifications;

CREATE POLICY "Users can view own notifications"
    ON notifications FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can update own notifications"
    ON notifications FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "System can insert notifications"
    ON notifications FOR INSERT WITH CHECK (true);
CREATE POLICY "Users can delete own notifications"
    ON notifications FOR DELETE USING (auth.uid() = user_id);

COMMENT ON TABLE notifications IS 'Unified notifications table for email, push, and in-app messages';

-- ============================================================
-- leaving_soon
-- ============================================================
CREATE TABLE IF NOT EXISTS leaving_soon (
    id SERIAL PRIMARY KEY,
    tmdb_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    leaving_date DATE NOT NULL,
    poster_path TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tmdb_id, provider_name)
);

CREATE INDEX IF NOT EXISTS idx_leaving_soon_date ON leaving_soon(leaving_date);
CREATE INDEX IF NOT EXISTS idx_leaving_soon_tmdb ON leaving_soon(tmdb_id);

-- RLS: leaving_soon is admin-curated content shown to everyone.
-- Public read; writes limited to authenticated users (admin-gated in app code).
ALTER TABLE leaving_soon ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Anyone can view leaving_soon"        ON leaving_soon;
DROP POLICY IF EXISTS "Authenticated can insert leaving_soon" ON leaving_soon;
DROP POLICY IF EXISTS "Authenticated can update leaving_soon" ON leaving_soon;
DROP POLICY IF EXISTS "Authenticated can delete leaving_soon" ON leaving_soon;

CREATE POLICY "Anyone can view leaving_soon"
    ON leaving_soon FOR SELECT USING (true);
CREATE POLICY "Authenticated can insert leaving_soon"
    ON leaving_soon FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);
CREATE POLICY "Authenticated can update leaving_soon"
    ON leaving_soon FOR UPDATE USING (auth.uid() IS NOT NULL);
CREATE POLICY "Authenticated can delete leaving_soon"
    ON leaving_soon FOR DELETE USING (auth.uid() IS NOT NULL);

CREATE OR REPLACE FUNCTION update_leaving_soon_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS leaving_soon_updated_at ON leaving_soon;
CREATE TRIGGER leaving_soon_updated_at
    BEFORE UPDATE ON leaving_soon
    FOR EACH ROW
    EXECUTE FUNCTION update_leaving_soon_timestamp();
