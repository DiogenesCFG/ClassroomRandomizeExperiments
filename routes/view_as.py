"""The instructor's read-only student view.

From the roster, "View as student" makes this browser see the site exactly as that student does (lobby, survey
page, previews, comments), without changing anything:
  - the session temporarily holds the student's sign-in instead of the instructor's (saved in session['viewas'],
    restored on exit), so every page behaves as it does for them;
  - every request that isn't a plain page view (forms, saves) is stopped before it runs;
  - the database connection is read-only (models/db.py: PRAGMA query_only), so even a page that tried to write
    couldn't; pages that normally write when opened skip it (is_read_only()).
Visiting an instructor page, or the Exit button in the banner, ends the view.
"""
import sqlite3

from flask import Blueprint, flash, jsonify, redirect, request, session, url_for, abort

from models.classroom import get_classroom_by_code

bp = Blueprint('view_as', __name__)

# Session keys a student view changes (restored exactly on exit)
LIVE_KEYS = ('participant_id', 'student_id', 'student_name', 'classroom_id', 'classroom_code', 'classroom_name')


def _keys(cid):
    return (f'host_authenticated_{cid}', f'classroom_joined_{cid}', f'roster_student_{cid}') + LIVE_KEYS


@bp.route('/c/<code>/host/roster/<int:student_id>/view-as', methods=['POST'])
def start(code, student_id):
    classroom = get_classroom_by_code(code)
    if not classroom or not session.get(f'host_authenticated_{classroom["id"]}'):
        abort(403)
    from models import roster as roster_model
    student = roster_model.get_student(classroom['id'], student_id)
    if not student or student['hidden']:
        flash('Choose a student on the roster.', 'danger')
        return redirect(url_for('roster.index', code=code))
    end()  # one view at a time
    cid = classroom['id']
    session['viewas'] = {'cid': cid, 'code': classroom['code'], 'sid': student['id'], 'name': student['full_name'],
                         'saved': {k: session.get(k) for k in _keys(cid)}}
    for k in LIVE_KEYS:
        session.pop(k, None)
    session.pop(f'host_authenticated_{cid}', None)
    session[f'classroom_joined_{cid}'] = True
    session[f'roster_student_{cid}'] = student['id']
    return redirect(url_for('classroom.lobby', code=code))


def end():
    """Restore the instructor's session. Returns the classroom code that was being viewed, or None."""
    view = session.pop('viewas', None)
    if not view:
        return None
    for k, v in view['saved'].items():
        if v is None:
            session.pop(k, None)
        else:
            session[k] = v
    return view['code']


@bp.route('/view-as/exit', methods=['POST'])
def exit_view():
    code = end()
    flash('Back in instructor mode. Nothing was changed while viewing as the student.', 'info')
    return redirect(url_for('roster.index', code=code) if code else url_for('main.index'))


HOST_BLUEPRINTS = ('host', 'roster', 'download')


def guard():
    """Before every request: in a student view, stop anything that would save, and leave the view on instructor pages."""
    view = session.get('viewas')
    if not view or request.endpoint in ('view_as.exit_view', 'static'):
        return None
    if (request.blueprint or '') in HOST_BLUEPRINTS:
        end()  # an instructor page: back to instructor mode, then show it
        flash('Left the student view.', 'info')
        return None
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    message = 'Student view (read-only): nothing was saved. Exit the view to make changes.'
    if request.headers.get('Sec-Fetch-Mode', 'navigate') != 'navigate':
        # A background request from the page's script (autosave, notes, tours...)
        return jsonify({'ok': False, 'reason': 'read_only', 'errors': [message], 'error': message})
    flash(message, 'warning')
    return redirect(request.referrer or url_for('classroom.lobby', code=view['code']))


def readonly_error(e):
    """A write that slipped past the guard hits the read-only database: say so instead of a server error."""
    text = str(e).lower()
    if session.get('viewas') and ('readonly' in text or 'read-only' in text or 'query_only' in text):
        flash('Student view (read-only): that page tried to save something, so it was blocked. Nothing changed.', 'warning')
        return redirect(url_for('classroom.lobby', code=session['viewas']['code']))
    raise e
