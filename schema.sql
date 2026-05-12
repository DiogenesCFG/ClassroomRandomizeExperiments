CREATE TABLE IF NOT EXISTS survey (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_number    INTEGER NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    question_type   TEXT NOT NULL CHECK (question_type IN ('numeric', 'multiple_choice')),
    password_hash   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_active       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS survey_arm (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id       INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    arm_index       INTEGER NOT NULL,
    label           TEXT NOT NULL,
    question_text   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_survey_arm_unique ON survey_arm(survey_id, arm_index);

CREATE TABLE IF NOT EXISTS arm_option (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    arm_id          INTEGER NOT NULL REFERENCES survey_arm(id) ON DELETE CASCADE,
    option_index    INTEGER NOT NULL,
    option_text     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_arm_option_unique ON arm_option(arm_id, option_index);

CREATE TABLE IF NOT EXISTS group_member (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id       INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    sis_code        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS participant (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    student_id      TEXT NOT NULL UNIQUE,
    logged_in_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS response (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id  INTEGER NOT NULL REFERENCES participant(id),
    survey_id       INTEGER NOT NULL REFERENCES survey(id),
    arm_id          INTEGER NOT NULL REFERENCES survey_arm(id),
    answer_text     TEXT,
    answer_index    INTEGER,
    answered_at     TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_response_unique ON response(participant_id, survey_id);
