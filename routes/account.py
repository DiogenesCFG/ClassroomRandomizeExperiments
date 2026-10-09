"""Student accounts (roster sign-in) and teams."""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, jsonify

from models.classroom import get_classroom_by_code
from models.db import get_db
from models.participant import login_or_create
from models import roster as roster_model

bp = Blueprint('account', __name__, url_prefix='/c/<code>')

MIN_PASSWORD_LENGTH = 6
NOT_FOUND_MSG = 'ID not found. Try again or contact your instructor.'


def _get_roster_classroom(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


def _has_classroom_access(classroom):
    return session.get(f'classroom_joined_{classroom["id"]}') or \
        session.get(f'host_authenticated_{classroom["id"]}')


def get_signed_in_student(classroom):
    """Return the signed-in roster student for this classroom, or None."""
    rid = session.get(f'roster_student_{classroom["id"]}')
    if not rid:
        return None
    student = roster_model.get_student(classroom['id'], rid)
    if not student or student['hidden'] or not student['password_hash']:
        # Removed from the roster or password reset since signing in
        session.pop(f'roster_student_{classroom["id"]}', None)
        return None
    return student


def ensure_participant_session(classroom, student):
    """Point the live-session keys (participant_id etc.) at this roster student."""
    if session.get('classroom_id') == classroom['id'] and session.get('student_id') == student['sis_id'] \
            and 'participant_id' in session:
        return
    participant = login_or_create(student['full_name'], student['sis_id'], classroom['id'])
    session['participant_id'] = participant['id']
    session['student_id'] = participant['student_id']
    session['student_name'] = participant['name']
    session['classroom_id'] = classroom['id']
    session['classroom_code'] = classroom['code']
    session['classroom_name'] = classroom['name']


def _require_student(classroom):
    """Return (student, None) or (None, redirect_response)."""
    if not _has_classroom_access(classroom):
        flash('Please join the classroom first.', 'danger')
        return None, redirect(url_for('classroom.join', code=classroom['code']))
    student = get_signed_in_student(classroom)
    if not student:
        return None, redirect(url_for('account.signin', code=classroom['code']))
    return student, None


# --- Sign in / out ---

@bp.route('/signin', methods=['GET', 'POST'])
def signin(code):
    classroom = _get_roster_classroom(code)
    if not _has_classroom_access(classroom):
        flash('Please join the classroom first.', 'danger')
        return redirect(url_for('classroom.join', code=code))
    if get_signed_in_student(classroom):
        return redirect(url_for('classroom.lobby', code=code))

    def render(step, student=None):
        return render_template('student/signin.html', classroom=classroom, step=step, student=student,
                               min_length=MIN_PASSWORD_LENGTH)

    pending = session.get('signin_pending') or {}
    student = None
    if pending.get('classroom_id') == classroom['id']:
        student = roster_model.get_student(classroom['id'], pending.get('roster_student_id'))
        if student and student['hidden']:
            student = None

    if request.method == 'GET' or request.form.get('step') in (None, 'restart'):
        session.pop('signin_pending', None)
        return render('id')

    step = request.form.get('step')

    if step == 'id':
        found = roster_model.get_student_by_sis(classroom['id'], request.form.get('sis_id', ''))
        if not found or found['hidden']:
            flash(NOT_FOUND_MSG, 'danger')
            return render('id')
        session['signin_pending'] = {'classroom_id': classroom['id'], 'roster_student_id': found['id'],
                                     'confirmed': False}
        return render('password' if found['password_hash'] else 'confirm', found)

    if not student:
        return render('id')

    if step == 'confirm':
        if request.form.get('answer') != 'yes':
            session.pop('signin_pending', None)
            flash("That ID belongs to someone else. Check your ID and try again, or contact your instructor.",
                  'danger')
            return render('id')
        if student['password_hash']:
            return render('password', student)
        session['signin_pending'] = {**pending, 'confirmed': True}
        return render('create', student)

    if step == 'create':
        if not pending.get('confirmed') or student['password_hash']:
            return render('password' if student['password_hash'] else 'confirm', student)
        password = request.form.get('password', '')
        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f'Your password needs at least {MIN_PASSWORD_LENGTH} characters.', 'danger')
            return render('create', student)
        if password != request.form.get('password_confirm', ''):
            flash('The passwords do not match.', 'danger')
            return render('create', student)
        roster_model.register_student(student['id'], password)
        return _complete_signin(classroom, student['id'])

    if step == 'password':
        if not roster_model.check_student_password(student, request.form.get('password', '')):
            flash('Incorrect password. If you forgot it, ask your instructor to reset it.', 'danger')
            return render('password', student)
        return _complete_signin(classroom, student['id'])

    return render('id')


def _complete_signin(classroom, roster_student_id):
    session.pop('signin_pending', None)
    session[f'roster_student_{classroom["id"]}'] = roster_student_id
    student = roster_model.get_student(classroom['id'], roster_student_id)
    ensure_participant_session(classroom, student)
    return redirect(url_for('classroom.lobby', code=classroom['code']))


@bp.route('/signout', methods=['POST'])
def signout(code):
    classroom = _get_roster_classroom(code)
    session.pop(f'roster_student_{classroom["id"]}', None)
    if session.get('classroom_id') == classroom['id']:
        for key in ('participant_id', 'student_id', 'student_name'):
            session.pop(key, None)
    return redirect(url_for('account.signin', code=code))


@bp.route('/live')
def live(code):
    """Lightweight check polled by the lobby: is a survey currently active?"""
    classroom = _get_roster_classroom(code)
    if not _has_classroom_access(classroom):
        return jsonify({'ok': False}), 401
    row = get_db().execute('SELECT 1 FROM survey WHERE is_active=1 AND classroom_id=?',
                           (classroom['id'],)).fetchone()
    return jsonify({'ok': True, 'live': row is not None})


TOURS = ('lobby', 'builder', 'builder_edit')


def tour_seen(student, name):
    return name in (student.get('tours_seen') or '').split()


@bp.route('/tour/<name>/seen', methods=['POST'])
def mark_tour_seen(code, name):
    """Remember that a student finished or closed a first-visit tour, so it doesn't start again."""
    classroom = _get_roster_classroom(code)
    student = get_signed_in_student(classroom)
    if not student or name not in TOURS:
        return jsonify({'ok': False}), 400
    names = [name, 'builder'] if name == 'builder_edit' else [name]
    if any(not tour_seen(student, n) for n in names):
        current = (student.get('tours_seen') or '').split()
        seen = ' '.join(current + [n for n in names if n not in current])
        db = get_db()
        db.execute('UPDATE roster_student SET tours_seen=? WHERE id=?', (seen, student['id']))
        db.commit()
    return jsonify({'ok': True})


# --- Teams ---

def _back_to(survey_id, code):
    if request.form.get('back') == 'edit':
        return redirect(url_for('builder.edit', code=code, survey_id=survey_id))
    return redirect(url_for('classroom.lobby', code=code))


@bp.route('/team/<int:survey_id>/invite', methods=['POST'])
def invite(code, survey_id):
    classroom = _get_roster_classroom(code)
    student, denied = _require_student(classroom)
    if denied:
        return denied
    if not roster_model.is_member(survey_id, student['id']):
        abort(403)
    if classroom['surveys_locked']:
        flash('Groups are locked by your instructor.', 'danger')
        return _back_to(survey_id, code)
    if roster_model.group_full(classroom, survey_id):
        flash(f'Your group is full: groups can have at most {classroom["max_group_size"]} members.', 'danger')
        return _back_to(survey_id, code)
    invitee_id = request.form.get('invitee_id', type=int)
    error = roster_model.invite(classroom['id'], survey_id, student['id'], invitee_id)
    if error:
        flash(error, 'danger')
    else:
        invitee = roster_model.get_student(classroom['id'], invitee_id)
        flash(f'Invite sent to {invitee["full_name"]}. They need to accept it from their lobby.', 'success')
    return _back_to(survey_id, code)


@bp.route('/group-finder', methods=['POST'])
def group_finder(code):
    """Opt in to (or out of) the group finder, where classmates without a group can find each other."""
    classroom = _get_roster_classroom(code)
    student, denied = _require_student(classroom)
    if denied:
        return denied
    if classroom['surveys_locked']:
        flash('Groups are locked by your instructor.', 'danger')
    else:
        listed = request.form.get('listed') == '1'
        roster_model.set_seeking(student['id'], listed, request.form.get('note', ''))
        flash('You are listed in the group finder: classmates without a group can see you and invite you.' if listed
              else 'You are no longer listed in the group finder.', 'success')
    return redirect(url_for('classroom.lobby', code=code) + '#finder-card')


@bp.route('/team/<int:survey_id>/leave', methods=['POST'])
def leave(code, survey_id):
    classroom = _get_roster_classroom(code)
    student, denied = _require_student(classroom)
    if denied:
        return denied
    if classroom['surveys_locked']:
        flash('Groups are locked by your instructor.', 'danger')
        return redirect(url_for('classroom.lobby', code=code))
    error = roster_model.leave_group(survey_id, student['id'])
    if error:
        flash(error, 'danger')
    else:
        flash('You left the group.', 'success')
    return redirect(url_for('classroom.lobby', code=code))


@bp.route('/team/invite/<int:invite_id>/<action>', methods=['POST'])
def respond_invite(code, invite_id, action):
    classroom = _get_roster_classroom(code)
    student, denied = _require_student(classroom)
    if denied:
        return denied
    inv = roster_model.get_invite(invite_id)
    if not inv or inv['roster_student_id'] != student['id']:
        flash('That invite no longer exists.', 'danger')
        return redirect(url_for('classroom.lobby', code=code))

    if action == 'decline':
        roster_model.delete_invite(invite_id)
        flash('Invite declined.', 'success')
    elif action == 'accept':
        if classroom['surveys_locked']:
            flash('Groups are locked by your instructor.', 'danger')
        elif roster_model.at_group_limit(classroom, student['id']):
            flash("You can't accept this invite: you're already in the maximum number of groups. "
                  "Leave a group first.", 'danger')
        elif roster_model.group_full(classroom, inv['survey_id']):
            flash(f"You can't accept this invite: that group is already full "
                  f"(at most {classroom['max_group_size']} members).", 'danger')
        else:
            roster_model.add_member(inv['survey_id'], student)
            flash('You joined the group.', 'success')
    else:
        abort(404)
    return redirect(url_for('classroom.lobby', code=code))
