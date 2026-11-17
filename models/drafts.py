"""Answers given but not yet submitted (the soft save).

The phone saves each respondent's answers about a second after every change (POST /student/draft) into
response_draft, which has the same columns as response. Submitting writes response as before and clears
the drafts for that part, so a submitted survey stays locked and response only ever holds submitted answers:
the dashboard charts, _is_fully_answered and everything else that reads response are unchanged.

Drafts are used to:
  - resume: the state endpoints send them back (payload['draft']) so a reload or a dropped connection
    continues where the respondent left off;
  - data: the exports read ALL_ANSWERS (both tables, with submitted = 1 / 0), so respondents who started
    but never submitted appear with submitted = no;
  - the live dashboard's "N in progress".
"""
from models.db import get_db

COLUMNS = ('participant_id, survey_id, arm_id, question_id, answer_text, answer_index, other_text, seconds, '
           'left_page, timed_out, display_order, position, answered_at, changes, first_value')

# Submitted answers and drafts together, for the exports (a subquery: FROM {ALL_ANSWERS} r)
ALL_ANSWERS = (f'(SELECT {COLUMNS}, 1 AS submitted FROM response '
               f'UNION ALL SELECT {COLUMNS}, 0 AS submitted FROM response_draft)')


def save(db, participant_id, survey_id, arm_id, question_ids, entries):
    """Replace this respondent's drafts for these questions with entries (dicts with question_id,
    answer_text, answer_index, other_text, seconds, left_page, timed_out, display_order, position).
    answered_at keeps the time an answer was first given, and changes when the answer changes."""
    given = set()
    for e in entries:
        given.add(e['question_id'])
        db.execute(
            'INSERT INTO response_draft (participant_id, survey_id, arm_id, question_id, answer_text, answer_index, '
            'other_text, seconds, left_page, timed_out, display_order, position, changes, first_value) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(participant_id, question_id) DO UPDATE SET '
            "answered_at = CASE WHEN response_draft.answer_text IS excluded.answer_text "
            "AND response_draft.other_text IS excluded.other_text THEN response_draft.answered_at ELSE datetime('now') END, "
            'arm_id = excluded.arm_id, answer_text = excluded.answer_text, answer_index = excluded.answer_index, '
            'other_text = excluded.other_text, seconds = excluded.seconds, left_page = excluded.left_page, '
            'timed_out = excluded.timed_out, display_order = excluded.display_order, position = excluded.position, '
            'changes = excluded.changes, first_value = excluded.first_value',
            (participant_id, survey_id, arm_id, e['question_id'], e['answer_text'], e['answer_index'], e['other_text'],
             e['seconds'], e['left_page'], e['timed_out'], e['display_order'], e['position'], e.get('changes'),
             e.get('first_value')))
    gone = [q for q in question_ids if q not in given]
    if gone:
        db.execute(f'DELETE FROM response_draft WHERE participant_id=? AND survey_id=? '
                   f'AND question_id IN ({",".join("?" * len(gone))})', (participant_id, survey_id, *gone))


def answered_times(db, participant_id, survey_id):
    """{question_id: (answer_text, answered_at)} of the drafts, so submitting keeps when each answer was given."""
    return {r['question_id']: (r['answer_text'], r['answered_at']) for r in db.execute(
        'SELECT question_id, answer_text, answered_at FROM response_draft WHERE participant_id=? AND survey_id=?',
        (participant_id, survey_id))}


def clear(db, participant_id, survey_id, question_ids=None):
    """Drop a respondent's drafts for a survey (only these questions, if given), e.g. once submitted."""
    if question_ids is None:
        db.execute('DELETE FROM response_draft WHERE participant_id=? AND survey_id=?', (participant_id, survey_id))
    elif question_ids:
        db.execute(f'DELETE FROM response_draft WHERE participant_id=? AND survey_id=? '
                   f'AND question_id IN ({",".join("?" * len(question_ids))})',
                   (participant_id, survey_id, *question_ids))


def load(participant_id, survey_id, question_ids):
    """The saved answers to send back to the phone (for these questions), as a list of dicts."""
    if not participant_id or not question_ids:
        return []
    rows = get_db().execute(
        f'SELECT question_id, arm_id, answer_text, answer_index, other_text, seconds, left_page, timed_out, changes, first_value '
        f'FROM response_draft WHERE participant_id=? AND survey_id=? '
        f'AND question_id IN ({",".join("?" * len(question_ids))})',
        (participant_id, survey_id, *question_ids)).fetchall()
    return [{'question_id': r['question_id'], 'arm_id': r['arm_id'], 'answer_text': r['answer_text'],
             'answer_index': r['answer_index'], 'other_text': r['other_text'], 'seconds': r['seconds'],
             'left_page': bool(r['left_page']), 'timed_out': bool(r['timed_out']), 'changes': r['changes'],
             'first_value': r['first_value']} for r in rows]


def attach(payload, participant_id):
    """Add the respondent's saved answers to an assignment payload (only those given in its arm)."""
    saved = load(participant_id, payload['survey_id'], [q['question_id'] for q in payload['questions']])
    payload['draft'] = [d for d in saved if d['arm_id'] == payload['arm_id']]
    return payload


def in_progress(db, survey_id):
    """How many respondents have answers saved but not submitted."""
    return db.execute('SELECT COUNT(DISTINCT participant_id) FROM response_draft WHERE survey_id=?',
                      (survey_id,)).fetchone()[0]
