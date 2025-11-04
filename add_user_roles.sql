-- Add user_role column to users table
-- Roles: 'user' (default), 'admin'

DO $$
BEGIN
    -- Add user_role column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='users' AND column_name='user_role'
    ) THEN
        ALTER TABLE users ADD COLUMN user_role TEXT DEFAULT 'user';

        -- Add constraint to only allow valid roles
        ALTER TABLE users ADD CONSTRAINT valid_user_role
            CHECK (user_role IN ('user', 'admin'));
    END IF;
END $$;

-- Create index for faster role lookups
CREATE INDEX IF NOT EXISTS idx_users_role ON users(user_role);

-- IMPORTANT: Set YOUR email as admin
-- Replace 'jjwoods@gmail.com' with your actual email if different
UPDATE users
SET user_role = 'admin'
WHERE email = 'jjwoods@gmail.com';

-- Verify admin user was set
DO $$
DECLARE
    admin_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO admin_count FROM users WHERE user_role = 'admin';

    IF admin_count = 0 THEN
        RAISE WARNING 'No admin users found! Please update the email in this script.';
    ELSE
        RAISE NOTICE 'Successfully set % admin user(s)', admin_count;
    END IF;
END $$;
