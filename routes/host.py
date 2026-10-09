from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, jsonify

from models.classroom import get_classroom_by_code, check_host_password, delete_classroom as delete_classroom_model
from models.db import get_db
from models.survey import list_surveys, with_todo

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
            return redirect(url_for('host.home', code=code))
        else:
            flash('Incorrect host password.', 'danger')

    # If already authenticated, go straight to the instructor home
    if session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.home', code=code))

    return render_template('host/login.html', classroom=classroom)


@bp.route('/logout', methods=['POST'])
def logout(code):
    classroom = _get_classroom_or_404(code)
    session.pop(f'host_authenticated_{classroom["id"]}', None)
    flash('Logged out of the instructor pages.', 'success')
    return redirect(url_for('main.index'))


@bp.route('/home')
def home(code):
    """Instructor home: everything between classes (phase, roster, surveys, downloads)."""
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.login', code=code))

    from models import feedback as fb
    from routes.feedback import class_phase
    db = get_db()
    surveys = list_surveys(classroom['id'])
    roster = db.execute('SELECT COUNT(*) AS n, SUM(password_hash IS NOT NULL) AS signed_up FROM roster_student '
                        'WHERE classroom_id=? AND hidden=0', (classroom['id'],)).fetchone()
    has_assignments = fb.assignments_exist(classroom['id'])
    done, total = fb.feedback_progress(classroom) if has_assignments else (0, 0)
    from models import reminders
    from models.survey import get_survey
    to_approve = [s for s in surveys if (s['reminder_plan'] or s['part2_from'] is not None) and not s['external']
                  and reminders.approval_state(get_survey(s['id'])) in ('pending', 'changed')]
    return render_template('host/home.html',
                           classroom=classroom,
                           surveys=surveys,
                           roster_count=roster['n'] or 0,
                           signed_up=roster['signed_up'] or 0,
                           response_count=db.execute(
                               'SELECT COUNT(*) FROM (SELECT DISTINCT r.participant_id, r.survey_id FROM response r '
                               'JOIN survey s ON r.survey_id = s.id WHERE s.classroom_id=?)',
                               (classroom['id'],)).fetchone()[0],
                           phase=class_phase(classroom),
                           to_approve=to_approve,
                           has_assignments=has_assignments,
                           feedback_done=done, feedback_students=total)


@bp.route('/dashboard')
def dashboard(code):
    """Live session: run surveys one by one, with the QR code and results."""
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.login', code=code))

    from models import reminders
    surveys = with_todo(list_surveys(classroom['id']))
    # ?survey=ID&part=N: launch just that survey (or one part of it), e.g. a part run outside
    # the live session's sequence. The sequence otherwise runs each survey's live part once.
    single = request.args.get('survey', type=int)
    if single:
        surveys = [s for s in surveys if s['id'] == single and not s['external']]
        if not surveys:
            abort(404)
    for s in surveys:
        s['two_part'] = reminders.is_two_part(s)
        if single:
            part = request.args.get('part', type=int)
            s['run_part'] = part if s['two_part'] and part in (1, 2) else (reminders.sequence_part(s) or 1)
        else:
            s['run_part'] = reminders.sequence_part(s)
        s['ran'] = bool(s['run_part']) and reminders.part_ran(s, s['run_part'])
    return render_template('host/dashboard.html', surveys=surveys, classroom=classroom, single=bool(single))


@bp.route('/demo')
def demo(code):
    """Demo dashboard: every survey's questions, images and sample charts, one click each,
    without running anything (made-up answers, like the groups' dashboard preview)."""
    classroom = _get_classroom_or_404(code)
    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.login', code=code))
    from models.survey import get_survey
    from routes.builder import preview_dashboard_context
    surveys = [s for s in with_todo(list_surveys(classroom['id']))]
    runnable = [s for s in surveys if not s['external']]
    if not runnable:
        flash('There are no surveys to show yet.', 'info')
        return redirect(url_for('host.home', code=code))
    chosen = request.args.get('survey', type=int)
    survey = get_survey(chosen if any(s['id'] == chosen for s in runnable) else runnable[0]['id'])
    return render_template('builder/preview_dashboard.html', demo_surveys=surveys,
                           **preview_dashboard_context(classroom, survey))


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
        'SELECT * FROM survey WHERE id=? AND classroom_id=? AND external=0',
        (survey_id, classroom['id']),
    ).fetchone()
    if not survey:
        return jsonify({'ok': False, 'error': 'survey_not_found'}), 404

    _launch(db, classroom, dict(survey), data.get('part'))

    # Notify students of the new active survey
    socketio.emit('survey_activated', {
        'survey_id': survey_id,
        'group_number': survey['group_number'],
        'title': survey['title'],
    }, room=f'students_{classroom["id"]}')

    # Return results directly to the host via HTTP response
    results = _get_aggregated_results(db, survey_id)
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

    # The next survey (by group number) whose live-session part hasn't run yet: parts run
    # separately, remote parts, and surveys launched on their own earlier are skipped
    from models import reminders
    after = current['group_number'] if current else -1
    next_row = None
    for row in db.execute('SELECT * FROM survey WHERE group_number > ? AND classroom_id=? AND external=0 '
                          'ORDER BY group_number', (after, classroom['id'])).fetchall():
        part = reminders.sequence_part(dict(row))
        if part and not reminders.part_ran(dict(row), part):
            next_row = row
            break
    if current:
        db.execute('UPDATE survey SET is_active=0 WHERE id=?', (current['id'],))

    if not next_row:
        db.commit()
        socketio.emit('survey_deactivated', {}, room=f'students_{classroom["id"]}')
        return jsonify({'ok': True, 'done': True, 'results': None})

    _launch(db, classroom, dict(next_row), None)

    # Notify students of the new active survey
    socketio.emit('survey_activated', {
        'survey_id': next_row['id'],
        'group_number': next_row['group_number'],
        'title': next_row['title'],
    }, room=f'students_{classroom["id"]}')

    # Return results directly to the host via HTTP response
    results = _get_aggregated_results(db, next_row['id'])
    return jsonify({'ok': True, 'done': False, 'results': results})


def _launch(db, classroom, survey, part):
    """Make this survey (one part of a two-part survey) the one students answer now."""
    from models import reminders
    if not reminders.is_two_part(survey) or part not in (1, 2):
        part = reminders.sequence_part(survey) or 1
    db.execute('UPDATE survey SET is_active=0 WHERE is_active=1 AND classroom_id=?', (classroom['id'],))
    db.execute(f"UPDATE survey SET is_active=1, went_live=1, active_part=?, "
               f"part{part}_ran=COALESCE(part{part}_ran, datetime('now')) WHERE id=?", (part, survey['id']))
    db.commit()


@bp.route('/survey/<int:survey_id>/run-again', methods=['POST'])
def run_again(code, survey_id):
    """Start a survey over: delete its responses (and notification sign-ups) and forget that it ran,
    so the live session runs it again. For a group that changed its survey after running it."""
    from models.classroom import check_host_password
    classroom = _get_classroom_or_404(code)
    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.login', code=code))
    if not check_host_password(classroom['id'], request.form.get('host_password', '').strip()):
        flash('Incorrect host password.', 'danger')
        return redirect(url_for('builder.index', code=code))
    db = get_db()
    survey = db.execute('SELECT * FROM survey WHERE id=? AND classroom_id=?', (survey_id, classroom['id'])).fetchone()
    if not survey:
        abort(404)
    for table in ('response', 'reminder_action', 'push_subscription'):
        db.execute(f'DELETE FROM {table} WHERE survey_id=?', (survey_id,))
    db.execute('UPDATE survey SET is_active=0, active_part=NULL, part1_ran=NULL, part2_ran=NULL WHERE id=?',
               (survey_id,))
    db.commit()
    flash(f'Group {survey["group_number"]}: responses deleted. The survey will run again in the live session.',
          'success')
    return redirect(url_for('builder.index', code=code))


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

    # Notify students that session is reset
    socketio.emit('survey_deactivated', {}, room=f'students_{classroom["id"]}')
    return jsonify({'ok': True})


@bp.route('/toggle-block-designers', methods=['POST'])
def toggle_block_designers(code):
    """Toggle whether survey designers are blocked from participating in their own survey."""
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401

    db = get_db()
    current = db.execute(
        'SELECT block_designers FROM classroom WHERE id=?', (classroom['id'],)
    ).fetchone()
    new_val = 0 if current['block_designers'] else 1
    db.execute('UPDATE classroom SET block_designers=? WHERE id=?', (new_val, classroom['id']))
    db.commit()
    return jsonify({'ok': True, 'block_designers': bool(new_val)})



@bp.route('/delete-classroom', methods=['POST'])
def delete_classroom(code):
    """Delete the entire classroom and all its data."""
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401

    password = request.form.get('host_password', '').strip()
    if not check_host_password(classroom['id'], password):
        flash('Incorrect host password.', 'danger')
        return redirect(url_for('host.home', code=code))

    from routes.builder import _delete_upload

    removed_files = delete_classroom_model(classroom['id'])
    for fn in removed_files:
        _delete_upload(fn)

    session.pop(f'host_authenticated_{classroom["id"]}', None)
    return redirect(url_for('main.index'))


@bp.route('/images')
def image_gallery(code):
    """View all uploaded images for this classroom's surveys."""
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.login', code=code))

    db = get_db()
    images = db.execute(
        'SELECT aq.image_filename, sq.label AS question_label, sq.question_index, '
        '       sa.label AS arm_label, s.title AS survey_title, s.group_number '
        'FROM arm_question aq '
        'JOIN survey_arm sa ON aq.arm_id = sa.id '
        'JOIN survey_question sq ON aq.question_id = sq.id '
        'JOIN survey s ON sa.survey_id = s.id '
        'WHERE s.classroom_id = ? AND aq.image_filename IS NOT NULL '
        'ORDER BY s.group_number, sq.question_index, sa.arm_index',
        (classroom['id'],),
    ).fetchall()

    return render_template('host/gallery.html', classroom=classroom, images=images)


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
