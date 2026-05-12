import hashlib

from models.db import get_db


def _hash_password(password):
    """Simple hash for survey edit passwords."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def check_password(survey_id, password):
    """Check if the password matches the survey's stored hash."""
    db = get_db()
    row = db.execute('SELECT password_hash FROM survey WHERE id=?', (survey_id,)).fetchone()
    if not row:
        return False
    return row['password_hash'] == _hash_password(password)


def create_survey(title, group_number, question_type, password, arms, members):
    """
    Create a survey with arms, options, and group members.

    arms: list of dicts, each with 'label', 'question_text', and optionally 'options' (list of strings)
    members: list of dicts, each with 'name' and 'sis_code'
    """
    db = get_db()
    cursor = db.execute(
        'INSERT INTO survey (title, group_number, question_type, password_hash) VALUES (?, ?, ?, ?)',
        (title, group_number, question_type, _hash_password(password)),
    )
    survey_id = cursor.lastrowid

    for i, arm in enumerate(arms):
        arm_cursor = db.execute(
            'INSERT INTO survey_arm (survey_id, arm_index, label, question_text) VALUES (?, ?, ?, ?)',
            (survey_id, i, arm['label'], arm['question_text']),
        )
        arm_id = arm_cursor.lastrowid

        if question_type == 'multiple_choice' and 'options' in arm:
            for j, option_text in enumerate(arm['options']):
                if option_text.strip():
                    db.execute(
                        'INSERT INTO arm_option (arm_id, option_index, option_text) VALUES (?, ?, ?)',
                        (arm_id, j, option_text.strip()),
                    )

    for member in members:
        if member['name'].strip() and member['sis_code'].strip():
            db.execute(
                'INSERT INTO group_member (survey_id, name, sis_code) VALUES (?, ?, ?)',
                (survey_id, member['name'].strip(), member['sis_code'].strip()),
            )

    db.commit()
    return survey_id


def update_survey(survey_id, title, group_number, question_type, arms, members):
    """Update an existing survey, replacing all arms, options, and members."""
    db = get_db()

    db.execute('UPDATE survey SET title=?, group_number=?, question_type=? WHERE id=?',
               (title, group_number, question_type, survey_id))

    # Delete old arms (cascades to options) and members
    db.execute('DELETE FROM survey_arm WHERE survey_id=?', (survey_id,))
    db.execute('DELETE FROM group_member WHERE survey_id=?', (survey_id,))

    for i, arm in enumerate(arms):
        arm_cursor = db.execute(
            'INSERT INTO survey_arm (survey_id, arm_index, label, question_text) VALUES (?, ?, ?, ?)',
            (survey_id, i, arm['label'], arm['question_text']),
        )
        arm_id = arm_cursor.lastrowid

        if question_type == 'multiple_choice' and 'options' in arm:
            for j, option_text in enumerate(arm['options']):
                if option_text.strip():
                    db.execute(
                        'INSERT INTO arm_option (arm_id, option_index, option_text) VALUES (?, ?, ?)',
                        (arm_id, j, option_text.strip()),
                    )

    for member in members:
        if member['name'].strip() and member['sis_code'].strip():
            db.execute(
                'INSERT INTO group_member (survey_id, name, sis_code) VALUES (?, ?, ?)',
                (survey_id, member['name'].strip(), member['sis_code'].strip()),
            )

    db.commit()


def get_survey(survey_id):
    """Get a survey with its arms, options, and group members."""
    db = get_db()
    survey = db.execute('SELECT * FROM survey WHERE id=?', (survey_id,)).fetchone()
    if survey is None:
        return None

    survey = dict(survey)
    arms = db.execute(
        'SELECT * FROM survey_arm WHERE survey_id=? ORDER BY arm_index', (survey_id,)
    ).fetchall()

    survey['arms'] = []
    for arm in arms:
        arm_dict = dict(arm)
        options = db.execute(
            'SELECT * FROM arm_option WHERE arm_id=? ORDER BY option_index', (arm['id'],)
        ).fetchall()
        arm_dict['options'] = [dict(o) for o in options]
        survey['arms'].append(arm_dict)

    members = db.execute(
        'SELECT * FROM group_member WHERE survey_id=?', (survey_id,)
    ).fetchall()
    survey['members'] = [dict(m) for m in members]

    return survey


def list_surveys():
    """List all surveys ordered by group_number."""
    db = get_db()
    surveys = db.execute('SELECT * FROM survey ORDER BY group_number').fetchall()
    return [dict(s) for s in surveys]


def get_active_survey_id():
    """Get the ID of the currently active survey, or None."""
    db = get_db()
    row = db.execute('SELECT id FROM survey WHERE is_active=1').fetchone()
    return row['id'] if row else None


def activate_survey(survey_id):
    """Deactivate all surveys, then activate the given one."""
    db = get_db()
    db.execute('UPDATE survey SET is_active=0 WHERE is_active=1')
    db.execute('UPDATE survey SET is_active=1 WHERE id=?', (survey_id,))
    db.commit()


def deactivate_all():
    """Deactivate all surveys."""
    db = get_db()
    db.execute('UPDATE survey SET is_active=0 WHERE is_active=1')
    db.commit()


def get_next_survey_id(current_survey_id):
    """Get the next survey by group_number after the current one."""
    db = get_db()
    current = db.execute('SELECT group_number FROM survey WHERE id=?', (current_survey_id,)).fetchone()
    if current is None:
        return None
    nxt = db.execute(
        'SELECT id FROM survey WHERE group_number > ? ORDER BY group_number LIMIT 1',
        (current['group_number'],),
    ).fetchone()
    return nxt['id'] if nxt else None


def delete_survey(survey_id):
    """Delete a survey and all its related data."""
    db = get_db()
    db.execute('DELETE FROM survey WHERE id=?', (survey_id,))
    db.commit()
