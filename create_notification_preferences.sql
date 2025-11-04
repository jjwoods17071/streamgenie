-- Notification Preferences Table
-- Stores user preferences for different types of notifications

CREATE TABLE IF NOT EXISTS notification_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Email notification preferences
    email_new_episodes BOOLEAN DEFAULT true,
    email_weekly_preview BOOLEAN DEFAULT true,
    email_series_finale BOOLEAN DEFAULT true,
    email_series_cancelled BOOLEAN DEFAULT true,
    email_show_added BOOLEAN DEFAULT false,

    -- In-app notification preferences (always on by default)
    inapp_new_episodes BOOLEAN DEFAULT true,
    inapp_weekly_preview BOOLEAN DEFAULT true,
    inapp_series_finale BOOLEAN DEFAULT true,
    inapp_series_cancelled BOOLEAN DEFAULT true,
    inapp_show_added BOOLEAN DEFAULT true,

    -- Frequency settings
    daily_reminder_time TIME DEFAULT '08:00:00',
    weekly_preview_day TEXT DEFAULT 'Sunday',
    weekly_preview_time TIME DEFAULT '18:00:00',
    timezone TEXT DEFAULT 'America/New_York',

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT unique_user_preferences UNIQUE(user_id)
);

-- Index for fast user lookups
CREATE INDEX IF NOT EXISTS idx_notification_preferences_user
ON notification_preferences(user_id);

-- Row Level Security Policies
ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY;

-- Users can view their own preferences
CREATE POLICY "Users can view own preferences"
ON notification_preferences
FOR SELECT
USING (auth.uid() = user_id);

-- Users can insert their own preferences
CREATE POLICY "Users can insert own preferences"
ON notification_preferences
FOR INSERT
WITH CHECK (auth.uid() = user_id);

-- Users can update their own preferences
CREATE POLICY "Users can update own preferences"
ON notification_preferences
FOR UPDATE
USING (auth.uid() = user_id);

-- Users can delete their own preferences
CREATE POLICY "Users can delete own preferences"
ON notification_preferences
FOR DELETE
USING (auth.uid() = user_id);

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_notification_preferences_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update updated_at on every update
DROP TRIGGER IF EXISTS trigger_update_notification_preferences_updated_at ON notification_preferences;
CREATE TRIGGER trigger_update_notification_preferences_updated_at
    BEFORE UPDATE ON notification_preferences
    FOR EACH ROW
    EXECUTE FUNCTION update_notification_preferences_updated_at();

-- Add show_status column to shows table (if it doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='shows' AND column_name='show_status'
    ) THEN
        ALTER TABLE shows ADD COLUMN show_status TEXT DEFAULT 'Returning Series';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='shows' AND column_name='last_status_check'
    ) THEN
        ALTER TABLE shows ADD COLUMN last_status_check TIMESTAMPTZ;
    END IF;
END $$;

COMMENT ON TABLE notification_preferences IS 'User preferences for email and in-app notifications';
COMMENT ON COLUMN notification_preferences.email_new_episodes IS 'Send email when a new episode airs';
COMMENT ON COLUMN notification_preferences.email_weekly_preview IS 'Send weekly preview email on specified day';
COMMENT ON COLUMN notification_preferences.email_series_finale IS 'Send email for series finale episodes';
COMMENT ON COLUMN notification_preferences.email_series_cancelled IS 'Send email when a show is cancelled';
COMMENT ON COLUMN notification_preferences.email_show_added IS 'Send email when adding a show to watchlist';
