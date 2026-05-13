CREATE TABLE IF NOT EXISTS classroom (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    code               TEXT NOT NULL UNIQUE,
    name               TEXT NOT NULL,
    host_password_hash TEXT NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS survey (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    classroom_id    INTEGER NOT NULL REFERENCES classroom(id) ON DELETE CASCADE,
    group_number    INTEGER NOT NULL,
    title           TEXT NOT NULL,
    question_type   TEXT NOT NULL CHECK (question_type IN ('numeric', 'multiple_choice')),
    password_hash   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_active       INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_survey_group_classroom ON survey(classroom_id, group_number);

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
    classroom_id    INTEGER NOT NULL REFERENCES classroom(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    student_id      TEXT NOT NULL,
    logged_in_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_participant_unique ON participant(student_id, classroom_id);

CREATE TABLE IF NOT EXISTS survey_question (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id       INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    question_index  INTEGER NOT NULL,
    question_type   TEXT NOT NULL CHECK (question_type IN ('numeric', 'multiple_choice')),
    label           TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_survey_question_unique ON survey_question(survey_id, question_index);

CREATE TABLE IF NOT EXISTS arm_question (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    arm_id          INTEGER NOT NULL REFERENCES survey_arm(id) ON DELETE CASCADE,
    question_id     INTEGER NOT NULL REFERENCES survey_question(id) ON DELETE CASCADE,
    question_text   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_arm_question_unique ON arm_question(arm_id, question_id);

CREATE TABLE IF NOT EXISTS arm_question_option (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    arm_question_id INTEGER NOT NULL REFERENCES arm_question(id) ON DELETE CASCADE,
    option_index    INTEGER NOT NULL,
    option_text     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_arm_question_option_unique ON arm_question_option(arm_question_id, option_index);

CREATE TABLE IF NOT EXISTS response (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id  INTEGER NOT NULL REFERENCES participant(id),
    survey_id       INTEGER NOT NULL REFERENCES survey(id),
    arm_id          INTEGER NOT NULL REFERENCES survey_arm(id),
    question_id     INTEGER REFERENCES survey_question(id),
    answer_text     TEXT,
    answer_index    INTEGER,
    answered_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_response_survey ON response(survey_id);
CREATE INDEX IF NOT EXISTS idx_response_survey_arm_question ON response(survey_id, arm_id, question_id);
CREATE INDEX IF NOT EXISTS idx_survey_active_classroom ON survey(classroom_id, is_active);
CREATE INDEX IF NOT EXISTS idx_participant_classroom ON participant(classroom_id);
