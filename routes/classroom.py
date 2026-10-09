
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from models.classroom import (
    create_classroom, get_classroom_by_code, check_host_password, check_classroom_password, parse_max_groups,
)
from models import roster as roster_model
from models.survey import list_surveys, get_survey, survey_warnings, respondent_count, survey_incomplete

bp = Blueprint('classroom', __name__, url_prefix='/c')


@bp.route('/create', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        name = request.form.get('name', '').strip()
        host_password = request.form.get('host_password', '').strip()
        host_password_confirm = request.form.get('host_password_confirm', '').strip()
        classroom_password = request.form.get('classroom_password', '').strip()
        classroom_password_confirm = request.form.get('classroom_password_confirm', '').strip()
        max_groups, max_groups_error = parse_max_groups(request.form.get('max_groups', ''))

        errors = []
        if not code:
            errors.append('Classroom code is required.')
        if not name:
            errors.append('Classroom name is required.')
        if not host_password:
            errors.append('Host password is required.')
        elif host_password != host_password_confirm:
            errors.append('Host passwords do not match.')
        if not classroom_password:
            errors.append('Classroom password is required.')
        elif classroom_password != classroom_password_confirm:
            errors.append('Classroom passwords do not match.')
        if max_groups_error:
            errors.append(max_groups_error)

        form_values = dict(code=code, name=name, max_groups=request.form.get('max_groups', ''))
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('classroom/create.html', **form_values)

        if get_classroom_by_code(code):
            flash(f'The code {code} is already used by another classroom (codes ignore upper/lower case). '
                  'Choose a different code; the name can be anything.', 'danger')
            return render_template('classroom/create.html', **form_values)
        classroom = create_classroom(code, name, host_password, classroom_password, max_groups)

        # The creator is the host
        session[f'host_authenticated_{classroom["id"]}'] = True
        session[f'classroom_joined_{classroom["id"]}'] = True
        flash(f'Classroom "{name}" created with code {classroom["code"]}!', 'success')

        roster_file = request.files.get('roster_file')
        if roster_file and roster_file.filename:
            from routes.roster import import_or_preview
            csv_text = roster_model.decode_csv_bytes(roster_file.read())
            return import_or_preview(classroom, csv_text)
        flash('Next step: upload your class roster so students can sign in.', 'info')
        return redirect(url_for('roster.index', code=classroom['code']))

    return render_template('classroom/create.html', code='', name='', max_groups='1')


@bp.route('/join', methods=['GET', 'POST'])
def join():
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        password = request.form.get('password', '').strip()
        classroom = get_classroom_by_code(code)
        if not classroom:
            flash('Classroom not found. Check the code and try again.', 'danger')
            return render_template('classroom/join.html', prefill_code=code)

        if not check_classroom_password(classroom['id'], password):
            flash('Incorrect classroom password.', 'danger')
            return render_template('classroom/join.html', prefill_code=code)

        session['classroom_id'] = classroom['id']
        session['classroom_code'] = classroom['code']
        session['classroom_name'] = classroom['name']
        session[f'classroom_joined_{classroom["id"]}'] = True
        return redirect(url_for('classroom.lobby', code=classroom['code']))

    prefill_code = request.args.get('code', '')
    prefill_password = request.args.get('password', '')
    return render_template('classroom/join.html', prefill_code=prefill_code, prefill_password=prefill_password)


@bp.route('/<code>/lobby')
def lobby(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        flash('Classroom not found.', 'danger')
        return redirect(url_for('main.index'))

    # Allow access if student joined via password or host is authenticated
    if not session.get(f'classroom_joined_{classroom["id"]}') and \
       not session.get(f'host_authenticated_{classroom["id"]}'):
        flash('Please join the classroom first.', 'danger')
        return redirect(url_for('classroom.join', code=code))

    from routes.account import get_signed_in_student, ensure_participant_session, tour_seen
    student = get_signed_in_student(classroom)
    if not student:
        return redirect(url_for('account.signin', code=code))
    ensure_participant_session(classroom, student)

    from models import feedback as fb
    groups = roster_model.my_groups(classroom['id'], student['id'])
    for g in groups:
        full = get_survey(g['id'])
        g['warnings'] = survey_warnings(full)
        g['todo'] = survey_incomplete(full)
        g['responses'] = respondent_count(g['id'])
        g['received'] = fb.received_feedback(g['id']) if classroom['feedback_released'] else []
    at_limit = roster_model.at_group_limit(classroom, student['id'])

    # Assigned groups appear once surveys are locked (before that, only comments the student
    # started on surveys that ran early). Each survey takes comments once it has gone live.
    # Students added after reviewers were assigned get their groups on first visit.
    started = fb.feedback_started(classroom)
    cards = fb.student_feedback(classroom, student['id'])
    if started and sum(1 for c in cards if c['assignment_id']) < (classroom['reviews_required'] or 0) \
            and fb.assignments_exist(classroom['id']):
        fb.ensure_assignments(classroom, only_student_id=student['id'])
        cards = fb.student_feedback(classroom, student['id'])
    if not started:
        cards = [c for c in cards if c['feedback_id']]
    live_ids = fb.commentable_ids(classroom)
    for c in cards:
        c['open'] = c['survey_id'] in live_ids
    carded = {c['survey_id'] for c in cards}
    can_add = [s for s in fb.commentable_surveys(classroom['id'], student['id'])
               if s['id'] not in carded and s['id'] in live_ids]

    surveys = list_surveys(classroom['id'])
    from routes.reminders import followups_for_student
    # Group finder: shown to students without a group, or whose group still has room
    open_group = next((g for g in groups if not (classroom['max_group_size'] and g['member_count'] >= classroom['max_group_size'])), None)
    show_finder = not classroom['surveys_locked'] and (not groups or open_group is not None)
    return render_template('classroom/lobby.html', classroom=classroom, student=student,
                           show_finder=show_finder, open_group=open_group,
                           finder=roster_model.group_finder(classroom['id'], exclude_id=student['id']) if show_finder else [],
                           followups=followups_for_student(classroom, student, session.get('participant_id')),
                           groups=groups, at_limit=at_limit,
                           invites=roster_model.pending_invites_for_student(student['id']),
                           live=any(s['is_active'] for s in surveys),
                           survey_order=surveys,
                           tour_auto=not tour_seen(student, 'lobby'),
                           open_surveys=fb.open_surveys_for_student(classroom, student['id'],
                                                                    session.get('participant_id')),
                           feedback_started=started,
                           feedback_cards=cards, can_add_feedback=can_add,
                           required_sent=sum(1 for c in cards if c['required'] and c['sent_at']),
                           required_total=sum(1 for c in cards if c['required']))


@bp.route('/host-join', methods=['GET', 'POST'])
def host_join():
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        password = request.form.get('password', '').strip()
        classroom = get_classroom_by_code(code)
        if not classroom:
            flash('Classroom not found. Check the code and try again.', 'danger')
            return render_template('classroom/host_join.html')
        if not check_host_password(classroom['id'], password):
            flash('Incorrect host password.', 'danger')
            return render_template('classroom/host_join.html')

        session[f'host_authenticated_{classroom["id"]}'] = True
        session['classroom_id'] = classroom['id']
        session['classroom_code'] = classroom['code']
        session['classroom_name'] = classroom['name']
        return redirect(url_for('host.home', code=classroom['code']))

    return render_template('classroom/host_join.html')
