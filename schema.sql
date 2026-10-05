-- Hidden Gems database (PostgreSQL + pgvector). Safe to run again: everything is IF NOT EXISTS.
-- No audio is ever stored: only song details and the numbers the models produce.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS songs (
    song_key           text PRIMARY KEY,          -- e.g. jamendo_959961, audius_AbC12
    source             text NOT NULL,             -- jamendo | audius | local
    source_id          text NOT NULL,
    title              text,
    artist             text,
    album              text,
    duration_s         real,
    listens            bigint,                    -- popularity on its own site (for obscurity)
    licence            text,
    page               text,                      -- link to credit the artist
    vocal_instrumental text,                      -- Jamendo's own label, if any
    speed_label        text,                      -- Jamendo's own label, if any
    mtg_split          text,                      -- validation | train | test | NULL (not in MTG-Jamendo)
    test_group         text,                      -- which test list it came from
    added_at           timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS features (             -- one row per song: whole-song summaries
    song_key           text PRIMARY KEY REFERENCES songs ON DELETE CASCADE,
    analysis_version   int,
    analysed_at        timestamptz DEFAULT now(),
    file_duration_s    real,
    trimmed_duration_s real,
    full_length_ok     boolean,
    sound              vector(1280),              -- Discogs-EffNet, whole-song average
    instruments        vector(40),                -- 40 instrument likelihoods
    valence            real,                      -- emoMusic happiness, 1-9
    arousal            real,                      -- emoMusic energy, 1-9
    deam_valence       real,
    deam_arousal       real,
    p_happy            real, p_sad real, p_aggressive real, p_relaxed real,
    bpm                real,
    beat_confidence    real,                      -- 0-5.32
    steadiness         real,
    busyness           real,                      -- note onsets per second
    danceability       real,
    loudness_db        real,
    candidates         jsonb,                     -- candidate models under test (cand_*)
    timings            jsonb
);

CREATE TABLE IF NOT EXISTS song_parts (           -- the 3 x 30 s parts (25/50/75 %)
    song_key    text REFERENCES songs ON DELETE CASCADE,
    part        smallint,
    start_s     real,
    end_s       real,
    sound       vector(1280),
    instruments vector(40),
    valence     real,
    arousal     real,
    PRIMARY KEY (song_key, part)
);

CREATE TABLE IF NOT EXISTS song_tags (            -- human labels (MTG-Jamendo) used only for testing
    song_key text REFERENCES songs ON DELETE CASCADE,
    kind     text,                                -- genre | mood | instrument
    tag      text,
    PRIMARY KEY (song_key, kind, tag)
);

CREATE TABLE IF NOT EXISTS pool_versions (        -- rescaling numbers saved with every pool build
    id         serial PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    note       text,
    n_songs    int,
    scaling    jsonb
);

-- Added 3 Oct 2026 (safe to run again): the better mood model, release date, and songs taken out of the pool.
ALTER TABLE features ADD COLUMN IF NOT EXISTS vg_valence real;     -- VGGish -> emoMusic happiness (the chosen mood model)
ALTER TABLE features ADD COLUMN IF NOT EXISTS vg_arousal real;     -- VGGish -> emoMusic energy
ALTER TABLE songs    ADD COLUMN IF NOT EXISTS release_date text;
ALTER TABLE songs    ADD COLUMN IF NOT EXISTS excluded boolean DEFAULT false;   -- marked i_agree = n in a pool list
ALTER TABLE songs    ADD COLUMN IF NOT EXISTS in_pool boolean DEFAULT false;    -- listed in a pool list (a test song can be one too)
CREATE INDEX IF NOT EXISTS songs_group ON songs (test_group);

-- Fast "closest songs" search on the Sound numbers (cosine distance).
CREATE INDEX IF NOT EXISTS features_sound_hnsw ON features USING hnsw (sound vector_cosine_ops);
