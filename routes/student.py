from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from models.participant import login_or_create

bp = Blueprint('student', __name__, url_prefix='/student')


@bp.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        student_id = request.form.get('student_id', '').strip()

        if not name or not student_id:
            flash('Please enter both your name and student ID.', 'danger')
            return render_template('student/login.html')

        participant = login_or_create(name, student_id)
        session['participant_id'] = participant['id']
        session['student_id'] = participant['student_id']
        session['student_name'] = participant['name']
        return redirect(url_for('student.live_session'))

    # If already logged in, go to session
    if 'participant_id' in session:
        return redirect(url_for('student.live_session'))

    return render_template('student/login.html')


@bp.route('/session')
def live_session():
    if 'participant_id' not in session:
        return redirect(url_for('student.login'))

    return render_template('student/session.html',
                           participant_id=session['participant_id'],
                           student_id=session['student_id'],
                           student_name=session['student_name'])
