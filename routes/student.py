from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort

from models.classroom import get_classroom_by_code
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
