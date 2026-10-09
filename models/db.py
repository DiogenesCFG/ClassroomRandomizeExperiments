import os
import sqlite3

import click
from flask import current_app, g


def get_db():
    """Get a database connection for the current request context."""
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA busy_timeout=5000')
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def get_socket_db():
    """Get a database connection for SocketIO event handlers (no request context)."""
    db = sqlite3.connect(
        current_app.config['DATABASE'],
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=5000')
    db.execute('PRAGMA foreign_keys=ON')
    return db


def init_db():
    """Initialize the database from schema.sql and run migrations."""
    db_path = current_app.config['DATABASE']
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = get_db()
    db.execute('PRAGMA journal_mode=WAL')
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'schema.sql')
    with open(schema_path, 'r') as f:
        db.executescript(f.read())

    # Migrations: add columns that may not exist in older databases
    try:
        db.execute('ALTER TABLE survey ADD COLUMN password_hash TEXT NOT NULL DEFAULT ""')
        db.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        db.execute('ALTER TABLE survey ADD COLUMN classroom_id INTEGER NOT NULL DEFAULT 0')
        db.commit()
    except sqlite3.OperationalError:
        pass

    try:
        db.execute('ALTER TABLE participant ADD COLUMN classroom_id INTEGER NOT NULL DEFAULT 0')
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: classroom password for student access
    try:
        db.execute("ALTER TABLE classroom ADD COLUMN classroom_password_hash TEXT NOT NULL DEFAULT ''")
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: block_designers flag on classroom
    try:
        db.execute('ALTER TABLE classroom ADD COLUMN block_designers INTEGER NOT NULL DEFAULT 0')
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: store classroom password in plaintext for display
    try:
        db.execute("ALTER TABLE classroom ADD COLUMN classroom_password_plain TEXT NOT NULL DEFAULT ''")
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: image uploads for arm questions
    try:
        db.execute('ALTER TABLE arm_question ADD COLUMN image_filename TEXT DEFAULT NULL')
        db.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: multi-question support
    try:
        db.execute('ALTER TABLE response ADD COLUMN question_id INTEGER REFERENCES survey_question(id)')
        db.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migrate existing single-question data to multi-question tables
    question_count = db.execute(
        "SELECT COUNT(*) as cnt FROM survey_question"
    ).fetchone()['cnt']

    if question_count == 0:
        surveys = db.execute('SELECT id, question_type FROM survey').fetchall()
        for survey in surveys:
            cursor = db.execute(
                'INSERT INTO survey_question (survey_id, question_index, question_type, label) '
                'VALUES (?, 0, ?, ?)',
                (survey['id'], survey['question_type'], '')
            )
            question_id = cursor.lastrowid

            arms = db.execute(
                'SELECT id, question_text FROM survey_arm WHERE survey_id=?',
                (survey['id'],)
            ).fetchall()
            for arm in arms:
                aq_cursor = db.execute(
                    'INSERT INTO arm_question (arm_id, question_id, question_text) VALUES (?, ?, ?)',
                    (arm['id'], question_id, arm['question_text'])
                )
                aq_id = aq_cursor.lastrowid

                options = db.execute(
                    'SELECT option_index, option_text FROM arm_option WHERE arm_id=? ORDER BY option_index',
                    (arm['id'],)
                ).fetchall()
                for opt in options:
                    db.execute(
                        'INSERT INTO arm_question_option (arm_question_id, option_index, option_text) '
                        'VALUES (?, ?, ?)',
                        (aq_id, opt['option_index'], opt['option_text'])
                    )

            # Backfill response.question_id for existing responses
            db.execute(
                'UPDATE response SET question_id=? WHERE survey_id=? AND question_id IS NULL',
                (question_id, survey['id'])
            )

        db.commit()

    # Replace old unique index with multi-question version
    try:
        db.execute('DROP INDEX idx_response_unique')
        db.commit()
    except sqlite3.OperationalError:
        pass
    try:
        db.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_response_unique_mq '
            'ON response(participant_id, survey_id, question_id)'
        )
        db.commit()
    except sqlite3.OperationalError:
        pass

    for sql in (
        'CREATE INDEX IF NOT EXISTS idx_response_survey_arm_question '
        'ON response(survey_id, arm_id, question_id)',
        'CREATE INDEX IF NOT EXISTS idx_survey_active_classroom '
        'ON survey(classroom_id, is_active)',
        'CREATE INDEX IF NOT EXISTS idx_participant_classroom '
        'ON participant(classroom_id)',
    ):
        try:
            db.execute(sql)
            db.commit()
        except sqlite3.OperationalError:
            pass

    # Migration: add slider config columns to survey_question
    for col, col_def in (
        ('slider_min', 'REAL DEFAULT NULL'),
        ('slider_max', 'REAL DEFAULT NULL'),
        ('slider_step', 'REAL DEFAULT NULL'),
    ):
        try:
            db.execute(f'ALTER TABLE survey_question ADD COLUMN {col} {col_def}')
            db.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Migration: class roster, per-student group limit, survey edit lock, anonymized IDs
    for table, col, col_def in (
        ('classroom', 'max_groups_per_student', 'INTEGER DEFAULT NULL'),
        ('classroom', 'max_group_size', 'INTEGER DEFAULT 5'),
        ('classroom', 'surveys_locked', 'INTEGER NOT NULL DEFAULT 0'),
        ('group_member', 'roster_student_id',
         'INTEGER DEFAULT NULL REFERENCES roster_student(id) ON DELETE SET NULL'),
        ('roster_student', 'anon_id', 'TEXT DEFAULT NULL'),
        ('roster_student', 'tours_seen', "TEXT NOT NULL DEFAULT ''"),
        ('classroom', 'feedback_open', 'INTEGER NOT NULL DEFAULT 0'),
        ('classroom', 'feedback_released', 'INTEGER NOT NULL DEFAULT 0'),
        ('classroom', 'reviews_required', 'INTEGER NOT NULL DEFAULT 2'),
        ('classroom', 'max_questions_per_survey', 'INTEGER DEFAULT 3'),
        ('arm_question', 'allow_other', 'INTEGER NOT NULL DEFAULT 0'),
        ('response', 'seconds', 'REAL DEFAULT NULL'),
        ('response', 'left_page', 'INTEGER DEFAULT NULL'),
        ('response', 'other_text', 'TEXT DEFAULT NULL'),
        ('response', 'timed_out', 'INTEGER DEFAULT NULL'),
        ('arm_question', 'timer_seconds', 'INTEGER DEFAULT NULL'),
        ('survey_question', 'show_arms', 'TEXT DEFAULT NULL'),
        ('survey_question', 'cond_question', 'INTEGER DEFAULT NULL'),
        ('survey_question', 'cond_values', 'TEXT DEFAULT NULL'),
        ('arm_question', 'timer_display', 'TEXT DEFAULT NULL'),
        ('arm_question', 'timer_default', 'TEXT DEFAULT NULL'),
        ('survey', 'early_allowed', 'INTEGER NOT NULL DEFAULT 0'),
        ('survey', 'early_open', 'INTEGER NOT NULL DEFAULT 0'),
        ('survey', 'early_deadline_utc', 'TEXT DEFAULT NULL'),
        ('survey', 'early_deadline_label', 'TEXT DEFAULT NULL'),
        ('survey', 'external', 'INTEGER NOT NULL DEFAULT 0'),
        ('survey', 'external_note', 'TEXT DEFAULT NULL'),
        ('survey', 'part2_from', 'INTEGER DEFAULT NULL'),
        ('survey', 'part1_when', 'TEXT DEFAULT NULL'),
        ('survey', 'part2_when', 'TEXT DEFAULT NULL'),
        ('survey', 'part1_open_date', 'TEXT DEFAULT NULL'),
        ('survey', 'part1_close_date', 'TEXT DEFAULT NULL'),
        ('survey', 'part1_open_utc', 'TEXT DEFAULT NULL'),
        ('survey', 'part1_close_utc', 'TEXT DEFAULT NULL'),
        ('survey', 'active_part', 'INTEGER DEFAULT NULL'),
        ('survey', 'part2_ran', 'TEXT DEFAULT NULL'),
        ('survey', 'part2_open_date', 'TEXT DEFAULT NULL'),
        ('survey', 'part2_close_date', 'TEXT DEFAULT NULL'),
        ('survey', 'part2_open_utc', 'TEXT DEFAULT NULL'),
        ('survey', 'part2_close_utc', 'TEXT DEFAULT NULL'),
        ('survey', 'part2_time', 'TEXT DEFAULT NULL'),
        ('survey', 'reminder_plan', 'TEXT DEFAULT NULL'),
        ('survey', 'reminders_approved', 'TEXT DEFAULT NULL'),
        ('classroom', 'reminders_until', 'TEXT DEFAULT NULL'),
    ):
        try:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {col} {col_def}')
            db.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
    try:
        db.execute('ALTER TABLE survey ADD COLUMN went_live INTEGER NOT NULL DEFAULT 0')
        # Surveys that already ran (active now or have answers) count as having gone live
        db.execute('UPDATE survey SET went_live=1 WHERE is_active=1 OR id IN (SELECT DISTINCT survey_id FROM response)')
        db.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        db.execute('ALTER TABLE survey ADD COLUMN part1_ran TEXT DEFAULT NULL')
        # Surveys that already ran live count as run, so the live sequence won't start them again
        db.execute("UPDATE survey SET part1_ran=datetime('now') WHERE went_live=1")
        db.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    db.execute('CREATE INDEX IF NOT EXISTS idx_group_member_roster ON group_member(roster_student_id)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_roster_student_anon ON roster_student(anon_id)')
    db.commit()
    from models.roster import backfill_anon_ids
    backfill_anon_ids(db)

    # Migration: remove CHECK constraint on question_type to allow new types
    # (short_answer, multiple_answer). SQLite can't ALTER constraints, so we
    # recreate the tables if they still have the old CHECK.
    for table in ('survey', 'survey_question'):
        table_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if table_sql and 'multiple_choice' in table_sql['sql'] and 'CHECK' in table_sql['sql']:
            # Table has the old CHECK constraint — recreate without it
            cols = db.execute(f'PRAGMA table_info({table})').fetchall()
            col_names = ', '.join(c['name'] for c in cols)
            db.execute(f'ALTER TABLE {table} RENAME TO {table}_old')
            # Re-run schema to create the new table (without CHECK)
            db.executescript(open(schema_path, 'r').read())
            db.execute(f'INSERT INTO {table} ({col_names}) SELECT {col_names} FROM {table}_old')
            db.execute(f'DROP TABLE {table}_old')
            db.commit()


@click.command('init-db')
def init_db_command():
    """CLI command: flask init-db"""
    init_db()
    click.echo('Database initialized.')
