import hashlib
import os

from flask import current_app

from models import rules
from models.db import get_db


def _image_fingerprint(filename, cache):
    """Hash an uploaded image's contents so re-uploads of the same picture compare equal."""
    if not filename:
        return None
    if filename not in cache:
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        try:
            with open(path, 'rb') as f:
                cache[filename] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            cache[filename] = filename.split('_', 1)[-1]  # file missing: fall back to the original name
    return cache[filename]


def survey_warnings(survey):
    """Design problems worth flagging to the group (not errors: the survey still saves).

    `survey` is a dict from get_survey(). Returns a list of messages.
    """
    if survey.get('external'):
        return []  # run on another platform: nothing here to check
    arms = survey.get('arms', [])
    questions = survey.get('questions', [])
    if len(arms) < 2:
        return ['Only one arm: there is no treatment to compare against.']

    cache = {}

    def arm_signature(arm_index):
        sig = []
        for q in questions:
            data = q['arms'].get(arm_index, {})
            if not rules.shown_in_arm(q, arm_index):
                sig.append(None)  # not asked in this arm
                continue
            sig.append((
                ' '.join((data.get('question_text') or '').lower().split()),
                tuple(' '.join(o.lower().split()) for o in data.get('options', [])),
                _image_fingerprint(data.get('image_filename'), cache),
                bool(data.get('allow_other')),
                data.get('timer_seconds') or None,
                (data.get('timer_display'), data.get('timer_default')) if data.get('timer_seconds') else None,
            ))
        return sig

    warnings = []
    signatures = [arm_signature(a['arm_index']) for a in arms]
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            if signatures[i] == signatures[j]:
                warnings.append(f'Arms "{arms[i]["label"]}" and "{arms[j]["label"]}" are identical in every '
                                f'question (text, options, and images), so there is no treatment difference.')
    return warnings


def missing_parts(arms, questions):
    """What a survey still needs before it can run, as short to-do items.

    Works on the builder's parsed form (arms: [{'label'}], questions with 'arms' keyed
    0..n-1) and, through survey_incomplete(), on a stored survey. Unfinished surveys
    still save; these are shown as "Still to do" and block early deployment.
    """
    todo = []
    if not questions:
        todo.append('Add at least one question.')
    for qi, q in enumerate(questions):
        for ai in range(len(arms)):
            if not rules.shown_in_arm(q, ai):
                continue  # this arm never sees the question, so its version can stay empty
            data = q.get('arms', {}).get(ai, {})
            name = f'Question {qi + 1}' + (f', {arms[ai]["label"]}' if len(arms) > 1 else '')
            if not (data.get('question_text') or '').strip():
                todo.append(f'{name}: write the question.')
            if q['question_type'] in ('multiple_choice', 'multiple_answer') and len(
                    [o for o in data.get('options', []) if o.strip()]) + (1 if data.get('allow_other') else 0) < 2:
                todo.append(f'{name}: add at least 2 answer options.')
            problem = timer_default_problem(q, data)
            if problem:
                todo.append(f'{name}: {problem}')
    return todo + rules.rule_problems(questions, arms)


def timer_default_problem(q, data):
    """Why an arm-question's "if time runs out" answer can't be recorded, or None.
    An empty default is fine: the answer is then recorded as blank, marked timed out."""
    if not data.get('timer_seconds'):
        return None
    default = (data.get('timer_default') or '').strip()
    if not default:
        return None
    qtype = q['question_type']
    if qtype in ('multiple_choice', 'multiple_answer'):
        options = [o.strip() for o in data.get('options', []) if o.strip()]
        if default not in options:
            return f'the answer recorded when time runs out ("{default}") must be one of the options, or left empty.'
    elif qtype in ('numeric', 'slider'):
        try:
            value = float(default)
        except ValueError:
            return f'the answer recorded when time runs out ("{default}") must be a number, or left empty.'
        if qtype == 'slider':
            lo, hi = q.get('slider_min', 0) or 0, q.get('slider_max', 100) or 100
            if not lo <= value <= hi:
                return f'the answer recorded when time runs out ({default}) must be between {lo:g} and {hi:g}.'
    return None


def survey_incomplete(survey):
    """missing_parts() for a survey dict from get_survey(), plus the two-part split and the
    reminder plan (models/reminders.py); [] for other-platform surveys."""
    if not survey or survey.get('external'):
        return []
    from models import reminders
    classroom = get_db().execute('SELECT * FROM classroom WHERE id=?', (survey['classroom_id'],)).fetchone()
    arms = sorted(survey.get('arms', []), key=lambda a: a['arm_index'])
    by_position = {a['arm_index']: i for i, a in enumerate(arms)}
    questions = [{'question_type': q['question_type'],
                  'slider_min': q.get('slider_min'), 'slider_max': q.get('slider_max'),
                  'show_arms': q.get('show_arms'), 'cond_question': q.get('cond_question'),
                  'cond_values': q.get('cond_values') or [],
                  'arms': {by_position[k]: v for k, v in q.get('arms', {}).items() if k in by_position}}
                 for q in survey.get('questions', [])]
    return (missing_parts(arms, questions) + reminders.part_problems(survey)
            + reminders.plan_problems(survey, dict(classroom) if classroom else None))


def with_todo(surveys):
    """Add each survey's missing_parts() as 'todo' (for the host's survey lists)."""
    for s in surveys:
        s['todo'] = survey_incomplete(get_survey(s['id']))
    return surveys


def respondent_count(survey_id):
    """Number of distinct students who answered this survey."""
    return get_db().execute('SELECT COUNT(DISTINCT participant_id) FROM response WHERE survey_id=?',
                            (survey_id,)).fetchone()[0]


def next_group_number(classroom_id):
    """The next unused group number in a classroom (max + 1)."""
    row = get_db().execute('SELECT MAX(group_number) FROM survey WHERE classroom_id=?', (classroom_id,)).fetchone()
    return (row[0] or 0) + 1


def create_survey(classroom_id, title, group_number, arms, questions, members):
    """
    Create a survey with arms, questions, and group members.

    arms: list of dicts, each with 'label'
    questions: list of dicts, each with 'question_type', 'label', and 'arms' dict
        where arms maps arm_index -> {'question_text': str, 'options': [str]}
    members: list of dicts, each with 'name', 'sis_code' and 'roster_student_id'
    """
    db = get_db()

    # Use first question's type for legacy column
    first_type = questions[0]['question_type'] if questions else 'multiple_choice'
    cursor = db.execute(
        'INSERT INTO survey (classroom_id, title, group_number, question_type) VALUES (?, ?, ?, ?)',
        (classroom_id, title, group_number, first_type),
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
            'INSERT INTO survey_question (survey_id, question_index, question_type, label, slider_min, slider_max, '
            'slider_step, show_arms, cond_question, cond_values) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (survey_id, qi, question['question_type'], question.get('label', ''),
             question.get('slider_min'), question.get('slider_max'), question.get('slider_step'),
             *rules.to_columns(question)),
        )
        question_id = q_cursor.lastrowid

        for ai, arm_id in enumerate(arm_ids):
            arm_data = question.get('arms', {}).get(ai, {})
            q_text = arm_data.get('question_text', '')
            image_filename = arm_data.get('image_filename')
            allow_other = 1 if (arm_data.get('allow_other')
                                and question['question_type'] in ('multiple_choice', 'multiple_answer')) else 0
            timer = arm_data.get('timer_seconds')
            aq_cursor = db.execute(
                'INSERT INTO arm_question (arm_id, question_id, question_text, image_filename, allow_other, '
                'timer_seconds, timer_display, timer_default) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (arm_id, question_id, q_text, image_filename, allow_other,
                 timer, (arm_data.get('timer_display') or 'both') if timer else None,
                 arm_data.get('timer_default', '') if timer else None),
            )
            aq_id = aq_cursor.lastrowid

            if question['question_type'] in ('multiple_choice', 'multiple_answer'):
                for oi, opt_text in enumerate(arm_data.get('options', [])):
                    if opt_text.strip():
                        db.execute(
                            'INSERT INTO arm_question_option (arm_question_id, option_index, option_text) VALUES (?, ?, ?)',
                            (aq_id, oi, opt_text.strip()),
                        )

            # Also populate legacy arm_option for first question
            if qi == 0 and question['question_type'] in ('multiple_choice', 'multiple_answer'):
                for oi, opt_text in enumerate(arm_data.get('options', [])):
                    if opt_text.strip():
                        db.execute(
                            'INSERT INTO arm_option (arm_id, option_index, option_text) VALUES (?, ?, ?)',
                            (arm_id, oi, opt_text.strip()),
                        )

    for member in members:
        db.execute(
            'INSERT INTO group_member (survey_id, name, sis_code, roster_student_id) VALUES (?, ?, ?, ?)',
            (survey_id, member['name'], member['sis_code'], member.get('roster_student_id')),
        )

    db.commit()
    return survey_id


def update_survey(survey_id, title, group_number, arms, questions):
    """Update an existing survey, replacing all arms and questions (group members are kept).
    Returns list of old image filenames that were removed (caller should delete files)."""
    db = get_db()

    # Collect old image filenames before deleting arm_questions
    old_images = db.execute(
        'SELECT aq.image_filename FROM arm_question aq '
        'JOIN survey_arm sa ON aq.arm_id = sa.id '
        'WHERE sa.survey_id=? AND aq.image_filename IS NOT NULL',
        (survey_id,)
    ).fetchall()
    old_image_filenames = [r['image_filename'] for r in old_images]

    first_type = questions[0]['question_type'] if questions else 'multiple_choice'
    db.execute('UPDATE survey SET title=?, group_number=?, question_type=? WHERE id=?',
               (title, group_number, first_type, survey_id))

    # Delete old data -- responses must go first since they reference arms/questions
    # without ON DELETE CASCADE
    db.execute('DELETE FROM response WHERE survey_id=?', (survey_id,))
    db.execute('DELETE FROM reminder_action WHERE survey_id=?', (survey_id,))
    db.execute('DELETE FROM push_subscription WHERE survey_id=?', (survey_id,))
    db.execute('DELETE FROM survey_question WHERE survey_id=?', (survey_id,))
    db.execute('DELETE FROM survey_arm WHERE survey_id=?', (survey_id,))

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
            'INSERT INTO survey_question (survey_id, question_index, question_type, label, slider_min, slider_max, '
            'slider_step, show_arms, cond_question, cond_values) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (survey_id, qi, question['question_type'], question.get('label', ''),
             question.get('slider_min'), question.get('slider_max'), question.get('slider_step'),
             *rules.to_columns(question)),
        )
        question_id = q_cursor.lastrowid

        for ai, arm_id in enumerate(arm_ids):
            arm_data = question.get('arms', {}).get(ai, {})
            q_text = arm_data.get('question_text', '')
            image_filename = arm_data.get('image_filename')
            allow_other = 1 if (arm_data.get('allow_other')
                                and question['question_type'] in ('multiple_choice', 'multiple_answer')) else 0
            timer = arm_data.get('timer_seconds')
            aq_cursor = db.execute(
                'INSERT INTO arm_question (arm_id, question_id, question_text, image_filename, allow_other, '
                'timer_seconds, timer_display, timer_default) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (arm_id, question_id, q_text, image_filename, allow_other,
                 timer, (arm_data.get('timer_display') or 'both') if timer else None,
                 arm_data.get('timer_default', '') if timer else None),
            )
            aq_id = aq_cursor.lastrowid

            if question['question_type'] in ('multiple_choice', 'multiple_answer'):
                for oi, opt_text in enumerate(arm_data.get('options', [])):
                    if opt_text.strip():
                        db.execute(
                            'INSERT INTO arm_question_option (arm_question_id, option_index, option_text) VALUES (?, ?, ?)',
                            (aq_id, oi, opt_text.strip()),
                        )

            if qi == 0 and question['question_type'] in ('multiple_choice', 'multiple_answer'):
                for oi, opt_text in enumerate(arm_data.get('options', [])):
                    if opt_text.strip():
                        db.execute(
                            'INSERT INTO arm_option (arm_id, option_index, option_text) VALUES (?, ?, ?)',
                            (arm_id, oi, opt_text.strip()),
                        )

    db.commit()

    # Return old filenames so caller can delete files that are no longer referenced
    # (only those not re-used in the new data)
    new_images = set()
    for q in questions:
        for ai_data in q.get('arms', {}).values():
            fn = ai_data.get('image_filename')
            if fn:
                new_images.add(fn)
    removed = [f for f in old_image_filenames if f not in new_images]
    return removed


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
        q_dict.update(rules.from_row(q))
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
                    'image_filename': aq['image_filename'],
                    'allow_other': bool(aq['allow_other']),
                    'timer_seconds': aq['timer_seconds'],
                    'timer_display': aq['timer_display'],
                    'timer_default': aq['timer_default'],
                }
            else:
                q_dict['arms'][arm['arm_index']] = {
                    'question_text': '',
                    'options': [],
                    'image_filename': None,
                    'allow_other': False,
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
             FROM survey_question sq WHERE sq.survey_id = s.id) AS question_types,
            (SELECT GROUP_CONCAT(gm.name, '; ') FROM group_member gm WHERE gm.survey_id = s.id) AS member_names,
            (SELECT COUNT(*) FROM group_member gm WHERE gm.survey_id = s.id) AS member_count,
            (SELECT COUNT(*) FROM team_invite ti WHERE ti.survey_id = s.id) AS invite_count,
            (SELECT GROUP_CONCAT(rs.full_name, '; ') FROM team_invite ti JOIN roster_student rs ON ti.roster_student_id = rs.id
             WHERE ti.survey_id = s.id) AS invite_names,
            (SELECT GROUP_CONCAT(rs.full_name, '; ') FROM join_request jr JOIN roster_student rs ON jr.roster_student_id = rs.id
             WHERE jr.survey_id = s.id) AS request_names
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
        'SELECT id FROM survey WHERE group_number > ? AND classroom_id=? AND external=0 ORDER BY group_number LIMIT 1',
        (current['group_number'], classroom_id),
    ).fetchone()
    return nxt['id'] if nxt else None


def delete_survey(survey_id):
    """Delete a survey and all its related data. Returns list of image filenames to clean up."""
    db = get_db()
    images = db.execute(
        'SELECT aq.image_filename FROM arm_question aq '
        'JOIN survey_arm sa ON aq.arm_id = sa.id '
        'WHERE sa.survey_id=? AND aq.image_filename IS NOT NULL',
        (survey_id,)
    ).fetchall()
    image_filenames = [r['image_filename'] for r in images]
    # Responses have no ON DELETE CASCADE, so remove them first
    db.execute('DELETE FROM response WHERE survey_id=?', (survey_id,))
    db.execute('DELETE FROM survey WHERE id=?', (survey_id,))
    db.commit()
    return image_filenames
