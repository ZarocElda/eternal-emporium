CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(160) NOT NULL UNIQUE,
    title VARCHAR(200) NOT NULL,
    summary VARCHAR(500),
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'scheduled', 'published', 'archived')),
    visibility VARCHAR(20) NOT NULL DEFAULT 'public'
        CHECK (visibility IN ('public', 'hidden')),
    starts_at TIMESTAMP,
    ends_at TIMESTAMP,
    max_hints INTEGER NOT NULL DEFAULT 3 CHECK (max_hints BETWEEN 0 AND 20),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at)
);

CREATE INDEX IF NOT EXISTS events_discovery_idx
ON events (status, visibility, starts_at, ends_at);

CREATE TABLE IF NOT EXISTS event_stages (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position > 0),
    title VARCHAR(200) NOT NULL,
    description TEXT,
    unlock_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (event_id, position)
);

CREATE TABLE IF NOT EXISTS event_puzzles (
    id SERIAL PRIMARY KEY,
    stage_id INTEGER NOT NULL REFERENCES event_stages(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position > 0),
    title VARCHAR(200) NOT NULL,
    puzzle_type VARCHAR(40) NOT NULL CHECK (
        puzzle_type IN (
            'code', 'password', 'trivia', 'ordering', 'image_hotspot',
            'scavenger', 'hidden_clue', 'interactive'
        )
    ),
    prompt TEXT,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    solution JSONB NOT NULL DEFAULT '{}'::jsonb,
    hints JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stage_id, position)
);

CREATE TABLE IF NOT EXISTS event_rewards (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    reward_type VARCHAR(30) NOT NULL
        CHECK (reward_type IN ('points', 'manual_prize')),
    points_amount INTEGER CHECK (points_amount IS NULL OR points_amount >= 0),
    prize_name VARCHAR(255),
    fulfillment_instructions TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (event_id, reward_type),
    CHECK (
        (reward_type = 'points' AND points_amount IS NOT NULL)
        OR (reward_type = 'manual_prize' AND prize_name IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS event_participations (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_activity_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    UNIQUE (event_id, user_id)
);

CREATE TABLE IF NOT EXISTS event_puzzle_progress (
    id SERIAL PRIMARY KEY,
    participation_id INTEGER NOT NULL
        REFERENCES event_participations(id) ON DELETE CASCADE,
    puzzle_id INTEGER NOT NULL REFERENCES event_puzzles(id) ON DELETE CASCADE,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    solved_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (participation_id, puzzle_id)
);

CREATE TABLE IF NOT EXISTS event_journal_entries (
    id SERIAL PRIMARY KEY,
    participation_id INTEGER NOT NULL
        REFERENCES event_participations(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_hint_usage (
    id SERIAL PRIMARY KEY,
    participation_id INTEGER NOT NULL
        REFERENCES event_participations(id) ON DELETE CASCADE,
    puzzle_id INTEGER NOT NULL REFERENCES event_puzzles(id) ON DELETE CASCADE,
    hint_number INTEGER NOT NULL CHECK (hint_number BETWEEN 1 AND 20),
    used_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (participation_id, puzzle_id, hint_number)
);

CREATE TABLE IF NOT EXISTS event_completions (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    participation_id INTEGER NOT NULL
        REFERENCES event_participations(id) ON DELETE CASCADE,
    completed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    elapsed_seconds INTEGER CHECK (elapsed_seconds IS NULL OR elapsed_seconds >= 0),
    hints_used INTEGER NOT NULL DEFAULT 0 CHECK (hints_used >= 0),
    UNIQUE (event_id, user_id),
    UNIQUE (participation_id)
);

CREATE TABLE IF NOT EXISTS event_reward_grants (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    completion_id INTEGER NOT NULL REFERENCES event_completions(id) ON DELETE CASCADE,
    reward_id INTEGER NOT NULL REFERENCES event_rewards(id) ON DELETE CASCADE,
    points_granted INTEGER NOT NULL DEFAULT 0 CHECK (points_granted >= 0),
    fulfillment_status VARCHAR(30) NOT NULL DEFAULT 'not_applicable'
        CHECK (fulfillment_status IN ('not_applicable', 'pending', 'fulfilled')),
    fulfilled_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    fulfilled_at TIMESTAMP,
    granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, event_id, reward_id)
);

CREATE INDEX IF NOT EXISTS event_leaderboard_idx
ON event_completions (event_id, completed_at, elapsed_seconds, hints_used);
