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
    reminders_until         TEXT DEFAULT NULL,           -- yyyy-mm-dd: latest date for reminders and part 2 (NULL = no limit)
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
    went_live       INTEGER NOT NULL DEFAULT 0,     -- activated in a live session at least once (opens it for comments)
    part2_from      INTEGER DEFAULT NULL,           -- two-part survey: index of the first part-2 question (NULL = one part)
    part1_when      TEXT DEFAULT NULL,              -- two-part: 'live' (live session, default) | 'class' (launched separately) | 'remote' (lobby, dates)
    part2_when      TEXT DEFAULT NULL,              -- same, default 'remote'
    part1_open_date TEXT DEFAULT NULL,              -- remote part: yyyy-mm-dd as the group chose it
    part1_close_date TEXT DEFAULT NULL,
    part1_open_utc  TEXT DEFAULT NULL,              -- ISO UTC, start of the open date in the group's time zone
    part1_close_utc TEXT DEFAULT NULL,              -- ISO UTC, end of the close date
    part2_open_date TEXT DEFAULT NULL,
    part2_close_date TEXT DEFAULT NULL,
    part2_open_utc  TEXT DEFAULT NULL,
    part2_close_utc TEXT DEFAULT NULL,
    part2_time      TEXT DEFAULT NULL,              -- HH:MM of the "part 2 is open" calendar reminder (remote part 2)
    active_part     INTEGER DEFAULT NULL,           -- the part running while is_active
    part1_ran       TEXT DEFAULT NULL,              -- when each part was first activated (the live sequence skips it)
    part2_ran       TEXT DEFAULT NULL,
    reminder_plan   TEXT DEFAULT NULL,              -- JSON {"arms": [{"note", "rules": [{message, start, end, every, time}]}]}
    reminders_approved TEXT DEFAULT NULL            -- hash of the plan the instructor approved
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
    slider_step     REAL DEFAULT NULL,
    show_arms       TEXT DEFAULT NULL,      -- JSON list of arm positions that see it (NULL = all arms)
    cond_question   INTEGER DEFAULT NULL,   -- shown only if this earlier question (index) ...
    cond_values     TEXT DEFAULT NULL       -- ... was answered with one of these (JSON list)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_survey_question_unique ON survey_question(survey_id, question_index);

CREATE TABLE IF NOT EXISTS arm_question (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    arm_id          INTEGER NOT NULL REFERENCES survey_arm(id) ON DELETE CASCADE,
    question_id     INTEGER NOT NULL REFERENCES survey_question(id) ON DELETE CASCADE,
    question_text   TEXT NOT NULL,
    image_filename  TEXT DEFAULT NULL,
    allow_other     INTEGER NOT NULL DEFAULT 0,  -- choice questions: adds an "Other" choice with a text box
    timer_seconds   INTEGER DEFAULT NULL,        -- time limit for this arm's version (NULL = no timer)
    timer_display   TEXT DEFAULT NULL,           -- 'both' | 'countdown' | 'bar' | 'hidden'
    timer_default   TEXT DEFAULT NULL            -- answer recorded if time runs out ('' = no answer)
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
    answered_at     TEXT DEFAULT (datetime('now')),
    seconds         REAL DEFAULT NULL,      -- time the question was on screen (page in view)
    left_page       INTEGER DEFAULT NULL,   -- 1 if the respondent switched away while on it
    other_text      TEXT DEFAULT NULL,      -- what they typed after choosing "Other"
    timed_out       INTEGER DEFAULT NULL    -- 1 if the question's timer ran out (the default was recorded)
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
-- Group finder (opt-in): roster_student.seeking_group = 1 lists the student for classmates without a group
-- (columns seeking_group, seeking_note are added by the migrations in models/db.py)

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

-- Calendar reminders: each download of the .ics file, tap on a Google Calendar link, or "Done"
CREATE TABLE IF NOT EXISTS reminder_action (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id      INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    participant_id INTEGER NOT NULL REFERENCES participant(id) ON DELETE CASCADE,
    arm_index      INTEGER,
    method         TEXT NOT NULL,     -- ics | google | done
    item           TEXT,              -- which reminder (Google links: rule number, or p2)
    device         TEXT,              -- ios | android | desktop, as detected by the phone's browser
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reminder_action_survey ON reminder_action(survey_id, participant_id);

-- Push notifications: a phone's browser subscription for one survey's reminders, and each message to send
CREATE TABLE IF NOT EXISTS push_subscription (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    survey_id      INTEGER NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
    participant_id INTEGER NOT NULL REFERENCES participant(id) ON DELETE CASCADE,
    arm_index      INTEGER,
    endpoint       TEXT NOT NULL,
    p256dh         TEXT NOT NULL,
    auth           TEXT NOT NULL,
    tz             TEXT,              -- the phone's time zone (for reminders without one)
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_push_subscription_unique ON push_subscription(survey_id, participant_id, endpoint);
CREATE TABLE IF NOT EXISTS push_message (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL REFERENCES push_subscription(id) ON DELETE CASCADE,
    item            TEXT NOT NULL,     -- rule number, or p2
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    send_at         TEXT NOT NULL,     -- ISO UTC
    status          TEXT NOT NULL DEFAULT 'pending',   -- pending | sending | sent | failed | missed | cancelled
    attempts        INTEGER NOT NULL DEFAULT 0,
    sent_at         TEXT,
    clicked_at      TEXT,
    token           TEXT NOT NULL,     -- in the notification's link, to record the tap
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_push_message_due ON push_message(status, send_at);

-- Server-wide settings (e.g. the push notification keys)
CREATE TABLE IF NOT EXISTS app_setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
