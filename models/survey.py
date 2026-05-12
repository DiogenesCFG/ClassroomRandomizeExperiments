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


def create_survey(classroom_id, title, group_number, password, arms, questions, members):
    """
    Create a survey with arms, questions, and group members.

    arms: list of dicts, each with 'label'
    questions: list of dicts, each with 'question_type', 'label', and 'arms' dict
        where arms maps arm_index -> {'question_text': str, 'options': [str]}
    members: list of dicts, each with 'name' and 'sis_code'
    """
    db = get_db()

    # Use first question's type for legacy column
    first_type = questions[0]['question_type'] if questions else 'multiple_choice'
    cursor = db.execute(
        'INSERT INTO survey (classroom_id, title, group_number, question_type, password_hash) VALUES (?, ?, ?, ?, ?)',
        (classroom_id, title, group_number, first_type, _hash_password(password)),
    )
    survey_id = cursor.lastrowid

    # Create arms (just labels now)
    arm_ids = []
    for i, arm in enumerate(arms):
        # Legacy question_text: use first question's text for this arm
        legacy_text = ''
        if questions and i in questions[0].get('arms', {}):
            legacy_text = questions[0]['arms'][i].get('question_text', '')
        arm_cursor = db.execute(
            'INSERT INTO survey_arm (survey_id, arm_index, label, question_text) VALUES (?, ?, ?, ?)',
            (survey_id, i, arm['label'], legacy_text),
        )
        arm_ids.append(arm_cursor.lastrowid)

    # Create questions with per-arm texts and options
    for qi, question in enumerate(questions):
        q_cursor = db.execute(
            'INSERT INTO survey_question (survey_id, question_index, question_type, label) VALUES (?, ?, ?, ?)',
            (survey_id, qi, question['question_type'], question.get('label', '')),
        )
        question_id = q_cursor.lastrowid

        for ai, arm_id in enumerate(arm_ids):
            arm_data = question.get('arms', {}).get(ai, {})
            q_text = arm_data.get('question_text', '')
            aq_cursor = db.execute(
                'INSERT INTO arm_question (arm_id, question_id, question_text) VALUES (?, ?, ?)',
                (arm_id, question_id, q_text),
            )
            aq_id = aq_cursor.lastrowid

            if question['question_type'] == 'multiple_choice':
                for oi, opt_text in enumerate(arm_data.get('options', [])):
                    if opt_text.strip():
                        db.execute(
                            'INSERT INTO arm_question_option (arm_question_id, option_index, option_text) VALUES (?, ?, ?)',
                            (aq_id, oi, opt_text.strip()),
                        )

            # Also populate legacy arm_option for first question
            if qi == 0 and question['question_type'] == 'multiple_choice':
                for oi, opt_text in enumerate(arm_data.get('options', [])):
                    if opt_text.strip():
                        db.execute(
                            'INSERT INTO arm_option (arm_id, option_index, option_text) VALUES (?, ?, ?)',
                            (arm_id, oi, opt_text.strip()),
                        )

    for member in members:
        if member['name'].strip() and member['sis_code'].strip():
            db.execute(
                'INSERT INTO group_member (survey_id, name, sis_code) VALUES (?, ?, ?)',
                (survey_id, member['name'].strip(), member['sis_code'].strip()),
            )

    db.commit()
    return survey_id


def update_survey(survey_id, title, group_number, arms, questions, members):
    """Update an existing survey, replacing all arms, questions, and members."""
    db = get_db()

    first_type = questions[0]['question_type'] if questions else 'multiple_choice'
    db.execute('UPDATE survey SET title=?, group_number=?, question_type=? WHERE id=?',
               (title, group_number, first_type, survey_id))

    # Delete old data (cascades handle arm_question, arm_question_option, arm_option)
    db.execute('DELETE FROM survey_question WHERE survey_id=?', (survey_id,))
    db.execute('DELETE FROM survey_arm WHERE survey_id=?', (survey_id,))
    db.execute('DELETE FROM group_member WHERE survey_id=?', (survey_id,))

    # Recreate arms
    arm_ids = []
    for i, arm in enumerate(arms):
        legacy_text = ''
        if questions and i in questions[0].get('arms', {}):
            legacy_text = questions[0]['arms'][i].get('question_text', '')
        arm_cursor = db.execute(
            'INSERT INTO survey_arm (survey_id, arm_index, label, question_text) VALUES (?, ?, ?, ?)',
            (survey_id, i, arm['label'], legacy_text),
        )
        arm_ids.append(arm_cursor.lastrowid)

    # Recreate questions
    for qi, question in enumerate(questions):
        q_cursor = db.execute(
            'INSERT INTO survey_question (survey_id, question_index, question_type, label) VALUES (?, ?, ?, ?)',
            (survey_id, qi, question['question_type'], question.get('label', '')),
        )
        question_id = q_cursor.lastrowid

        for ai, arm_id in enumerate(arm_ids):
            arm_data = question.get('arms', {}).get(ai, {})
            q_text = arm_data.get('question_text', '')
            aq_cursor = db.execute(
                'INSERT INTO arm_question (arm_id, question_id, question_text) VALUES (?, ?, ?)',
                (arm_id, question_id, q_text),
            )
            aq_id = aq_cursor.lastrowid

            if question['question_type'] == 'multiple_choice':
                for oi, opt_text in enumerate(arm_data.get('options', [])):
                    if opt_text.strip():
                        db.execute(
                            'INSERT INTO arm_question_option (arm_question_id, option_index, option_text) VALUES (?, ?, ?)',
                            (aq_id, oi, opt_text.strip()),
                        )

            if qi == 0 and question['question_type'] == 'multiple_choice':
                for oi, opt_text in enumerate(arm_data.get('options', [])):
                    if opt_text.strip():
                        db.execute(
                            'INSERT INTO arm_option (arm_id, option_index, option_text) VALUES (?, ?, ?)',
                            (arm_id, oi, opt_text.strip()),
                        )

    for member in members:
        if member['name'].strip() and member['sis_code'].strip():
            db.execute(
                'INSERT INTO group_member (survey_id, name, sis_code) VALUES (?, ?, ?)',
                (survey_id, member['name'].strip(), member['sis_code'].strip()),
            )

    db.commit()


def get_survey(survey_id):
    """Get a survey with its arms, questions, and group members."""
    db = get_db()
    survey = db.execute('SELECT * FROM survey WHERE id=?', (survey_id,)).fetchone()
    if survey is None:
        return None

    survey = dict(survey)

    # Arms (just labels/indexes)
    arms = db.execute(
        'SELECT * FROM survey_arm WHERE survey_id=? ORDER BY arm_index', (survey_id,)
    ).fetchall()
    survey['arms'] = [dict(a) for a in arms]

    # Questions with per-arm texts and options
    questions = db.execute(
        'SELECT * FROM survey_question WHERE survey_id=? ORDER BY question_index', (survey_id,)
    ).fetchall()
    survey['questions'] = []
    for q in questions:
        q_dict = dict(q)
        q_dict['arms'] = {}
        for arm in arms:
            aq = db.execute(
                'SELECT * FROM arm_question WHERE arm_id=? AND question_id=?',
                (arm['id'], q['id'])
            ).fetchone()
            if aq:
                options = db.execute(
                    'SELECT * FROM arm_question_option WHERE arm_question_id=? ORDER BY option_index',
                    (aq['id'],)
                ).fetchall()
                q_dict['arms'][arm['arm_index']] = {
                    'question_text': aq['question_text'],
                    'options': [o['option_text'] for o in options],
                }
            else:
                q_dict['arms'][arm['arm_index']] = {
                    'question_text': '',
                    'options': [],
                }
        survey['questions'].append(q_dict)

    # Members
    members = db.execute(
        'SELECT * FROM group_member WHERE survey_id=?', (survey_id,)
    ).fetchall()
    survey['members'] = [dict(m) for m in members]

    return survey


def list_surveys(classroom_id):
    """List all surveys for a classroom, ordered by group_number."""
    db = get_db()
    surveys = db.execute(
        '''SELECT s.*,
            (SELECT COUNT(*) FROM survey_question sq WHERE sq.survey_id = s.id) AS question_count,
            (SELECT GROUP_CONCAT(DISTINCT sq.question_type)
             FROM survey_question sq WHERE sq.survey_id = s.id) AS question_types
           FROM survey s
           WHERE s.classroom_id=?
           ORDER BY s.group_number''',
        (classroom_id,)
    ).fetchall()
    return [dict(s) for s in surveys]


def get_active_survey_id(classroom_id):
    """Get the ID of the currently active survey in a classroom, or None."""
    db = get_db()
    row = db.execute(
        'SELECT id FROM survey WHERE is_active=1 AND classroom_id=?', (classroom_id,)
    ).fetchone()
    return row['id'] if row else None


def activate_survey(survey_id, classroom_id):
    """Deactivate all surveys in the classroom, then activate the given one."""
    db = get_db()
    db.execute('UPDATE survey SET is_active=0 WHERE is_active=1 AND classroom_id=?', (classroom_id,))
    db.execute('UPDATE survey SET is_active=1 WHERE id=?', (survey_id,))
    db.commit()


def deactivate_all(classroom_id):
    """Deactivate all surveys in a classroom."""
    db = get_db()
    db.execute('UPDATE survey SET is_active=0 WHERE is_active=1 AND classroom_id=?', (classroom_id,))
    db.commit()


def get_next_survey_id(current_survey_id, classroom_id):
    """Get the next survey by group_number after the current one, within the classroom."""
    db = get_db()
    current = db.execute('SELECT group_number FROM survey WHERE id=?', (current_survey_id,)).fetchone()
    if current is None:
        return None
    nxt = db.execute(
        'SELECT id FROM survey WHERE group_number > ? AND classroom_id=? ORDER BY group_number LIMIT 1',
        (current['group_number'], classroom_id),
    ).fetchone()
    return nxt['id'] if nxt else None


def delete_survey(survey_id):
    """Delete a survey and all its related data."""
    db = get_db()
    db.execute('DELETE FROM survey WHERE id=?', (survey_id,))
    db.commit()
