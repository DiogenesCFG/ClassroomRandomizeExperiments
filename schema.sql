CREATE TABLE IF NOT EXISTS classroom (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    code                    TEXT NOT NULL UNIQUE,
    name                    TEXT NOT NULL,
    host_password_hash      TEXT NOT NULL,
    classroom_password_hash TEXT NOT NULL DEFAULT '',
    classroom_password_plain TEXT NOT NULL DEFAULT '',
    block_designers         INTEGER NOT NULL DEFAULT 0,
    max_groups_per_student  INTEGER DEFAULT NULL,
    max_group_size          INTEGER DEFAULT 5,       -- members per group (NULL = no limit)
    surveys_locked          INTEGER NOT NULL DEFAULT 0,
    feedback_open           INTEGER NOT NULL DEFAULT 0,  -- students can send peer comments
    feedback_released       INTEGER NOT NULL DEFAULT 0,  -- groups can read comments they received
    reviews_required        INTEGER NOT NULL DEFAULT 2,  -- required comments per student
    max_questions_per_survey INTEGER DEFAULT 3,          -- NULL = no limit (host is exempt)
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS survey (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    classroom_id    INTEGER NOT NULL REFERENCES classroom(id) ON DELETE CASCADE,
    group_number    INTEGER NOT NULL,
    title           TEXT NOT NULL,
    question_type   TEXT NOT NULL,
    password_hash   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_active       INTEGER NOT NULL DEFAULT 0,
    early_allowed   INTEGER NOT NULL DEFAULT 0,     -- host lets this group deploy before class
    early_open      INTEGER NOT NULL DEFAULT 0,     -- group submitted it: locked and answerable from the lobby
    early_deadline_utc   TEXT DEFAULT NULL,         -- ISO UTC, end of the chosen day in the group's time zone
    early_deadline_label TEXT DEFAULT NULL,         -- the date as the group chose it, for display
    external        INTEGER NOT NULL DEFAULT 0,     -- the group runs it on another platform (e.g. Google Forms), randomizing and emailing it themselves
    external_note   TEXT DEFAULT NULL,              -- the group's note on how they run it
    went_live       INTEGER NOT NULL DEFAULT 0      -- activated in a live session at least once (opens it for comments)
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
    sis_code        TEXT NOT NULL,
    roster_student_id INTEGER DEFAULT NULL REFERENCES roster_student(id) ON DELETE SET NULL
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
    question_type   TEXT NOT NULL,
    label           TEXT NOT NULL DEFAULT '',
    slider_min      REAL DEFAULT NULL,
    slider_max      REAL DEFAULT NULL,
    slider_step     REAL DEFAULT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_survey_question_unique ON survey_question(survey_id, question_index);

CREATE TABLE IF NOT EXISTS arm_question (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    arm_id          INTEGER NOT NULL REFERENCES survey_arm(id) ON DELETE CASCADE,
    question_id     INTEGER NOT NULL REFERENCES survey_question(id) ON DELETE CASCADE,
    question_text   TEXT NOT NULL,
    image_filename  TEXT DEFAULT NULL
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

-- Class roster: students sign in with an SIS ID from this list and a password
-- they choose on first sign-in.
CREATE TABLE IF NOT EXISTS roster_student (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    classroom_id    INTEGER NOT NULL REFERENCES classroom(id) ON DELETE CASCADE,
    sis_id          TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    first_name      TEXT NOT NULL DEFAULT '',
    last_name       TEXT NOT NULL DEFAULT '',
    password_hash   TEXT DEFAULT NULL,
    registered_at   TEXT DEFAULT NULL,
    hidden          INTEGER NOT NULL DEFAULT 0,
    anon_id         TEXT DEFAULT NULL,  -- random respondent ID used in students' anonymized downloads
    tours_seen      TEXT NOT NULL DEFAULT '',  -- first-visit tours already shown, space-separated (e.g. "lobby builder")
    added_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_roster_student_unique ON roster_student(classroom_id, sis_id);

CREATE TABLE IF NOT EXISTS team_invite (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id         INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    roster_student_id INTEGER NOT NULL REFERENCES roster_student(id) ON DELETE CASCADE,
    invited_by        INTEGER REFERENCES roster_student(id) ON DELETE SET NULL,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_team_invite_unique ON team_invite(survey_id, roster_student_id);

-- Peer feedback: which groups each student must comment on (stable once made)
CREATE TABLE IF NOT EXISTS review_assignment (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    roster_student_id INTEGER NOT NULL REFERENCES roster_student(id) ON DELETE CASCADE,
    survey_id         INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_review_assignment_unique ON review_assignment(roster_student_id, survey_id);

-- Peer comments (sent_at NULL = private draft/note)
CREATE TABLE IF NOT EXISTS feedback (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id         INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    roster_student_id INTEGER NOT NULL REFERENCES roster_student(id) ON DELETE CASCADE,
    body              TEXT NOT NULL DEFAULT '',
    sent_at           TEXT DEFAULT NULL,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_unique ON feedback(survey_id, roster_student_id);
