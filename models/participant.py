from models.db import get_db


def login_or_create(name, student_id, classroom_id):
    """Log in an existing participant or create a new one. Returns participant dict."""
    db = get_db()
    row = db.execute(
        'SELECT * FROM participant WHERE student_id=? AND classroom_id=?',
        (student_id, classroom_id),
    ).fetchone()
    if row:
        # Update name in case it changed
        db.execute('UPDATE participant SET name=? WHERE id=?', (name, row['id']))
        db.commit()
        return dict(db.execute('SELECT * FROM participant WHERE id=?', (row['id'],)).fetchone())

    cursor = db.execute(
        'INSERT INTO participant (name, student_id, classroom_id) VALUES (?, ?, ?)',
        (name, student_id, classroom_id),
    )
    db.commit()
    return dict(db.execute('SELECT * FROM participant WHERE id=?', (cursor.lastrowid,)).fetchone())


def get_participant(participant_id):
    db = get_db()
    row = db.execute('SELECT * FROM participant WHERE id=?', (participant_id,)).fetchone()
    return dict(row) if row else None


def count_participants(classroom_id):
    db = get_db()
    row = db.execute(
        'SELECT COUNT(*) as cnt FROM participant WHERE classroom_id=?', (classroom_id,)
    ).fetchone()
    return row['cnt']
