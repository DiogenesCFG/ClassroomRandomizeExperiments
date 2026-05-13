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
        g.db.execute('PRAGMA journal_mode=WAL')
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
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=5000')
    db.execute('PRAGMA foreign_keys=ON')
    return db


def init_db():
    """Initialize the database from schema.sql and run migrations."""
    db_path = current_app.config['DATABASE']
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = get_db()
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


@click.command('init-db')
def init_db_command():
    """CLI command: flask init-db"""
    init_db()
    click.echo('Database initialized.')
