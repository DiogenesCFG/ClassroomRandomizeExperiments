import hashlib

from models.db import get_db


def _hash_password(password):
    """Hash a classroom host password with SHA-256."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def create_classroom(code, name, host_password, classroom_password, max_groups_per_student=None):
    """Create a new classroom. Returns the classroom dict."""
    db = get_db()
    cursor = db.execute(
        'INSERT INTO classroom (code, name, host_password_hash, classroom_password_hash, classroom_password_plain, '
        'max_groups_per_student) VALUES (?, ?, ?, ?, ?, ?)',
        (code.upper().strip(), name.strip(), _hash_password(host_password),
         _hash_password(classroom_password), classroom_password, max_groups_per_student),
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
    # arm_question_option, survey_question, participant, group_member,
    # roster_student, team_invite
    db.execute('DELETE FROM classroom WHERE id=?', (classroom_id,))
    db.commit()

    return image_filenames


def set_max_groups(classroom_id, max_groups):
    """Set the per-student group limit (None = no limit)."""
    db = get_db()
    db.execute('UPDATE classroom SET max_groups_per_student=? WHERE id=?', (max_groups, classroom_id))
    db.commit()


def set_max_group_size(classroom_id, size):
    """Set the members-per-group limit (None = no limit)."""
    db = get_db()
    db.execute('UPDATE classroom SET max_group_size=? WHERE id=?', (size, classroom_id))
    db.commit()


def parse_max_group_size(value):
    """Parse a max-members form value. Returns (value_or_None, error_or_None)."""
    value = (value or '').strip()
    if not value:
        return None, None
    if not value.isdigit() or int(value) < 1:
        return None, 'Max members per group must be a whole number of at least 1 (or empty for no limit).'
    return int(value), None


def parse_max_groups(value):
    """Parse a max-groups form value. Returns (value_or_None, error_or_None)."""
    value = (value or '').strip()
    if not value:
        return None, None
    if not value.isdigit() or int(value) < 1:
        return None, 'Max groups per student must be a whole number of at least 1 (or empty for no limit).'
    return int(value), None
