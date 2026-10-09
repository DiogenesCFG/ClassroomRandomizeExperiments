"""Two-part surveys and calendar reminders: the group's plan (saved from the survey page),
the instructor's approval, part 2 answered from the lobby, and the respondent's
"add to calendar" step (logged in reminder_action). See models/reminders.py."""
from flask import (
    Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, session, url_for,
)

from models import push
from models import reminders as rem
from models.classroom import get_classroom_by_code
from models.db import get_db
from models.survey import get_survey, survey_incomplete
from routes.account import ensure_participant_session, get_signed_in_student

bp = Blueprint('reminders', __name__, url_prefix='/c/<code>')


def _classroom(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


def _is_host(classroom):
    return session.get(f'host_authenticated_{classroom["id"]}') is True


def _survey(classroom, survey_id):
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id']:
        abort(404)
    return survey


# --- The group's settings (survey page: "Two-part survey" and "Notifications" cards) ---

@bp.route('/builder/<int:survey_id>/reminders', methods=['POST'])
def save_plan(code, survey_id):
    """Autosave of the notifications and of the parts' timing (when, remote dates). Separate from
    the survey form, so it never touches arms, questions or responses (it can change after the
    survey has run). Body: {plan: {...}, parts: {"1": {when, open_date, ...}, "2": {...}}}."""
    from routes.builder import _can_edit, _locked_for
    classroom = _classroom(code)
    student = get_signed_in_student(classroom)
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or not _can_edit(classroom, student, survey_id):
        return jsonify({'ok': False, 'reason': 'forbidden'}), 403
    if _locked_for(classroom, survey):
        return jsonify({'ok': False, 'reason': 'locked'})
    data = request.get_json(silent=True) or {}
    if isinstance(data.get('plan'), dict):
        rem.save_plan(survey_id, rem.clean_plan(data['plan'], len(survey['arms'])))
    if isinstance(data.get('parts'), dict):
        rem.save_parts(survey_id, data['parts'])
    survey = get_survey(survey_id)
    return jsonify({'ok': True, 'todo': survey_incomplete(survey),
                    'problems': rem.plan_problems(survey, classroom),
                    'approval': rem.approval_state(survey)})


@bp.route('/host/survey/<int:survey_id>/reminders', methods=['POST'])
def approve(code, survey_id):
    classroom = _classroom(code)
    if not _is_host(classroom):
        abort(403)
    survey = _survey(classroom, survey_id)
    approve_it = request.form.get('action') == 'approve'
    rem.set_approval(survey, approve_it)
    flash(f'Group {survey["group_number"]}: reminders ' + ('approved.' if approve_it else 'no longer approved.'),
          'success')
    back = request.form.get('next', '')
    return redirect(back if back.startswith('/') else url_for('feedback.view_survey', code=code, survey_id=survey_id))




# --- The respondent's reminder step ---

def _respondent(classroom, survey):
    """Who is asking for the reminders: (arm_index, participant_id, preview) or None.

    ?arm=N is a preview of that arm (group members, the host, and classmates once the survey
    has gone live; nothing is logged). Otherwise a signed-in student who answered part 1 gets
    their own arm's reminders (until they've answered part 2: by then the reminders are over)."""
    student = get_signed_in_student(classroom)
    if request.args.get('arm') is not None:
        from routes.builder import _can_preview
        if not _can_preview(classroom, student, survey):
            return None
        arm = request.args.get('arm', type=int) or 0
        return min(max(arm, 0), len(survey['arms']) - 1), None, True
    if not student:
        return None
    ensure_participant_session(classroom, student)
    db = get_db()
    pid = session['participant_id']
    if not rem.answered_part(db, pid, survey, 1):
        return None
    if rem.is_two_part(survey) and rem.answered_part(db, pid, survey, 2):
        return None
    arm = rem.respondent_arm(db, survey['id'], pid)
    return (arm, pid, False) if arm is not None else None


def _items(classroom, survey, arm, preview):
    """The respondent's reminders; none until the instructor approves the plan (a preview shows them anyway)."""
    if not preview and rem.approval_state(survey) not in ('approved', 'none'):
        return []
    lobby = url_for('classroom.lobby', code=classroom['code'], _external=True)
    return rem.calendar_items(survey, arm, classroom, lobby)


def _arm_args(preview, arm):
    return {'arm': arm} if preview else {}


@bp.route('/reminders/<int:survey_id>/panel')
def panel(code, survey_id):
    classroom = _classroom(code)
    survey = _survey(classroom, survey_id)
    who = _respondent(classroom, survey)
    if not who:
        return jsonify({'ok': True, 'show': False})
    arm, participant_id, preview = who
    items = _items(classroom, survey, arm, preview)
    plan = rem.load_plan(survey)
    done, push_state = False, {'on': False, 'pending': 0}
    if participant_id:
        done = get_db().execute("SELECT 1 FROM reminder_action WHERE survey_id=? AND participant_id=? AND method='done'",
                                (survey_id, participant_id)).fetchone() is not None
        push_state = push.status_for(survey_id, participant_id)
    args = _arm_args(preview, arm)
    return jsonify({
        'ok': True, 'show': bool(items), 'preview': preview, 'approval': rem.approval_state(survey),
        'arm_label': survey['arms'][arm]['label'] if preview else None,
        'note': plan['arms'][arm]['note'] if items and arm < len(plan['arms']) else '', 'done': done,
        'items': [{'summary': i['summary'], 'when': i['when'],
                   'google_url': url_for('reminders.google', code=code, survey_id=survey_id, key=str(i['key']), **args)}
                  for i in items],
        'ics_url': url_for('reminders.calendar_file', code=code, survey_id=survey_id, **args),
        'done_url': url_for('reminders.mark_done', code=code, survey_id=survey_id, **args),
        'push_url': None if preview else url_for('reminders.push_subscribe', code=code, survey_id=survey_id),
        'push_test_url': url_for('reminders.push_test', code=code, survey_id=survey_id, arm=arm) if preview else None,
        'vapid_key': push.vapid_keys()[1],
        'push': push_state,
    })


@bp.route('/reminders/<int:survey_id>/calendar.ics')
def calendar_file(code, survey_id):
    classroom = _classroom(code)
    survey = _survey(classroom, survey_id)
    who = _respondent(classroom, survey)
    if not who:
        abort(403)
    arm, participant_id, preview = who
    items = _items(classroom, survey, arm, preview)
    if not items:
        abort(404)
    if participant_id:
        rem.log_action(survey_id, participant_id, arm, 'ics', device=request.args.get('d'))
    body = rem.ics(items, survey_id, arm, f'{classroom["name"]} reminders')
    # iPhones show "Add All" for a calendar opened in place; computers just save the file
    disposition = 'inline' if request.args.get('inline') == '1' else 'attachment'
    return Response(body, mimetype='text/calendar',
                    headers={'Content-Disposition': f'{disposition}; filename=reminders.ics'})


@bp.route('/reminders/<int:survey_id>/google/<key>')
def google(code, survey_id, key):
    classroom = _classroom(code)
    survey = _survey(classroom, survey_id)
    who = _respondent(classroom, survey)
    if not who:
        abort(403)
    arm, participant_id, preview = who
    item = next((i for i in _items(classroom, survey, arm, preview) if str(i['key']) == key), None)
    if not item:
        abort(404)
    if participant_id:
        rem.log_action(survey_id, participant_id, arm, 'google', item=key, device=request.args.get('d'))
    return redirect(rem.google_url(item))


@bp.route('/reminders/<int:survey_id>/done', methods=['POST'])
def mark_done(code, survey_id):
    classroom = _classroom(code)
    survey = _survey(classroom, survey_id)
    who = _respondent(classroom, survey)
    if not who:
        return jsonify({'ok': False}), 403
    arm, participant_id, preview = who
    if participant_id:
        rem.log_action(survey_id, participant_id, arm, 'done', device=request.args.get('d'))
    return jsonify({'ok': True})


@bp.route('/reminders/<int:survey_id>/push', methods=['POST'])
def push_subscribe(code, survey_id):
    """Turn notifications on (body: {subscription, tz}) or off ({off: true}) for this survey's reminders."""
    classroom = _classroom(code)
    survey = _survey(classroom, survey_id)
    if request.args.get('arm') is not None:
        return jsonify({'ok': False, 'reason': 'preview'}), 400
    who = _respondent(classroom, survey)
    if not who:
        return jsonify({'ok': False}), 403
    arm, participant_id, _ = who
    data = request.get_json(silent=True) or {}
    if data.get('off'):
        push.unsubscribe(survey_id, participant_id)
        rem.log_action(survey_id, participant_id, arm, 'push_off', device=request.args.get('d'))
        return jsonify({'ok': True, 'push': push.status_for(survey_id, participant_id)})
    items = _items(classroom, survey, arm, False)
    if not items:
        return jsonify({'ok': False, 'reason': 'nothing'}), 400
    push.remember_site(request.host_url)
    try:
        count = push.subscribe(survey, participant_id, arm, data.get('subscription') or {}, data.get('tz'), items)
    except ValueError:
        return jsonify({'ok': False, 'reason': 'bad_subscription'}), 400
    rem.log_action(survey_id, participant_id, arm, 'push', device=request.args.get('d'))
    return jsonify({'ok': True, 'scheduled': count, 'push': push.status_for(survey_id, participant_id)})


@bp.route('/reminders/<int:survey_id>/push-test', methods=['POST'])
def push_test(code, survey_id):
    """Preview only: send this arm's first notification to this device right away, to see how it
    looks. Nothing is scheduled or recorded."""
    classroom = _classroom(code)
    survey = _survey(classroom, survey_id)
    who = _respondent(classroom, survey)
    if not who or not who[2]:
        return jsonify({'ok': False}), 403
    arm = who[0]
    items = _items(classroom, survey, arm, True)
    if not items:
        return jsonify({'ok': False, 'reason': 'nothing'}), 400
    push.remember_site(request.host_url)
    try:
        push.send_test((request.get_json(silent=True) or {}).get('subscription') or {},
                       items[0]['summary'], items[0]['description'],
                       url_for('classroom.lobby', code=code, _external=True))
    except ValueError:
        return jsonify({'ok': False, 'reason': 'bad_subscription'}), 400
    except Exception as e:  # the push service refused it
        return jsonify({'ok': False, 'reason': 'send_failed', 'error': str(e)[:200]}), 502
    return jsonify({'ok': True})


@bp.route('/reminders/push/<int:message_id>/<token>')
def push_open(code, message_id, token):
    """A tapped notification: record it, then go to the lobby."""
    found = push.record_click(message_id, token)
    return redirect(url_for('classroom.lobby', code=found or code))


@bp.route('/reminders/<int:survey_id>')
def page(code, survey_id):
    """The reminder step on its own page (from the lobby, or a preview with ?arm=N)."""
    classroom = _classroom(code)
    survey = _survey(classroom, survey_id)
    if not _respondent(classroom, survey):
        flash('Reminders are for classmates who answered this survey.', 'danger')
        return redirect(url_for('classroom.lobby', code=code))
    preview_arm = request.args.get('arm', type=int)
    return render_template('reminders/page.html', classroom=classroom, survey=survey, preview_arm=preview_arm,
                           panel_url=url_for('reminders.panel', code=code, survey_id=survey_id,
                                             **({'arm': preview_arm} if preview_arm is not None else {})))


# --- Remote parts, answered from the lobby between their dates ---

def _remote_refusal(db, student, survey, part, pid):
    """Why this student can't answer this remote part now: (title, message), or None."""
    from models import feedback as fb
    if part == 2 and not rem.answered_part(db, pid, survey, 1):
        return ('Part 2 is for classmates who answered part 1',
                "You didn't answer part 1 of this survey, so there is nothing for you here.")
    if fb.is_own_survey(survey['id'], student['id']):
        return "This is your group's survey", "You can't answer your own survey."
    window = rem.part_window(survey, part)
    if window in ('none', 'waiting', 'upcoming'):
        opens = rem.nice_date(rem.part_dates(survey, part)[0])
        return f'Part {part} is not open yet', (f'It opens on {opens}.' if window == 'upcoming' else '')
    if window == 'closed':
        return f'Part {part} is closed', 'Its deadline has passed.'
    return None


@bp.route('/student/part/<int:survey_id>/<int:part>')
def remote_part(code, survey_id, part):
    classroom = _classroom(code)
    student = get_signed_in_student(classroom)
    if not student:
        return redirect(url_for('account.signin', code=code))
    survey = _survey(classroom, survey_id)
    if part not in rem.remote_parts(survey):
        abort(404)
    ensure_participant_session(classroom, student)
    return render_template('student/session.html', classroom=classroom, open_survey=survey, remote_part=part,
                           remote_close=rem.nice_date(rem.part_dates(survey, part)[1]),
                           participant_id=session['participant_id'], student_id=session['student_id'],
                           student_name=session['student_name'],
                           state_url=url_for('reminders.remote_part_state', code=code, survey_id=survey_id, part=part),
                           submit_url=url_for('student.submit_answer_http', code=code))


@bp.route('/student/part/<int:survey_id>/<int:part>/state')
def remote_part_state(code, survey_id, part):
    from sockets.events import _build_assignment_payload, _get_survey_with_arms_and_questions, _is_fully_answered
    classroom = _classroom(code)
    student = get_signed_in_student(classroom)
    if not student:
        return jsonify({'ok': False, 'error': 'not_logged_in'}), 401
    ensure_participant_session(classroom, student)
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or part not in rem.remote_parts(survey):
        return jsonify({'ok': False}), 404
    db = get_db()
    pid = session['participant_id']
    if _is_fully_answered(db, pid, survey_id, part=part):
        return jsonify({'ok': True, 'state': 'submitted', 'survey_id': survey_id})
    refusal = _remote_refusal(db, student, survey, part, pid)
    if refusal:
        return jsonify({'ok': True, 'state': 'closed', 'title': refusal[0], 'message': refusal[1]})
    s, arms, questions = _get_survey_with_arms_and_questions(db, survey_id)
    arm = rem.respondent_arm(db, survey_id, pid) if part == 2 else None
    payload = _build_assignment_payload(s, arms, questions, session['student_id'], part=part,
                                        arm_position=next((i for i, a in enumerate(arms) if a['arm_index'] == arm), None))
    payload['title'] += f' (part {part})'
    return jsonify({'ok': True, 'state': 'assignment', 'assignment': payload})


def parts_text(survey):
    """{1: 'in class, during the live session', 2: 'remote, from the lobby, Fri Oct 16 to Mon Oct 19'}."""
    out = {}
    for p in (1, 2):
        text = rem.WHEN_NAMES[rem.part_when(survey, p)]
        if rem.part_when(survey, p) == 'remote':
            opens, closes = rem.part_dates(survey, p)
            if opens and closes:
                text += f', {rem.nice_date(opens)} to {rem.nice_date(closes)}'
        out[p] = text
    return out


def view_data(classroom, survey):
    """The two-part split and each arm's notifications, for View survey (and the instructor's approval)."""
    if survey.get('external'):
        return None
    plan = rem.load_plan(survey)
    two_part = rem.is_two_part(survey)
    if not two_part and not rem.has_reminders(plan):
        return None
    arms = []
    for arm in survey['arms']:
        ai = arm['arm_index']
        items = [i for i in rem.calendar_items(survey, ai, classroom, '') if i['key'] != 'p2']
        arms.append({'label': arm['label'], 'note': plan['arms'][ai]['note'] if ai < len(plan['arms']) else '',
                     'events': items})
    return {'two_part': two_part, 'part2_from': rem.part2_start(survey), 'parts': parts_text(survey) if two_part else {},
            'remote_part2': 2 in rem.remote_parts(survey),
            'time': rem.nice_time(survey.get('part2_time') or rem.DEFAULT_TIME),
            'tz': rem.tz_label(plan['tz']), 'has_notifications': rem.has_reminders(plan),
            'arms': arms, 'approval': rem.approval_state(survey),
            'problems': rem.plan_problems(survey, classroom) + rem.part_problems(survey)}


def followups_for_student(classroom, student, participant_id):
    """Lobby list: remote parts this student can answer (part 2 only after part 1; never their
    own group's), and notifications for surveys they answered."""
    from sockets.events import _is_fully_answered
    from models import feedback as fb
    db = get_db()
    out = []
    for row in db.execute('SELECT id FROM survey WHERE classroom_id=? AND external=0 '
                          'AND (part2_from IS NOT NULL OR reminder_plan IS NOT NULL) ORDER BY group_number',
                          (classroom['id'],)):
        survey = get_survey(row['id'])
        own = fb.is_own_survey(survey['id'], student['id'])
        answered1 = participant_id is not None and rem.answered_part(db, participant_id, survey, 1)
        entry = {'id': survey['id'], 'group_number': survey['group_number'], 'title': survey['title'],
                 'parts': [], 'reminders': 0}
        for p in rem.remote_parts(survey):
            window = rem.part_window(survey, p)
            if own or window in ('none', 'waiting') or (p == 2 and not answered1):
                continue
            opens, closes = rem.part_dates(survey, p)
            entry['parts'].append({'part': p, 'window': window, 'opens': rem.nice_date(opens),
                                   'closes': rem.nice_date(closes),
                                   'done': participant_id is not None and _is_fully_answered(db, participant_id, survey['id'], part=p)})
        if answered1 and not (rem.is_two_part(survey) and rem.answered_part(db, participant_id, survey, 2)) \
                and rem.approval_state(survey) in ('approved', 'none'):
            arm = rem.respondent_arm(db, survey['id'], participant_id)
            entry['reminders'] = len(rem.calendar_items(survey, arm, classroom, ''))
        if entry['parts'] or entry['reminders']:
            out.append(entry)
    return out
