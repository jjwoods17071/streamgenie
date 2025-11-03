-- StreamGenie PostgreSQL Schema for Supabase
-- Run this in Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table (for multi-user support)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    -- Supabase Auth handles passwords, we just store metadata here
    username VARCHAR(50) UNIQUE,
    watchlist_public BOOLEAN DEFAULT false
);

-- User settings table
CREATE TABLE user_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email_notifications BOOLEAN DEFAULT false,
    reminder_time TIME DEFAULT '08:00:00',
    timezone VARCHAR(50) DEFAULT 'America/New_York',
    theme VARCHAR(20) DEFAULT 'light',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Shows table (multi-tenant version of current SQLite table)
CREATE TABLE shows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tmdb_id INTEGER NOT NULL,
    title VARCHAR(500) NOT NULL,
    region VARCHAR(10) NOT NULL DEFAULT 'US',
    on_provider BOOLEAN DEFAULT false,
    next_air_date DATE,
    overview TEXT,
    poster_path VARCHAR(255),
    provider_name VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, tmdb_id, provider_name)  -- One show per user per provider
);

-- Indexes for performance
CREATE INDEX idx_shows_user_id ON shows(user_id);
CREATE INDEX idx_shows_tmdb_id ON shows(tmdb_id);
CREATE INDEX idx_shows_next_air_date ON shows(next_air_date);
CREATE INDEX idx_shows_user_provider ON shows(user_id, provider_name);

-- Logo overrides table (move from JSON file to database)
CREATE TABLE logo_overrides (
    provider_name VARCHAR(100) PRIMARY KEY,
    logo_url TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Deleted providers table (move from JSON file to database)
CREATE TABLE deleted_providers (
    provider_name VARCHAR(100) PRIMARY KEY,
    deleted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_settings_updated_at BEFORE UPDATE ON user_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_shows_updated_at BEFORE UPDATE ON shows
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_logo_overrides_updated_at BEFORE UPDATE ON logo_overrides
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Row Level Security (RLS) Policies
-- This ensures users can only see their own data

ALTER TABLE shows ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;

-- Users can only see their own shows
CREATE POLICY "Users can view own shows"
    ON shows FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own shows"
    ON shows FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own shows"
    ON shows FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own shows"
    ON shows FOR DELETE
    USING (auth.uid() = user_id);

-- Users can view their own settings
CREATE POLICY "Users can view own settings"
    ON user_settings FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can update own settings"
    ON user_settings FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own settings"
    ON user_settings FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Public watchlists: anyone can view if watchlist_public is true
CREATE POLICY "Public watchlists are viewable by everyone"
    ON shows FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM users
            WHERE users.id = shows.user_id
            AND users.watchlist_public = true
        )
    );

-- Logo overrides and deleted providers are global (no RLS needed)
-- Anyone can read, only admins can write (set up admin role separately)

-- Create a default user for migration (temporary)
-- This will be used to migrate existing SQLite data
INSERT INTO users (id, email, username, watchlist_public)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'default@streamgenie.local',
    'default_user',
    false
);

-- Create default user settings
INSERT INTO user_settings (user_id, email_notifications)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    false
);

-- Comments for documentation
COMMENT ON TABLE users IS 'User accounts with metadata';
COMMENT ON TABLE user_settings IS 'User preferences and settings';
COMMENT ON TABLE shows IS 'Shows tracked by users with streaming provider info';
COMMENT ON TABLE logo_overrides IS 'Custom logo URLs for streaming providers';
COMMENT ON TABLE deleted_providers IS 'Providers that have been hidden from the UI';

COMMENT ON COLUMN shows.tmdb_id IS 'The Movie Database ID for the show';
COMMENT ON COLUMN shows.on_provider IS 'Whether the show is currently available on the provider';
COMMENT ON COLUMN shows.next_air_date IS 'Next episode air date';
COMMENT ON COLUMN shows.provider_name IS 'Streaming service name (Netflix, Hulu, etc)';
