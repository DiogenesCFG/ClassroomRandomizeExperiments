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


@click.command('init-db')
def init_db_command():
    """CLI command: flask init-db"""
    init_db()
    click.echo('Database initialized.')
