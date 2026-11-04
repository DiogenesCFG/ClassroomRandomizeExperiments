import json
import sqlite3

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, jsonify

from models import drafts
from models.classroom import get_classroom_by_code
from models.db import get_db
from models.survey import get_survey
from routes.account import get_signed_in_student, ensure_participant_session

bp = Blueprint('student', __name__, url_prefix='/c/<code>/student')


def _get_classroom_or_404(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


def _clean_seconds(value):
    """Time on a question as reported by the phone: a number of seconds, rounded to 0.1, or None."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds != seconds or seconds < 0 or seconds > 24 * 3600:  # NaN or nonsense
        return None
    return round(seconds, 1)


def _clean_order(value):
    """Shuffled options: the order they were shown, as a JSON list of texts (or None)."""
    if not isinstance(value, list) or not value or len(value) > 50:
        return None
    return json.dumps([str(v)[:200] for v in value], ensure_ascii=False)


def _clean_position(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 1000 else None


def _clean_entry(answer):
    """One answer as sent by the phone, cleaned for storing (response or response_draft)."""
    return {
        'question_id': answer.get('question_id'),
        'answer_text': str(answer.get('answer_text', '')),
        'answer_index': answer.get('answer_index') if isinstance(answer.get('answer_index'), int) else None,
        'other_text': str(answer.get('other_text') or '').strip()[:140] or None,
        'seconds': _clean_seconds(answer.get('seconds')),
        'left_page': 1 if answer.get('left_page') else 0,
        'timed_out': 1 if answer.get('timed_out') else 0,
        'display_order': _clean_order(answer.get('display_order')),
        'position': _clean_position(answer.get('position')),
    }


def _part_of(db, survey, question_ids):
    """(part, that part's question ids) for answers to these questions, or (None, None) if they mix parts.
    A one-part survey: (1, None), None meaning all its questions."""
    from models import reminders
    if not reminders.is_two_part(survey):
        return 1, None
    index_of = {r['id']: r['question_index'] for r in db.execute(
        'SELECT id, question_index FROM survey_question WHERE survey_id=?', (survey['id'],))}
    parts = {reminders.question_part(survey, {'question_index': index_of[q]}) for q in question_ids if q in index_of}
    if len(parts) != 1:
        return None, None
    part = parts.pop()
    return part, [q for q, i in index_of.items() if reminders.question_part(survey, {'question_index': i}) == part]


def _closed_for(db, survey, part):
    """Why answers to this part can't be taken now (an error code), or None.
    Part 1 (or a one-part survey): only while it runs live, or opened early before its deadline.
    Part 2 of a two-part survey: while its dates are open, for students who answered part 1."""
    from models.feedback import early_survey_is_open
    from models import reminders
    if part == 2 and not reminders.answered_part(db, session['participant_id'], survey, 1):
        return 'part1_first'
    running_live = survey['is_active'] and (survey['active_part'] or 1) == part
    open_remote = part in reminders.remote_parts(survey) and reminders.part_window(get_survey(survey['id']), part) == 'open'
    open_early = part == 1 and not reminders.is_two_part(survey) and early_survey_is_open(survey)
    if not (running_live or open_remote or open_early):
        return 'survey_closed'
    return None


def _require_classroom_access(classroom):
    """Check that the user has joined via classroom password or is host."""
    if not session.get(f'classroom_joined_{classroom["id"]}') and \
       not session.get(f'host_authenticated_{classroom["id"]}'):
        return False
    return True


@bp.route('/')
def login(code):
    """Entry point for the live session: sign in with the roster first if needed."""
    classroom = _get_classroom_or_404(code)
    if not _require_classroom_access(classroom):
        flash('Please join the classroom first.', 'danger')
        return redirect(url_for('classroom.join', code=code))
    return redirect(url_for('student.live_session', code=code))


@bp.route('/session')
def live_session(code):
    classroom = _get_classroom_or_404(code)

    if not _require_classroom_access(classroom):
        return redirect(url_for('classroom.join', code=code))

    student = get_signed_in_student(classroom)
    if not student:
        return redirect(url_for('account.signin', code=code))
    ensure_participant_session(classroom, student)

    return render_template('student/session.html',
                           participant_id=session['participant_id'],
                           student_id=session['student_id'],
                           student_name=session['student_name'],
                           classroom=classroom)


@bp.route('/state')
def session_state(code):
    """HTTP fallback for getting the active student assignment."""
    classroom = _get_classroom_or_404(code)

    if 'participant_id' not in session or session.get('classroom_id') != classroom['id']:
        return jsonify({'ok': False, 'error': 'not_logged_in'}), 401

    from sockets.events import (
        _build_assignment_payload,
        _get_survey_with_arms_and_questions,
        _is_fully_answered,
    )

    db = get_db()
    active = db.execute(
        'SELECT * FROM survey WHERE is_active=1 AND classroom_id=?',
        (classroom['id'],),
    ).fetchone()

    if not active:
        return jsonify({'ok': True, 'state': 'waiting'})

    # Check if student is a designer of this survey and should be blocked
    block_designers = db.execute(
        'SELECT block_designers FROM classroom WHERE id=?', (classroom['id'],)
    ).fetchone()['block_designers']
    if block_designers:
        is_designer = db.execute(
            'SELECT 1 FROM group_member WHERE survey_id=? AND sis_code=?',
            (active['id'], session['student_id']),
        ).fetchone()
        if is_designer:
            return jsonify({'ok': True, 'state': 'blocked_designer', 'survey_id': active['id']})

    # A two-part survey runs one part at a time (the one the host launched)
    from models import reminders
    part = (active['active_part'] or 1) if reminders.is_two_part(dict(active)) else 1
    if _is_fully_answered(db, session['participant_id'], active['id'], part):
        return jsonify({
            'ok': True,
            'state': 'submitted',
            'survey_id': active['id'],
        })
    if part == 2 and not reminders.answered_part(db, session['participant_id'], dict(active), 1):
        return jsonify({'ok': True, 'state': 'skip', 'survey_id': active['id'],
                        'title': 'This survey is for classmates who answered its part 1',
                        'message': "You didn't answer part 1 before class, so please wait for the next survey."})

    result = _get_survey_with_arms_and_questions(db, active['id'])
    if not result:
        return jsonify({'ok': False, 'error': 'survey_not_found'}), 404

    survey, arms, questions = result
    payload = _build_assignment_payload(survey, arms, questions, session['student_id'], part=part)
    drafts.attach(payload, session['participant_id'])
    if part == 2:
        payload['title'] += ' (part 2)'
    return jsonify({
        'ok': True,
        'state': 'assignment',
        'assignment': payload,
    })


@bp.route('/submit', methods=['POST'])
def submit_answer_http(code):
    """HTTP fallback for saving an answer when SocketIO is unavailable."""
    classroom = _get_classroom_or_404(code)

    if 'participant_id' not in session or session.get('classroom_id') != classroom['id']:
        return jsonify({'ok': False, 'error': 'not_logged_in'}), 401

    from sockets.events import _is_fully_answered

    data = request.get_json(silent=True) or {}
    survey_id = data.get('survey_id')
    arm_id = data.get('arm_id')
    answers = data.get('answers') or []

    if not survey_id or not arm_id or not answers:
        return jsonify({'ok': False, 'error': 'missing_answer_data'}), 400

    db = get_db()
    survey = db.execute(
        'SELECT * FROM survey WHERE id=? AND classroom_id=?',
        (survey_id, classroom['id']),
    ).fetchone()
    if not survey:
        return jsonify({'ok': False, 'error': 'survey_not_found'}), 404

    survey = dict(survey)
    part, part_ids = _part_of(db, survey, [a.get('question_id') for a in answers])
    if part is None:
        return jsonify({'ok': False, 'error': 'missing_answer_data'}), 400
    closed = _closed_for(db, survey, part)
    if closed:
        return jsonify({'ok': False, 'error': closed}), 403 if closed == 'part1_first' else 409

    if _is_fully_answered(db, session['participant_id'], survey_id, part):
        drafts.clear(db, session['participant_id'], survey_id, part_ids)
        db.commit()
        return jsonify({'ok': True, 'status': 'already_answered'})

    try:
        for answer in answers:
            e = _clean_entry(answer)
            db.execute(
                'INSERT INTO response (participant_id, survey_id, arm_id, question_id, answer_text, answer_index, '
                'seconds, left_page, other_text, timed_out, display_order, position) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (session['participant_id'], survey_id, arm_id, e['question_id'], e['answer_text'], answer.get('answer_index'),
                 e['seconds'], e['left_page'], e['other_text'], e['timed_out'], e['display_order'], e['position']),
            )
        # Submitted: the answers saved along the way are no longer drafts
        drafts.clear(db, session['participant_id'], survey_id, part_ids)
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        if _is_fully_answered(db, session['participant_id'], survey_id):
            return jsonify({'ok': True, 'status': 'already_answered'})
        return jsonify({'ok': False, 'error': 'integrity_error'}), 409

    return jsonify({'ok': True, 'status': 'saved'})


@bp.route('/draft', methods=['POST'])
def save_draft(code):
    """Save the answers given so far (not submitted), about a second after each change on the phone.
    Refused for previews (no participant), closed surveys and once the part is submitted."""
    classroom = _get_classroom_or_404(code)
    if 'participant_id' not in session or session.get('classroom_id') != classroom['id'] or not session['participant_id']:
        return jsonify({'ok': False, 'error': 'not_logged_in'}), 401

    from sockets.events import _is_fully_answered

    data = request.get_json(silent=True) or {}
    db = get_db()
    survey = db.execute('SELECT * FROM survey WHERE id=? AND classroom_id=?',
                        (data.get('survey_id'), classroom['id'])).fetchone()
    if not survey:
        return jsonify({'ok': False, 'error': 'survey_not_found'}), 404
    survey = dict(survey)
    arm_id = data.get('arm_id')
    if not db.execute('SELECT 1 FROM survey_arm WHERE id=? AND survey_id=?', (arm_id, survey['id'])).fetchone():
        return jsonify({'ok': False, 'error': 'missing_answer_data'}), 400
    own = {r['id'] for r in db.execute('SELECT id FROM survey_question WHERE survey_id=?', (survey['id'],))}
    question_ids = [q for q in (data.get('question_ids') or []) if isinstance(q, int) and q in own]
    if not question_ids:
        return jsonify({'ok': False, 'error': 'missing_answer_data'}), 400
    part, _ = _part_of(db, survey, question_ids)
    if part is None:
        return jsonify({'ok': False, 'error': 'missing_answer_data'}), 400
    closed = _closed_for(db, survey, part)
    if closed:
        return jsonify({'ok': False, 'error': closed}), 409
    if _is_fully_answered(db, session['participant_id'], survey['id'], part):
        return jsonify({'ok': True, 'status': 'submitted'})
    entries = [_clean_entry(a) for a in (data.get('answers') or [])[:200]
               if isinstance(a, dict) and a.get('question_id') in question_ids]
    drafts.save(db, session['participant_id'], survey['id'], arm_id, question_ids, entries)
    db.commit()
    return jsonify({'ok': True, 'status': 'saved'})
