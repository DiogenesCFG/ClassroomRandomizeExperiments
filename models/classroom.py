import hashlib

from models.db import get_db


def _hash_password(password):
    """Hash a classroom host password with SHA-256."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def create_classroom(code, name, host_password):
    """Create a new classroom. Returns the classroom dict."""
    db = get_db()
    cursor = db.execute(
        'INSERT INTO classroom (code, name, host_password_hash) VALUES (?, ?, ?)',
        (code.upper().strip(), name.strip(), _hash_password(host_password)),
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


def get_classroom(classroom_id):
    """Get a classroom by ID. Returns dict or None."""
    db = get_db()
    row = db.execute('SELECT * FROM classroom WHERE id=?', (classroom_id,)).fetchone()
    return dict(row) if row else None
