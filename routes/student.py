import sqlite3

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, jsonify

from models.classroom import get_classroom_by_code
from models.db import get_db
from models.participant import login_or_create

bp = Blueprint('student', __name__, url_prefix='/c/<code>/student')


def _get_classroom_or_404(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


@bp.route('/', methods=['GET', 'POST'])
def login(code):
    classroom = _get_classroom_or_404(code)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        student_id = request.form.get('student_id', '').strip()

        if not name or not student_id:
            flash('Please enter both your name and student ID.', 'danger')
            return render_template('student/login.html', classroom=classroom)

        participant = login_or_create(name, student_id, classroom['id'])
        session['participant_id'] = participant['id']
        session['student_id'] = participant['student_id']
        session['student_name'] = participant['name']
        session['classroom_id'] = classroom['id']
        session['classroom_code'] = classroom['code']
        return redirect(url_for('student.live_session', code=code))

    # If already logged in for this classroom, go to session
    if 'participant_id' in session and session.get('classroom_id') == classroom['id']:
        return redirect(url_for('student.live_session', code=code))

    return render_template('student/login.html', classroom=classroom)


@bp.route('/session')
def live_session(code):
    classroom = _get_classroom_or_404(code)

    if 'participant_id' not in session:
        return redirect(url_for('student.login', code=code))

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

    if _is_fully_answered(db, session['participant_id'], active['id']):
        return jsonify({
            'ok': True,
            'state': 'submitted',
            'survey_id': active['id'],
        })

    result = _get_survey_with_arms_and_questions(db, active['id'])
    if not result:
        return jsonify({'ok': False, 'error': 'survey_not_found'}), 404

    survey, arms, questions = result
    payload = _build_assignment_payload(survey, arms, questions, session['student_id'])
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

    from app import socketio
    from sockets.events import _get_aggregated_results, _is_fully_answered

    data = request.get_json(silent=True) or {}
    survey_id = data.get('survey_id')
    arm_id = data.get('arm_id')
    answers = data.get('answers') or []

    if not survey_id or not arm_id or not answers:
        return jsonify({'ok': False, 'error': 'missing_answer_data'}), 400

    db = get_db()
    survey = db.execute(
        'SELECT id FROM survey WHERE id=? AND classroom_id=?',
        (survey_id, classroom['id']),
    ).fetchone()
    if not survey:
        return jsonify({'ok': False, 'error': 'survey_not_found'}), 404

    if _is_fully_answered(db, session['participant_id'], survey_id):
        return jsonify({'ok': True, 'status': 'already_answered'})

    try:
        for answer in answers:
            db.execute(
                'INSERT INTO response (participant_id, survey_id, arm_id, question_id, answer_text, answer_index) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (
                    session['participant_id'],
                    survey_id,
                    arm_id,
                    answer.get('question_id'),
                    str(answer.get('answer_text', '')),
                    answer.get('answer_index'),
                ),
            )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        if _is_fully_answered(db, session['participant_id'], survey_id):
            return jsonify({'ok': True, 'status': 'already_answered'})
        return jsonify({'ok': False, 'error': 'integrity_error'}), 409

    results = _get_aggregated_results(db, survey_id)
    if results:
        socketio.emit('results_update', results, room=f'host_{classroom["id"]}')

    return jsonify({'ok': True, 'status': 'saved'})
