"""Peer feedback (students comment on other groups' surveys), the host's class-phase
controls, and surveys opened early."""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, jsonify, Response

from models.classroom import get_classroom_by_code
from models.db import get_db
from models.survey import get_survey
from models import feedback as fb
from routes.account import get_signed_in_student, ensure_participant_session

bp = Blueprint('feedback', __name__, url_prefix='/c/<code>')

MAX_COMMENT_LENGTH = 3000


def _classroom(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


def _is_host(classroom):
    return session.get(f'host_authenticated_{classroom["id"]}') is True


def _student_or_redirect(classroom):
    student = get_signed_in_student(classroom)
    if not student:
        return None, redirect(url_for('account.signin', code=classroom['code']))
    return student, None


def _lobby_feedback(code):
    return redirect(url_for('classroom.lobby', code=code) + '#feedback')


def class_phase(classroom):
    """0 Building, 1 Locked, 2 Feedback open, 3 Feedback closed (comments shown to groups)."""
    if classroom['feedback_released'] and not classroom['feedback_open']:
        return 3
    if classroom['feedback_open']:
        return 2
    if classroom['surveys_locked']:
        return 1
    return 0


# --- Viewing other groups' surveys ---

def can_view_survey(classroom, survey, student):
    """Classmates can look at a survey once it has gone live (see survey_commentable)."""
    if _is_host(classroom):
        return True
    if not student:
        return False
    if fb.is_own_survey(survey['id'], student['id']):
        return True
    return fb.survey_commentable(classroom, survey)


@bp.route('/survey/<int:survey_id>/view')
def view_survey(code, survey_id):
    """Read-only overview of every arm's questions side by side, for writing feedback."""
    classroom = _classroom(code)
    student = get_signed_in_student(classroom)
    if not student and not _is_host(classroom):
        return redirect(url_for('account.signin', code=code))
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id']:
        abort(404)
    if not can_view_survey(classroom, survey, student):
        flash('You can look at other groups\' surveys once they have run.', 'danger')
        return redirect(url_for('classroom.lobby', code=code))
    from routes.reminders import view_data
    return render_template('feedback/view_survey.html', classroom=classroom, survey=survey,
                           reminders=view_data(classroom, survey), is_host=_is_host(classroom))


# --- Writing comments ---

def _check_target(classroom, student, survey_id):
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id']:
        abort(404)
    if fb.is_own_survey(survey_id, student['id']) or not fb.survey_commentable(classroom, survey):
        abort(403)
    return survey


@bp.route('/feedback/<int:survey_id>', methods=['POST'])
def save_comment(code, survey_id):
    classroom = _classroom(code)
    student, denied = _student_or_redirect(classroom)
    if denied:
        return denied
    _check_target(classroom, student, survey_id)
    body = request.form.get('body', '').strip()[:MAX_COMMENT_LENGTH]
    send = request.form.get('action') == 'send'
    existing = fb.get_feedback(survey_id, student['id'])

    if send or (existing and existing['sent_at']):
        if not classroom['feedback_open']:
            flash('Comments are not open right now.', 'danger')
            return _lobby_feedback(code)
        if not body:
            flash('Write something before sending.', 'danger')
            return _lobby_feedback(code)
    fb.save_feedback(survey_id, student['id'], body, send=send or bool(existing and existing['sent_at']))
    flash('Comment sent.' if send else 'Draft saved (only you can see it).', 'success')
    return _lobby_feedback(code)


@bp.route('/feedback/<int:survey_id>/note', methods=['POST'])
def save_note(code, survey_id):
    """Private note from the live-session screen; becomes the draft of the comment."""
    classroom = _classroom(code)
    student = get_signed_in_student(classroom)
    if not student:
        return jsonify({'ok': False}), 401
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or fb.is_own_survey(survey_id, student['id'])             or not fb.survey_commentable(classroom, survey):
        return jsonify({'ok': False}), 403
    existing = fb.get_feedback(survey_id, student['id'])
    if existing and existing['sent_at']:
        return jsonify({'ok': False, 'reason': 'already_sent'})
    body = ((request.get_json(silent=True) or {}).get('body') or '').strip()[:MAX_COMMENT_LENGTH]
    fb.save_feedback(survey_id, student['id'], body, send=False)
    return jsonify({'ok': True})


@bp.route('/feedback/<int:survey_id>/note')
def get_note(code, survey_id):
    classroom = _classroom(code)
    student = get_signed_in_student(classroom)
    if not student:
        return jsonify({'ok': False}), 401
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or not fb.survey_commentable(classroom, survey):
        return jsonify({'ok': False, 'reason': 'not_live'})  # the page then hides the note box
    if fb.is_own_survey(survey_id, student['id']):
        return jsonify({'ok': True, 'own': True})
    existing = fb.get_feedback(survey_id, student['id']) or {}
    return jsonify({'ok': True, 'body': existing.get('body', ''), 'sent': bool(existing.get('sent_at'))})


@bp.route('/feedback/add', methods=['POST'])
def add_extra(code):
    classroom = _classroom(code)
    student, denied = _student_or_redirect(classroom)
    if denied:
        return denied
    survey_id = request.form.get('survey_id', type=int)
    _check_target(classroom, student, survey_id)
    if not fb.get_feedback(survey_id, student['id']):
        fb.save_feedback(survey_id, student['id'], '', send=False)
    return _lobby_feedback(code)


@bp.route('/feedback/<int:survey_id>/delete', methods=['POST'])
def delete_comment(code, survey_id):
    classroom = _classroom(code)
    student, denied = _student_or_redirect(classroom)
    if denied:
        return denied
    _check_target(classroom, student, survey_id)
    if fb.is_required(classroom, survey_id, student['id']):
        flash('Required comments can be edited but not removed.', 'danger')
        return _lobby_feedback(code)
    existing = fb.get_feedback(survey_id, student['id'])
    if existing and existing['sent_at'] and not classroom['feedback_open']:
        flash('Comments are closed, so sent comments can no longer be removed.', 'danger')
        return _lobby_feedback(code)
    fb.delete_feedback(survey_id, student['id'])
    flash('Comment removed.', 'success')
    return _lobby_feedback(code)


# --- Answering surveys opened early ---

@bp.route('/student/open/<int:survey_id>')
def answer_open_survey(code, survey_id):
    classroom = _classroom(code)
    student, denied = _student_or_redirect(classroom)
    if denied:
        return denied
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or not survey['early_open']:
        abort(404)
    ensure_participant_session(classroom, student)
    return render_template('student/session.html', classroom=classroom, open_survey=survey,
                           participant_id=session['participant_id'], student_id=session['student_id'],
                           student_name=session['student_name'],
                           state_url=url_for('feedback.open_survey_state', code=code, survey_id=survey_id),
                           submit_url=url_for('student.submit_answer_http', code=code))


@bp.route('/student/open/<int:survey_id>/state')
def open_survey_state(code, survey_id):
    from sockets.events import _build_assignment_payload, _get_survey_with_arms_and_questions, _is_fully_answered
    classroom = _classroom(code)
    student = get_signed_in_student(classroom)
    if not student:
        return jsonify({'ok': False, 'error': 'not_logged_in'}), 401
    ensure_participant_session(classroom, student)
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or not survey['early_open']:
        return jsonify({'ok': False}), 404
    db = get_db()
    if _is_fully_answered(db, session['participant_id'], survey_id):
        return jsonify({'ok': True, 'state': 'submitted', 'survey_id': survey_id})
    if classroom['block_designers'] and fb.is_own_survey(survey_id, student['id']):
        return jsonify({'ok': True, 'state': 'blocked_designer', 'survey_id': survey_id})
    if not fb.early_survey_is_open(survey):
        return jsonify({'ok': True, 'state': 'closed', 'survey_id': survey_id})
    s, arms, questions = _get_survey_with_arms_and_questions(db, survey_id)
    return jsonify({'ok': True, 'state': 'assignment',
                    'assignment': _build_assignment_payload(s, arms, questions, session['student_id'])})


@bp.route('/builder/<int:survey_id>/submit-early', methods=['POST'])
def submit_early(code, survey_id):
    """A group the host allowed to deploy early submits its survey: it locks and opens to the class."""
    classroom = _classroom(code)
    student, denied = _student_or_redirect(classroom)
    if denied:
        return denied
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or not fb.is_own_survey(survey_id, student['id']):
        abort(403)
    if not survey['early_allowed']:
        flash('Your instructor has not enabled early deployment for this survey.', 'danger')
        return redirect(url_for('builder.edit', code=code, survey_id=survey_id))
    if survey['part2_from'] is not None:
        flash('Two-part surveys open from the lobby on their own dates (see "Part 2 and reminders").', 'danger')
        return redirect(url_for('builder.edit', code=code, survey_id=survey_id))
    from models.survey import survey_incomplete
    if survey_incomplete(survey):
        flash('Finish the survey before submitting it (see "Not finished yet" at the top).', 'danger')
        return redirect(url_for('builder.edit', code=code, survey_id=survey_id))
    deadline_utc = request.form.get('deadline_utc', '').strip()
    label = request.form.get('deadline_label', '').strip()[:40]
    if not fb.parse_utc(deadline_utc) or not label:
        flash('Choose the date by which classmates should answer.', 'danger')
        return redirect(url_for('builder.edit', code=code, survey_id=survey_id))
    db = get_db()
    db.execute('UPDATE survey SET early_open=1, early_deadline_utc=?, early_deadline_label=? WHERE id=?',
               (deadline_utc, label, survey_id))
    db.commit()
    flash(f'Survey submitted! Classmates can answer it from their lobby until {label}. '
          'It is now locked; ask your instructor if you need to change it.', 'success')
    return redirect(url_for('builder.edit', code=code, survey_id=survey_id))


# --- Host controls ---

def _host_classroom(code):
    classroom = _classroom(code)
    if not _is_host(classroom):
        abort(403)
    return classroom


@bp.route('/host/phase', methods=['POST'])
def set_phase(code):
    """Class phase: the 'Next step' button or individual switches. Nothing is ever deleted."""
    classroom = _host_classroom(code)
    db = get_db()
    action = request.form.get('action', '')
    fields = {}
    if action == 'next':
        step = class_phase(classroom)
        if step == 0:
            fields = {'surveys_locked': 1}
        elif step == 1:
            fields = {'feedback_open': 1}
        elif step == 2:
            fields = {'feedback_open': 0, 'feedback_released': 1}
    elif action in ('surveys_locked', 'feedback_open', 'feedback_released'):
        fields = {action: 1 if request.form.get('value') == '1' else 0}
    elif action == 'reviews_required':
        n = request.form.get('reviews_required', type=int)
        if n is None or n < 0 or n > 20:
            flash('Required comments per student must be between 0 and 20.', 'danger')
            return redirect(url_for('host.home', code=code))
        fields = {'reviews_required': n}
    elif action == 'max_questions':
        raw = request.form.get('max_questions', '').strip()
        if raw and (not raw.isdigit() or int(raw) < 1):
            flash('Max questions per survey must be a whole number of at least 1 (or empty for no limit).', 'danger')
            return redirect(url_for('host.home', code=code))
        fields = {'max_questions_per_survey': int(raw) if raw else None}
        flash('Question limit saved: ' + (f'{raw} per survey.' if raw else 'no limit.'), 'success')

    elif action == 'reminders_until':
        raw = request.form.get('reminders_until', '').strip()
        from models.reminders import _date, nice_date
        if raw and not _date(raw):
            flash('Choose a valid date (or leave it empty for no limit).', 'danger')
            return redirect(url_for('host.home', code=code))
        fields = {'reminders_until': raw or None}
        flash('Reminders and part 2 can now run ' + (f'until {nice_date(_date(raw))}.' if raw else 'on any date.'), 'success')

    for col, val in fields.items():
        db.execute(f'UPDATE classroom SET {col}=? WHERE id=?', (val, classroom['id']))
    db.commit()

    classroom = _classroom(code)
    # Assign reviewers as soon as groups are final, so students know whose surveys to watch
    if fb.feedback_started(classroom):
        if fields.get('surveys_locked') or fields.get('feedback_open') or 'reviews_required' in fields:
            fb.ensure_assignments(classroom)
    return redirect(url_for('host.home', code=code) + '#phase')


@bp.route('/host/survey/<int:survey_id>/early', methods=['POST'])
def host_early(code, survey_id):
    """Allow/disallow early deployment, or unlock a survey a group submitted early."""
    classroom = _host_classroom(code)
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id']:
        abort(404)
    action = request.form.get('action')
    db = get_db()
    if action == 'allow':
        db.execute('UPDATE survey SET early_allowed=1 WHERE id=?', (survey_id,))
    elif action == 'disallow':
        db.execute('UPDATE survey SET early_allowed=0, early_open=0 WHERE id=?', (survey_id,))
    elif action == 'unlock':
        db.execute('UPDATE survey SET early_open=0 WHERE id=?', (survey_id,))
    db.commit()
    return redirect(url_for('builder.index', code=code))


@bp.route('/download/feedback')
def download_feedback(code):
    classroom = _host_classroom(code)
    from models.download import export_feedback_csv
    return Response(export_feedback_csv(classroom), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=feedback.csv'})


@bp.route('/download/feedback-summary')
def download_feedback_summary(code):
    classroom = _host_classroom(code)
    from models.download import export_feedback_summary_csv
    return Response(export_feedback_summary_csv(classroom), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=feedback_summary.csv'})
