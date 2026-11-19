"""Read-only results: every survey's questions and real response charts, without going live.

Two ways in, same page (templates/results/results.html + host.js, the live dashboard's results area):
- the instructor, signed in: /c/<code>/host/results
- anyone with the class's private results link: /results/<token> (classroom.results_token; the instructor creates,
  replaces or turns it off on the instructor home). No password, no names, nothing can be changed or opened on phones.
"""
import hmac
import secrets

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from models.db import get_db

bp = Blueprint('results', __name__)


def _classroom_by_code(code):
    from models.classroom import get_classroom_by_code
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


def _host(code):
    classroom = _classroom_by_code(code)
    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return classroom, False
    return classroom, True


def _classroom_by_token(token):
    """The classroom whose results link this is (compared in constant time), or 404."""
    if not token or len(token) < 20:
        abort(404)
    row = get_db().execute('SELECT * FROM classroom WHERE results_token=?', (token,)).fetchone()
    if not row or not hmac.compare_digest(row['results_token'], token):
        abort(404)
    return dict(row)


def _surveys(classroom):
    from models.live import live_sequence
    from models.survey import list_surveys
    db = get_db()
    counts = dict(db.execute('SELECT r.survey_id, COUNT(DISTINCT r.participant_id) FROM response r JOIN survey s '
                             'ON s.id = r.survey_id WHERE s.classroom_id=? GROUP BY r.survey_id',
                             (classroom['id'],)).fetchall())
    surveys = live_sequence(classroom, list_surveys(classroom['id']))
    for s in surveys:
        s['respondents'] = counts.get(s['id'], 0)
    return surveys


def _page(classroom, surveys, link_for, state_url_for, shared):
    runnable = [s for s in surveys if not s['external']]
    chosen = request.args.get('survey', type=int)
    survey = next((s for s in runnable if s['id'] == chosen), None) \
        or next((s for s in runnable if s['respondents']), None) or (runnable[0] if runnable else None)
    return render_template('results/results.html', classroom=classroom, surveys=surveys, survey=survey,
                           link_for=link_for, state_url=state_url_for(survey['id']) if survey else None, shared=shared)


def _state(classroom, survey_id):
    from sockets.events import _get_aggregated_results
    db = get_db()
    row = db.execute('SELECT id FROM survey WHERE id=? AND classroom_id=? AND external=0',
                     (survey_id, classroom['id'])).fetchone()
    if not row:
        return jsonify({'ok': False}), 404
    results = _get_aggregated_results(db, survey_id)
    n = db.execute('SELECT COUNT(*) FROM roster_student WHERE classroom_id=? AND hidden=0', (classroom['id'],)).fetchone()[0]
    if results is not None:
        results['participant_count'] = n
    return jsonify({'ok': True, 'active_survey_id': survey_id, 'participant_count': n, 'results': results})


# --- The instructor ---

@bp.route('/c/<code>/host/results')
def host_results(code):
    classroom, ok = _host(code)
    if not ok:
        return redirect(url_for('host.login', code=code))
    return _page(classroom, _surveys(classroom),
                 lambda sid: url_for('results.host_results', code=code, survey=sid),
                 lambda sid: url_for('results.host_results_state', code=code, survey=sid), shared=False)


@bp.route('/c/<code>/host/results/state')
def host_results_state(code):
    classroom, ok = _host(code)
    if not ok:
        return jsonify({'ok': False, 'error': 'not_authenticated'}), 401
    return _state(classroom, request.args.get('survey', type=int))


@bp.route('/c/<code>/host/results-link', methods=['POST'])
def results_link(code):
    """Create (or replace) the private results link, or turn it off."""
    classroom, ok = _host(code)
    if not ok:
        abort(403)
    db = get_db()
    if request.form.get('action') == 'off':
        db.execute('UPDATE classroom SET results_token=NULL WHERE id=?', (classroom['id'],))
        flash('The results link is off: it no longer opens anything.', 'success')
    else:
        db.execute('UPDATE classroom SET results_token=? WHERE id=?', (secrets.token_urlsafe(24), classroom['id']))
        flash('New results link made. Any earlier link no longer works.' if classroom.get('results_token')
              else 'Results link made. Copy it and send it to whoever needs to see the results.', 'success')
    db.commit()
    return redirect(url_for('host.home', code=code) + '#results-link')


# --- Anyone with the private link ---

@bp.route('/results/<token>')
def shared_results(token):
    classroom = _classroom_by_token(token)
    return _page(classroom, _surveys(classroom),
                 lambda sid: url_for('results.shared_results', token=token, survey=sid),
                 lambda sid: url_for('results.shared_results_state', token=token, survey=sid), shared=True)


@bp.route('/results/<token>/state')
def shared_results_state(token):
    classroom = _classroom_by_token(token)
    return _state(classroom, request.args.get('survey', type=int))
