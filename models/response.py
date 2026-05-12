import sqlite3
from models.db import get_db


def save_response(participant_id, survey_id, arm_id, answer_text, answer_index=None):
    """Save a response. Returns True if saved, False if duplicate."""
    db = get_db()
    try:
        db.execute(
            'INSERT INTO response (participant_id, survey_id, arm_id, answer_text, answer_index) '
            'VALUES (?, ?, ?, ?, ?)',
            (participant_id, survey_id, arm_id, answer_text, answer_index),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def has_responded(participant_id, survey_id):
    db = get_db()
    row = db.execute(
        'SELECT id FROM response WHERE participant_id=? AND survey_id=?',
        (participant_id, survey_id),
    ).fetchone()
    return row is not None


def get_response_count(survey_id):
    db = get_db()
    row = db.execute(
        'SELECT COUNT(*) as cnt FROM response WHERE survey_id=?', (survey_id,)
    ).fetchone()
    return row['cnt']


def get_aggregated_results(survey_id):
    """
    Get aggregated results for a survey, structured for Chart.js.

    Returns dict with:
      - question_type: 'numeric' or 'multiple_choice'
      - arms: list of {label, arm_id, arm_index, question_text, ...}
        For MC: each arm has 'counts' (dict of option_text -> count)
        For numeric: each arm has 'values' (list of floats) and 'stats' (mean, median, etc.)
      - total_responses: int
    """
    db = get_db()
    survey = db.execute('SELECT * FROM survey WHERE id=?', (survey_id,)).fetchone()
    if not survey:
        return None

    arms = db.execute(
        'SELECT * FROM survey_arm WHERE survey_id=? ORDER BY arm_index', (survey_id,)
    ).fetchall()

    result = {
        'survey_id': survey_id,
        'question_type': survey['question_type'],
        'title': survey['title'],
        'group_number': survey['group_number'],
        'arms': [],
        'total_responses': 0,
    }

    for arm in arms:
        arm_data = {
            'arm_id': arm['id'],
            'arm_index': arm['arm_index'],
            'label': arm['label'],
            'question_text': arm['question_text'],
        }

        responses = db.execute(
            'SELECT answer_text, answer_index FROM response WHERE survey_id=? AND arm_id=?',
            (survey_id, arm['id']),
        ).fetchall()

        result['total_responses'] += len(responses)

        if survey['question_type'] == 'multiple_choice':
            # Get options for this arm
            options = db.execute(
                'SELECT * FROM arm_option WHERE arm_id=? ORDER BY option_index', (arm['id'],)
            ).fetchall()
            option_texts = [o['option_text'] for o in options]

            counts = {opt: 0 for opt in option_texts}
            for r in responses:
                if r['answer_text'] in counts:
                    counts[r['answer_text']] += 1

            arm_data['options'] = option_texts
            arm_data['counts'] = counts
            arm_data['n'] = len(responses)
        else:
            # Numeric
            values = []
            for r in responses:
                try:
                    values.append(float(r['answer_text']))
                except (ValueError, TypeError):
                    pass

            arm_data['values'] = values
            arm_data['n'] = len(values)
            if values:
                sorted_vals = sorted(values)
                arm_data['stats'] = {
                    'mean': sum(values) / len(values),
                    'median': sorted_vals[len(sorted_vals) // 2],
                    'min': min(values),
                    'max': max(values),
                    'std': (sum((x - sum(values)/len(values))**2 for x in values) / len(values)) ** 0.5,
                }
            else:
                arm_data['stats'] = None

        result['arms'].append(arm_data)

    return result
