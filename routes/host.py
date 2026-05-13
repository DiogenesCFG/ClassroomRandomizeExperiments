from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, jsonify

from models.classroom import get_classroom_by_code, check_host_password
from models.db import get_db
from models.survey import list_surveys

bp = Blueprint('host', __name__, url_prefix='/c/<code>/host')


def _get_classroom_or_404(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


@bp.route('/', methods=['GET', 'POST'])
def login(code):
    classroom = _get_classroom_or_404(code)

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        if check_host_password(classroom['id'], password):
            session[f'host_authenticated_{classroom["id"]}'] = True
            return redirect(url_for('host.dashboard', code=code))
        else:
            flash('Incorrect host password.', 'danger')

    # If already authenticated, go straight to dashboard
    if session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.dashboard', code=code))

    return render_template('host/login.html', classroom=classroom)


@bp.route('/dashboard')
def dashboard(code):
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.login', code=code))

    surveys = list_surveys(classroom['id'])
    return render_template('host/dashboard.html',
                           surveys=surveys,
                           classroom=classroom)


@bp.route('/debug')
def debug(code):
    """Diagnostic endpoint: shows database state for debugging."""
    classroom = _get_classroom_or_404(code)
    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.login', code=code))

    db = get_db()
    classroom_id = classroom['id']

    # Check indexes on response table
    indexes = db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='response'"
    ).fetchall()

    # Check response table columns
    columns = db.execute('PRAGMA table_info(response)').fetchall()

    # Count surveys and their questions
    surveys = db.execute(
        'SELECT s.id, s.title, s.group_number, s.is_active, '
        '(SELECT COUNT(*) FROM survey_question WHERE survey_id=s.id) as q_count, '
        '(SELECT COUNT(*) FROM survey_arm WHERE survey_id=s.id) as arm_count '
        'FROM survey s WHERE s.classroom_id=? ORDER BY s.group_number',
        (classroom_id,)
    ).fetchall()

    # Count responses
    responses = db.execute(
        'SELECT r.id, r.participant_id, r.survey_id, r.arm_id, r.question_id, '
        'r.answer_text, r.answered_at '
        'FROM response r '
        'JOIN survey s ON r.survey_id=s.id '
        'WHERE s.classroom_id=? ORDER BY r.id DESC LIMIT 20',
        (classroom_id,)
    ).fetchall()

    # Count participants
    participants = db.execute(
        'SELECT COUNT(*) as cnt FROM participant WHERE classroom_id=?',
        (classroom_id,)
    ).fetchone()['cnt']

    return jsonify({
        'classroom': {'id': classroom_id, 'code': classroom['code'], 'name': classroom['name']},
        'response_table': {
            'columns': [{'name': c['name'], 'type': c['type']} for c in columns],
            'indexes': [{'name': i['name'], 'sql': i['sql']} for i in indexes],
        },
        'surveys': [dict(s) for s in surveys],
        'recent_responses': [dict(r) for r in responses],
        'participant_count': participants,
    })
