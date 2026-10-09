ALTER TABLE turns ADD COLUMN input_mode TEXT NOT NULL DEFAULT 'text' CHECK (input_mode IN ('text', 'voice'));
ALTER TABLE turns ADD COLUMN speech_ms INTEGER;
ALTER TABLE turns ADD COLUMN first_word_delay_ms INTEGER;
ALTER TABLE turns ADD COLUMN wpm INTEGER;
ALTER TABLE turns ADD COLUMN filler_count INTEGER;
