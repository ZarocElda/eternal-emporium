ALTER TABLE event_clue_placements
ADD COLUMN IF NOT EXISTS target_puzzle_id INTEGER REFERENCES event_puzzles(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS event_clue_placements_target_puzzle_idx
ON event_clue_placements (target_puzzle_id);
