-- ZIP code for best-effort local sports broadcast / in-market detection.
ALTER TABLE notification_preferences ADD COLUMN IF NOT EXISTS zip_code text;
