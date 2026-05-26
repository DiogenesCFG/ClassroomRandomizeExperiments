import hashlib

from models.db import get_db


def _hash_password(password):
    """Hash a classroom host password with SHA-256."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def create_classroom(code, name, host_password, classroom_password):
    """Create a new classroom. Returns the classroom dict."""
    db = get_db()
    cursor = db.execute(
        'INSERT INTO classroom (code, name, host_password_hash, classroom_password_hash, classroom_password_plain) '
        'VALUES (?, ?, ?, ?, ?)',
        (code.upper().strip(), name.strip(), _hash_password(host_password),
         _hash_password(classroom_password), classroom_password),
    )
    db.commit()
    row = db.execute('SELECT * FROM classroom WHERE id=?', (cursor.lastrowid,)).fetchone()
    return dict(row)


def get_classroom_by_code(code):
    """Look up a classroom by its code. Returns dict or None."""
    db = get_db()
    row = db.execute('SELECT * FROM classroom WHERE code=?', (code.upper().strip(),)).fetchone()
    return dict(row) if row else None


def check_host_password(classroom_id, password):
    """Check if the password matches the classroom's host password hash."""
    db = get_db()
    row = db.execute('SELECT host_password_hash FROM classroom WHERE id=?', (classroom_id,)).fetchone()
    if not row:
        return False
    return row['host_password_hash'] == _hash_password(password)


def check_classroom_password(classroom_id, password):
    """Check if the password matches the classroom's student-facing password hash."""
    db = get_db()
    row = db.execute('SELECT classroom_password_hash FROM classroom WHERE id=?', (classroom_id,)).fetchone()
    if not row:
        return False
    return row['classroom_password_hash'] == _hash_password(password)


def get_classroom(classroom_id):
    """Get a classroom by ID. Returns dict or None."""
    db = get_db()
    row = db.execute('SELECT * FROM classroom WHERE id=?', (classroom_id,)).fetchone()
    return dict(row) if row else None


def delete_classroom(classroom_id):
    """Delete a classroom and all related data.

    Returns a list of image filenames that the caller should remove from disk.
    """
    db = get_db()

    # Collect image filenames before cascade deletes the rows
    images = db.execute(
        'SELECT DISTINCT aq.image_filename FROM arm_question aq '
        'JOIN survey_arm sa ON aq.arm_id = sa.id '
        'JOIN survey s ON sa.survey_id = s.id '
        'WHERE s.classroom_id = ? AND aq.image_filename IS NOT NULL',
        (classroom_id,),
    ).fetchall()
    image_filenames = [r['image_filename'] for r in images]

    # Delete responses first (no ON DELETE CASCADE on this table)
    db.execute(
        'DELETE FROM response WHERE survey_id IN '
        '(SELECT id FROM survey WHERE classroom_id=?)',
        (classroom_id,),
    )

    # Delete classroom — cascades to survey, survey_arm, arm_question,
    # arm_question_option, survey_question, participant, group_member
    db.execute('DELETE FROM classroom WHERE id=?', (classroom_id,))
    db.commit()

    return image_filenames
