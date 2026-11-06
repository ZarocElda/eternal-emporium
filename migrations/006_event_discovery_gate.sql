ALTER TABLE event_clue_placements
ADD COLUMN IF NOT EXISTS entry_token VARCHAR(80);

UPDATE event_clue_placements
SET entry_token = md5(random()::text || clock_timestamp()::text || id::text)
WHERE entry_token IS NULL;

ALTER TABLE event_clue_placements
ALTER COLUMN entry_token SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS event_clue_placements_entry_token_idx
ON event_clue_placements (entry_token);

CREATE TABLE IF NOT EXISTS event_discoveries (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    placement_id INTEGER REFERENCES event_clue_placements(id) ON DELETE SET NULL,
    discovered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (event_id, user_id)
);
