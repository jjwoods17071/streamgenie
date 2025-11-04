-- Add production intelligence fields to shows table
-- Stores enhanced status information beyond basic TMDB data

DO $$
BEGIN
    -- Add production_status column (enhanced status category)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='shows' AND column_name='production_status'
    ) THEN
        ALTER TABLE shows ADD COLUMN production_status TEXT;
    END IF;

    -- Add status_confidence column (high, medium, low)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='shows' AND column_name='status_confidence'
    ) THEN
        ALTER TABLE shows ADD COLUMN status_confidence TEXT;
    END IF;

    -- Add status_message column (human-readable message)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='shows' AND column_name='status_message'
    ) THEN
        ALTER TABLE shows ADD COLUMN status_message TEXT;
    END IF;

    -- Add in_production column (boolean from TMDB)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='shows' AND column_name='in_production'
    ) THEN
        ALTER TABLE shows ADD COLUMN in_production BOOLEAN DEFAULT false;
    END IF;

    -- Add web_intel column (optional web search results)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='shows' AND column_name='web_intel'
    ) THEN
        ALTER TABLE shows ADD COLUMN web_intel TEXT;
    END IF;

    -- Add last_intel_check column (when we last checked production status)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='shows' AND column_name='last_intel_check'
    ) THEN
        ALTER TABLE shows ADD COLUMN last_intel_check TIMESTAMPTZ;
    END IF;
END $$;

-- Create index for production_status queries
CREATE INDEX IF NOT EXISTS idx_shows_production_status ON shows(production_status);
CREATE INDEX IF NOT EXISTS idx_shows_in_production ON shows(in_production);

-- Verify columns were added
DO $$
DECLARE
    column_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO column_count
    FROM information_schema.columns
    WHERE table_name='shows'
    AND column_name IN ('production_status', 'status_confidence', 'status_message', 'in_production', 'web_intel', 'last_intel_check');

    IF column_count = 6 THEN
        RAISE NOTICE 'Successfully added all 6 production intelligence columns to shows table';
    ELSE
        RAISE WARNING 'Expected 6 columns, but found %', column_count;
    END IF;
END $$;
