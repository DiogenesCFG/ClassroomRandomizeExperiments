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


@bp.route('/state')
def state(code):
    """HTTP fallback for participant count and active survey results."""
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401

    from sockets.events import _get_aggregated_results

    db = get_db()
    classroom_id = classroom['id']

    participant_count = db.execute(
        'SELECT COUNT(*) as cnt FROM participant WHERE classroom_id=?',
        (classroom_id,),
    ).fetchone()['cnt']

    active = db.execute(
        'SELECT id FROM survey WHERE is_active=1 AND classroom_id=?',
        (classroom_id,),
    ).fetchone()

    if not active:
        return jsonify({
            'ok': True,
            'participant_count': participant_count,
            'active_survey_id': None,
            'results': None,
        })

    results = _get_aggregated_results(db, active['id'])
    return jsonify({
        'ok': True,
        'participant_count': participant_count,
        'active_survey_id': active['id'],
        'results': results,
    })


@bp.route('/activate', methods=['POST'])
def activate_http(code):
    """HTTP fallback for activating a survey."""
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401

    from app import socketio
    from sockets.events import _get_aggregated_results

    data = request.get_json(silent=True) or {}
    survey_id = data.get('survey_id')
    if not survey_id:
        return jsonify({'ok': False, 'error': 'missing_survey_id'}), 400

    db = get_db()
    survey = db.execute(
        'SELECT id, group_number, title FROM survey WHERE id=? AND classroom_id=?',
        (survey_id, classroom['id']),
    ).fetchone()
    if not survey:
        return jsonify({'ok': False, 'error': 'survey_not_found'}), 404

    db.execute('UPDATE survey SET is_active=0 WHERE is_active=1 AND classroom_id=?', (classroom['id'],))
    db.execute('UPDATE survey SET is_active=1 WHERE id=?', (survey_id,))
    db.commit()

    socketio.emit('survey_activated', {
        'survey_id': survey_id,
        'group_number': survey['group_number'],
        'title': survey['title'],
    }, room=f'students_{classroom["id"]}')

    results = _get_aggregated_results(db, survey_id)
    if results:
        socketio.emit('results_update', results, room=f'host_{classroom["id"]}')

    return jsonify({'ok': True, 'results': results})


@bp.route('/next', methods=['POST'])
def next_http(code):
    """HTTP fallback for advancing to the next survey."""
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401

    from app import socketio
    from sockets.events import _get_aggregated_results

    db = get_db()
    current = db.execute(
        'SELECT * FROM survey WHERE is_active=1 AND classroom_id=?',
        (classroom['id'],),
    ).fetchone()

    if current:
        next_row = db.execute(
            'SELECT id, group_number, title FROM survey WHERE group_number > ? AND classroom_id=? '
            'ORDER BY group_number LIMIT 1',
            (current['group_number'], classroom['id']),
        ).fetchone()
        db.execute('UPDATE survey SET is_active=0 WHERE id=?', (current['id'],))
    else:
        next_row = db.execute(
            'SELECT id, group_number, title FROM survey WHERE classroom_id=? ORDER BY group_number LIMIT 1',
            (classroom['id'],),
        ).fetchone()

    if not next_row:
        db.commit()
        socketio.emit('survey_deactivated', {}, room=f'students_{classroom["id"]}')
        socketio.emit('all_done', {}, room=f'host_{classroom["id"]}')
        return jsonify({'ok': True, 'done': True, 'results': None})

    db.execute('UPDATE survey SET is_active=1 WHERE id=?', (next_row['id'],))
    db.commit()

    socketio.emit('survey_activated', {
        'survey_id': next_row['id'],
        'group_number': next_row['group_number'],
        'title': next_row['title'],
    }, room=f'students_{classroom["id"]}')

    results = _get_aggregated_results(db, next_row['id'])
    if results:
        socketio.emit('results_update', results, room=f'host_{classroom["id"]}')
        socketio.emit('survey_changed', {'survey_id': next_row['id']}, room=f'host_{classroom["id"]}')

    return jsonify({'ok': True, 'done': False, 'results': results})


@bp.route('/reset', methods=['POST'])
def reset_http(code):
    """HTTP fallback for resetting the live session."""
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401

    from app import socketio

    db = get_db()
    db.execute('UPDATE survey SET is_active=0 WHERE is_active=1 AND classroom_id=?', (classroom['id'],))
    db.commit()

    socketio.emit('survey_deactivated', {}, room=f'students_{classroom["id"]}')
    socketio.emit('session_reset', {}, room=f'host_{classroom["id"]}')
    return jsonify({'ok': True})


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
