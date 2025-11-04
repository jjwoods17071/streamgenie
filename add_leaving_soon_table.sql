-- Add leaving_soon table to track shows leaving streaming platforms
-- Admins can manually add/update entries with departure dates

CREATE TABLE IF NOT EXISTS leaving_soon (
    id SERIAL PRIMARY KEY,
    tmdb_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    provider_name TEXT NOT NULL,  -- Netflix, Hulu, etc.
    leaving_date DATE NOT NULL,
    poster_path TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tmdb_id, provider_name)  -- One entry per show per provider
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_leaving_soon_date ON leaving_soon(leaving_date);
CREATE INDEX IF NOT EXISTS idx_leaving_soon_tmdb ON leaving_soon(tmdb_id);

-- Create updated_at trigger
CREATE OR REPLACE FUNCTION update_leaving_soon_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER leaving_soon_updated_at
    BEFORE UPDATE ON leaving_soon
    FOR EACH ROW
    EXECUTE FUNCTION update_leaving_soon_timestamp();

-- Verify table creation
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'leaving_soon'
    ) THEN
        RAISE NOTICE 'Successfully created leaving_soon table';
    ELSE
        RAISE WARNING 'Failed to create leaving_soon table';
    END IF;
END $$;
