CREATE TABLE IF NOT EXISTS event_clue_placements (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    page_scope VARCHAR(30) NOT NULL DEFAULT 'store'
        CHECK (page_scope IN ('global', 'store', 'dashboard', 'profile', 'purchases')),
    placement_zone VARCHAR(40) NOT NULL DEFAULT 'content_top'
        CHECK (placement_zone IN ('content_top', 'theme_banner_hotspot', 'floating_corner', 'footer')),
    display_type VARCHAR(30) NOT NULL DEFAULT 'text'
        CHECK (display_type IN ('text', 'image', 'invisible_hotspot')),
    label VARCHAR(255),
    tooltip VARCHAR(255),
    position_x NUMERIC(5,2) NOT NULL DEFAULT 50 CHECK (position_x BETWEEN 0 AND 100),
    position_y NUMERIC(5,2) NOT NULL DEFAULT 50 CHECK (position_y BETWEEN 0 AND 100),
    width_percent NUMERIC(5,2) NOT NULL DEFAULT 12 CHECK (width_percent BETWEEN 1 AND 100),
    height_percent NUMERIC(5,2) NOT NULL DEFAULT 18 CHECK (height_percent BETWEEN 1 AND 100),
    image_filename VARCHAR(255),
    image_content_type VARCHAR(100),
    image_data BYTEA,
    starts_at TIMESTAMP,
    ends_at TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at)
);

CREATE INDEX IF NOT EXISTS event_clue_placements_active_idx
ON event_clue_placements (is_active, page_scope, starts_at, ends_at);
