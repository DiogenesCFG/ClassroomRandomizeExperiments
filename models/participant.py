from models.db import get_db


def login_or_create(name, student_id):
    """Log in an existing participant or create a new one. Returns participant dict."""
    db = get_db()
    row = db.execute('SELECT * FROM participant WHERE student_id=?', (student_id,)).fetchone()
    if row:
        # Update name in case it changed
        db.execute('UPDATE participant SET name=? WHERE id=?', (name, row['id']))
        db.commit()
        return dict(db.execute('SELECT * FROM participant WHERE id=?', (row['id'],)).fetchone())

    cursor = db.execute(
        'INSERT INTO participant (name, student_id) VALUES (?, ?)',
        (name, student_id),
    )
    db.commit()
    return dict(db.execute('SELECT * FROM participant WHERE id=?', (cursor.lastrowid,)).fetchone())


def get_participant(participant_id):
    db = get_db()
    row = db.execute('SELECT * FROM participant WHERE id=?', (participant_id,)).fetchone()
    return dict(row) if row else None


def count_participants():
    db = get_db()
    row = db.execute('SELECT COUNT(*) as cnt FROM participant').fetchone()
    return row['cnt']
