import os
import random
import time
import uuid

from flask import (
    Blueprint, Response, render_template, request, redirect, url_for, flash, session, abort, current_app, jsonify,
)
from werkzeug.utils import secure_filename

from models.classroom import get_classroom_by_code
from models.db import get_db
from models.flow import survey_flows
from models.preview import fake_responses
from models.survey import (
    create_survey, get_survey, list_surveys, update_survey, delete_survey, next_group_number,
    survey_warnings, respondent_count, missing_parts, survey_incomplete, with_todo,
)
from models import roster as roster_model
from models import rules
from routes.account import get_signed_in_student, tour_seen
from models.download import (
    export_survey_responses_csv, export_survey_responses_anon_csv, anon_responses_csv, export_single_survey_config_csv,
    export_single_survey_designers_csv, export_single_survey_participation_csv,
)

bp = Blueprint('builder', __name__, url_prefix='/c/<code>/builder')

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg'}


def _require_classroom_access(classroom, code):
    """Hosts pass; students must have joined the classroom and signed in with the roster.

    Returns (student_or_None, redirect_or_None).
    """
    if _is_classroom_host(classroom['id']):
        return get_signed_in_student(classroom), None
    if not session.get(f'classroom_joined_{classroom["id"]}'):
        flash('Please join the classroom first.', 'danger')
        return None, redirect(url_for('classroom.join', code=code))
    student = get_signed_in_student(classroom)
    if not student:
        return None, redirect(url_for('account.signin', code=code))
    return student, None


def _can_edit(classroom, student, survey_id):
    """Hosts can edit any survey; students only their own group's."""
    return _is_classroom_host(classroom['id']) or \
        (student is not None and roster_model.is_member(survey_id, student['id']))


def _get_classroom_or_404(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


def _is_classroom_host(classroom_id):
    """Check if the current session user is authenticated as host for this classroom."""
    return session.get(f'host_authenticated_{classroom_id}') is True


def _save_upload(file_obj):
    """Save an uploaded file. Returns the stored filename, or None if invalid/empty."""
    if not file_obj or not file_obj.filename:
        return None
    ext = os.path.splitext(file_obj.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None
    safe_name = secure_filename(file_obj.filename)
    unique_name = f'{uuid.uuid4().hex}_{safe_name}'
    file_obj.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_name))
    return unique_name


def _delete_upload(filename):
    """Delete an uploaded file from disk (best-effort)."""
    if not filename:
        return
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    try:
        os.remove(path)
    except OSError:
        pass


def _parse_form(form, files=None):
    """Parse the builder form data into structured dicts for multi-question surveys."""
    title = form.get('title', '').strip()
    group_number = form.get('group_number', '').strip()

    # Parse arms (just labels now)
    arms = []
    arm_idx = 0
    while f'arms[{arm_idx}][label]' in form:
        arms.append({
            'label': form.get(f'arms[{arm_idx}][label]', '').strip(),
        })
        arm_idx += 1

    # Parse questions
    questions = []
    q_idx = 0
    while f'questions[{q_idx}][question_type]' in form:
        q_type = form.get(f'questions[{q_idx}][question_type]', 'multiple_choice')
        question = {
            'question_type': q_type,
            'label': form.get(f'questions[{q_idx}][label]', '').strip(),
            'arms': {},
            **rules.parse_rules(form, q_idx, len(arms)),
        }
        if q_type == 'slider':
            try:
                question['slider_min'] = float(form.get(f'questions[{q_idx}][slider_min]', '0'))
            except (ValueError, TypeError):
                question['slider_min'] = 0
            try:
                question['slider_max'] = float(form.get(f'questions[{q_idx}][slider_max]', '100'))
            except (ValueError, TypeError):
                question['slider_max'] = 100
            try:
                question['slider_step'] = float(form.get(f'questions[{q_idx}][slider_step]', '1'))
            except (ValueError, TypeError):
                question['slider_step'] = 1
        for ai in range(len(arms)):
            q_text = form.get(f'questions[{q_idx}][arms][{ai}][question_text]', '').strip()
            options = []
            if question['question_type'] in ('multiple_choice', 'multiple_answer'):
                opt_idx = 0
                while f'questions[{q_idx}][arms][{ai}][options][{opt_idx}]' in form:
                    opt = form.get(f'questions[{q_idx}][arms][{ai}][options][{opt_idx}]', '').strip()
                    if opt:
                        options.append(opt)
                    opt_idx += 1

            # Handle image upload
            image_filename = None
            if files:
                file_key = f'questions[{q_idx}][arms][{ai}][image]'
                file_obj = files.get(file_key)
                saved = _save_upload(file_obj)
                if saved:
                    image_filename = saved

            # If no new upload, keep existing image
            if not image_filename:
                existing = form.get(f'questions[{q_idx}][arms][{ai}][existing_image]', '').strip()
                if existing:
                    image_filename = existing

            question['arms'][ai] = {
                'question_text': q_text,
                'options': options,
                'image_filename': image_filename,
                'allow_other': form.get(f'questions[{q_idx}][arms][{ai}][allow_other]') == '1',
                **_parse_timer(form, f'questions[{q_idx}][arms][{ai}]'),
            }
        questions.append(question)
        q_idx += 1

    return title, group_number, arms, questions


TIMER_DISPLAYS = ('both', 'countdown', 'bar', 'hidden')
MAX_TIMER_SECONDS = 600


def _parse_timer(form, prefix):
    """An arm-question's timer fields. timer_seconds is None when there's no timer;
    timer_seconds_raw keeps what was typed so a bad value can be shown back."""
    raw = form.get(f'{prefix}[timer_seconds]', '').strip()
    display = form.get(f'{prefix}[timer_display]', 'both')
    seconds = int(raw) if raw.isdigit() else None
    return {
        'timer_seconds': seconds if form.get(f'{prefix}[timer_on]') == '1' else None,
        'timer_seconds_raw': raw if form.get(f'{prefix}[timer_on]') == '1' else '',
        'timer_display': display if display in TIMER_DISPLAYS else 'both',
        'timer_default': form.get(f'{prefix}[timer_default]', '').strip()[:140],
    }


def _parse_external(form):
    """The "we're running our survey on another platform" box: (external, note)."""
    return form.get('external') == '1', form.get('external_note', '').strip()[:1000] or None


def _validate_external(title, group_number):
    """A survey sent from another platform needs nothing else; arms and questions are optional."""
    errors = []
    if group_number and not str(group_number).isdigit():
        errors.append('Group number must be a valid number.')
    return errors


def _save_external(survey_id, external, note):
    db = get_db()
    db.execute('UPDATE survey SET external=?, external_note=? WHERE id=?', (1 if external else 0, note, survey_id))
    if external:
        # The group sends it out itself, so it can't open early here
        db.execute('UPDATE survey SET early_open=0 WHERE id=?', (survey_id,))
    db.commit()


def _question_limit_errors(classroom, questions):
    """The instructor's cap on questions per survey (students only; the host is exempt)."""
    limit = classroom.get('max_questions_per_survey')
    if limit and len(questions) > limit and not _is_classroom_host(classroom['id']):
        extra = len(questions) - limit
        return [f'Your instructor limits surveys to {limit} question{"s" if limit != 1 else ""}. '
                f'Remove {extra} question{"s" if extra != 1 else ""} to save.']
    return []


def _fill_defaults(title, arms, group_number):
    """Unfinished surveys save too: a blank title or arm name gets a placeholder."""
    for i, arm in enumerate(arms):
        if not arm['label']:
            arm['label'] = f'Arm {i + 1}'
    return title or f'Group {group_number} survey'


def _validate(title, group_number, arms, questions):
    """Mistakes that block saving. Missing pieces (question text, options) don't block:
    the survey saves as unfinished and they're listed by missing_parts()."""
    errors = []
    if group_number and not str(group_number).isdigit():
        errors.append('Group number must be a valid number.')
    if len(arms) < 1:
        errors.append('At least 1 arm is required.')
    for qi, q in enumerate(questions):
        for ai, arm in enumerate(arms):
            data = q.get('arms', {}).get(ai, {})
            raw = data.get('timer_seconds_raw', '')
            if raw and not (raw.isdigit() and 1 <= int(raw) <= MAX_TIMER_SECONDS):
                errors.append(f'Question {qi+1}, {arm["label"] or f"Arm {ai+1}"}: the timer must be a whole number '
                              f'of seconds between 1 and {MAX_TIMER_SECONDS}.')
        if q['question_type'] == 'slider':
            s_min = q.get('slider_min', 0)
            s_max = q.get('slider_max', 100)
            s_step = q.get('slider_step', 1)
            if s_min >= s_max:
                errors.append(f'Question {qi+1}: Slider min must be less than max.')
            if s_step <= 0:
                errors.append(f'Question {qi+1}: Slider step must be greater than 0.')
    return errors


@bp.route('/')
def index(code):
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return denied
    # Students see their own groups in the lobby; only the host sees the full list
    if not _is_classroom_host(classroom['id']):
        return redirect(url_for('classroom.lobby', code=code))
    surveys = with_todo(list_surveys(classroom['id']))
    from models import reminders
    for s in surveys:
        # How each part runs, and whether it already ran (for the Launch / Run again buttons)
        s['runs'] = [{'part': p, 'when': reminders.part_when(s, p), 'ran': reminders.part_ran(s, p)}
                     for p in ((1, 2) if reminders.is_two_part(s) else (1,))]
        if s['reminder_plan'] or s['part2_from'] is not None:
            full = get_survey(s['id'])
            s['two_part'] = reminders.is_two_part(full)
            s['reminder_approval'] = reminders.approval_state(full)
    return render_template('builder/list.html', surveys=surveys, is_host=True, classroom=classroom)



def _locked_for(classroom, survey=None):
    """Students can't change surveys once the host locks editing, nor a survey their
    group submitted for early answering (until the host unlocks it). Hosts always can."""
    if _is_classroom_host(classroom['id']):
        return False
    return bool(classroom.get('surveys_locked')) or bool(survey and survey.get('early_open'))


def _cleanup_orphan_uploads(max_age_hours=24):
    """Delete uploaded images no survey uses any more.

    Images replaced while editing are kept for a day so "Discard changes from this
    session" can bring them back; after that they're removed.
    """
    folder = current_app.config['UPLOAD_FOLDER']
    used = {r[0] for r in get_db().execute(
        'SELECT image_filename FROM arm_question WHERE image_filename IS NOT NULL')}
    cutoff = time.time() - max_age_hours * 3600
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        path = os.path.join(folder, name)
        try:
            if name not in used and os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def _load_survey(classroom, code, survey_id, student):
    """Return (survey, None) if the user may work on this survey, else (None, redirect)."""
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id']:
        flash('Survey not found.', 'danger')
        return None, redirect(url_for('classroom.lobby', code=code))
    if not _can_edit(classroom, student, survey_id):
        flash('Only members of this group can open this survey.', 'danger')
        return None, redirect(url_for('classroom.lobby', code=code))
    return survey, None


def _render_form(classroom, mode, student, **ctx):
    survey_id = ctx.get('survey_id')
    exclude = student['id'] if student else None
    survey = get_survey(survey_id) if survey_id else None
    # First-visit tour of the survey page, for students on an editable page only. Students
    # who saw the full tour on the old create page get just the edit-page extras.
    tour_auto = tour_short = False
    if student and not _is_classroom_host(classroom['id']) and not _locked_for(classroom, survey)             and mode == 'edit' and not tour_seen(student, 'builder_edit'):
        tour_auto = True
        tour_short = tour_seen(student, 'builder')
    ctx.setdefault('tour_auto', tour_auto)
    ctx.setdefault('tour_short', tour_short)
    return render_template(
        'builder/form.html', mode=mode, classroom=classroom,
        is_host=_is_classroom_host(classroom['id']), student=student,
        locked=_locked_for(classroom, survey),
        groups_locked=_locked_for(classroom),
        survey=survey,
        classmates=roster_model.classmates(classroom['id'], exclude_id=exclude),
        members=survey['members'] if survey else [],
        pending_invites=roster_model.pending_invites_for_survey(survey_id) if survey_id else [],
        join_requests=roster_model.join_requests_for_survey(survey_id) if survey_id else [],
        warnings=survey_warnings(survey) if survey else [],
        todo=survey_incomplete(survey) if survey else [],
        response_count=respondent_count(survey_id) if survey_id else 0,
        reminders_state=_reminders_state(classroom, survey) if survey else None,
        **{'external': bool(survey and survey['external']),
           'external_note': survey['external_note'] if survey else None, **ctx})


def _reminders_state(classroom, survey):
    """What the "Two-part survey" timing and the "Notifications" card start from (reminders-builder.js)."""
    from datetime import date
    from models import reminders
    plan = reminders.load_plan(survey)
    return {'plan': plan,
            'parts': {str(p): {'when': survey.get(f'part{p}_when') or ('live' if p == 1 else 'remote'),
                               'open_date': survey.get(f'part{p}_open_date') or '',
                               'close_date': survey.get(f'part{p}_close_date') or ''} for p in (1, 2)},
            'part2_time': survey.get('part2_time') or reminders.DEFAULT_TIME,
            'approval': reminders.approval_state(survey),
            'problems': reminders.plan_problems(survey, classroom),
            'has_notifications': reminders.has_reminders(plan),
            'today': date.today().isoformat(),
            'limit_text': reminders.nice_date(reminders._date(classroom.get('reminders_until'))),
            'max_rules': reminders.MAX_RULES_PER_ARM}


def _form_values_from_survey(survey):
    """Convert a stored survey into the arms/questions structure the form template uses."""
    arms = [{'label': a['label']} for a in survey['arms']]
    questions = []
    for q in survey.get('questions', []):
        question = {
            'question_type': q['question_type'],
            'label': q.get('label', ''),
            'arms': {},
            'show_arms': q.get('show_arms'),
            'cond_question': q.get('cond_question'),
            'cond_values': q.get('cond_values') or [],
        }
        if q['question_type'] == 'slider':
            question['slider_min'] = q.get('slider_min', 0)
            question['slider_max'] = q.get('slider_max', 100)
            question['slider_step'] = q.get('slider_step', 1)
        for ai in range(len(arms)):
            arm_data = q.get('arms', {}).get(ai, {})
            options = arm_data.get('options', [])
            if not options and q['question_type'] in ('multiple_choice', 'multiple_answer'):
                options = ['', '']
            question['arms'][ai] = {
                'question_text': arm_data.get('question_text', ''),
                'options': options,
                'image_filename': arm_data.get('image_filename'),
                'allow_other': arm_data.get('allow_other', False),
                'timer_seconds': arm_data.get('timer_seconds'),
                'timer_display': arm_data.get('timer_display') or 'both',
                'timer_default': arm_data.get('timer_default') or '',
            }
        questions.append(question)
    return arms, questions


@bp.route('/new', methods=['GET', 'POST'])
def new(code):
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return denied
    is_host = _is_classroom_host(classroom['id'])

    if _locked_for(classroom):
        flash('Survey editing is locked by your instructor.', 'danger')
        return redirect(url_for('classroom.lobby', code=code))
    if student and not is_host and roster_model.at_group_limit(classroom, student['id']):
        flash("You're already in the maximum number of groups, so you can't create a new survey. "
              "Leave a group first.", 'danger')
        return redirect(url_for('classroom.lobby', code=code))

    # Creating a group only needs a name and teammates: the survey itself is built
    # afterwards on its page, saving as it goes, even unfinished.
    if request.method == 'POST':
        invite_ids = [int(i) for i in request.form.getlist('invite_ids') if i.isdigit()]
        title = request.form.get('title', '').strip()[:200]
        group_number = request.form.get('group_number', '').strip()
        if is_host and group_number and not group_number.isdigit():
            flash('Group number must be a valid number.', 'danger')
            return redirect(url_for('builder.new', code=code))

        members = []
        if student and not is_host:
            members.append({'name': student['full_name'], 'sis_code': student['sis_id'],
                            'roster_student_id': student['id']})
        number = int(group_number) if (is_host and group_number) else next_group_number(classroom['id'])
        arms, questions = blank_design()
        try:
            survey_id = create_survey(classroom['id'], title or f'Group {number} survey', number,
                                      arms, questions, members)
        except Exception as e:
            flash(f'Error creating your group: {e}', 'danger')
            return redirect(url_for('builder.new', code=code))

        if student and not is_host:
            roster_model.after_join(classroom, survey_id, student['id'])  # their requests to join other groups are void
        sent = 0
        for invitee_id in invite_ids:
            if not roster_model.invite(classroom['id'], survey_id, student['id'] if student else None, invitee_id):
                sent += 1
        msg = f'Group {number} created!'
        if sent:
            msg += f' {sent} invite{"s" if sent != 1 else ""} sent; teammates accept from their lobby.'
        msg += ' Build your survey below; it saves automatically, even unfinished.'
        flash(msg, 'success')
        return redirect(url_for('builder.edit', code=code, survey_id=survey_id))

    exclude = student['id'] if student else None
    return render_template('builder/new_group.html', classroom=classroom, is_host=is_host,
                           classmates=roster_model.classmates(classroom['id'], exclude_id=exclude))


def _save_edit(classroom, survey):
    """Validate the posted form and update the survey.

    Returns (errors, saved_questions, todo). Only real mistakes (errors) block saving;
    an unfinished survey saves and `todo` lists what it still needs. Images are only
    stored once the form saves, so repeated autosaves of a blocked form don't pile up files.
    """
    is_host = _is_classroom_host(classroom['id'])
    title, group_number, arms, questions = _parse_form(request.form)
    if not is_host or not group_number:
        group_number = str(survey['group_number'])
    external, ext_note = _parse_external(request.form)
    if external:
        # Arms and questions stay as they were (unchecking the box brings them back)
        errors = _validate_external(title, group_number)
        if errors:
            return errors, None, []
        db = get_db()
        db.execute('UPDATE survey SET title=?, group_number=? WHERE id=?',
                   (title or f'Group {group_number} survey', int(group_number), survey['id']))
        db.commit()
        _save_external(survey['id'], True, ext_note)
        return [], [], []
    errors = _validate(title, group_number, arms, questions) + _question_limit_errors(classroom, questions)
    if errors:
        return errors, None, []
    title, _, arms, questions = _parse_form(request.form, request.files)
    title = _fill_defaults(title, arms, group_number)
    update_survey(survey['id'], title, int(group_number), arms, questions)
    _save_external(survey['id'], False, ext_note)
    _save_part2_from(survey['id'], request.form)
    _cleanup_orphan_uploads()
    return [], questions, survey_incomplete(get_survey(survey['id']))


def _save_part2_from(survey_id, form):
    """Two-part survey: the index of the question part 2 starts at ('' = one part)."""
    raw = form.get('part2_from', '').strip()
    db = get_db()
    db.execute('UPDATE survey SET part2_from=? WHERE id=?', (int(raw) if raw.isdigit() else None, survey_id))
    db.commit()


@bp.route('/<int:survey_id>/edit', methods=['GET', 'POST'])
def edit(code, survey_id):
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return denied
    survey, denied = _load_survey(classroom, code, survey_id, student)
    if denied:
        return denied

    if request.method == 'POST':
        if _locked_for(classroom, survey):
            flash('This survey is locked. Ask your instructor if you need to change it.', 'danger')
            return redirect(url_for('builder.edit', code=code, survey_id=survey_id))
        try:
            errors, _, _ = _save_edit(classroom, survey)
        except Exception as e:
            errors = [f'Error updating survey: {e}']
        if errors:
            for e in errors:
                flash(e, 'danger')
            title, group_number, arms, questions = _parse_form(request.form)
            external, ext_note = _parse_external(request.form)
            return _render_form(classroom, 'edit', student, survey_id=survey_id, title=title,
                                group_number=group_number or survey['group_number'],
                                arms=arms, questions=questions, external=external, external_note=ext_note)
        flash('Survey saved!', 'success')
        return redirect(url_for('builder.edit', code=code, survey_id=survey_id))

    arms, questions = _form_values_from_survey(survey)
    return _render_form(classroom, 'edit', student, survey_id=survey_id, title=survey['title'],
                        group_number=survey['group_number'], arms=arms, questions=questions)


@bp.route('/<int:survey_id>/autosave', methods=['POST'])
def autosave(code, survey_id):
    """Save the edit form in the background. Returns JSON for builder.js."""
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return jsonify({'ok': False, 'reason': 'signed_out'}), 401
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or not _can_edit(classroom, student, survey_id):
        return jsonify({'ok': False, 'reason': 'forbidden'}), 403
    if _locked_for(classroom, survey):
        return jsonify({'ok': False, 'reason': 'locked'})
    if respondent_count(survey_id) and request.form.get('external') != '1':
        # Saving recreates arms/questions, which deletes collected responses: never do that silently
        return jsonify({'ok': False, 'reason': 'has_responses'})

    try:
        errors, questions, todo = _save_edit(classroom, survey)
    except Exception as e:
        return jsonify({'ok': False, 'reason': 'error', 'errors': [str(e)]})
    if errors:
        return jsonify({'ok': False, 'reason': 'invalid', 'errors': errors})

    images = {f'{qi}_{ai}': data.get('image_filename')
              for qi, q in enumerate(questions) for ai, data in q['arms'].items()}
    return jsonify({'ok': True, 'saved_at': time.strftime('%H:%M:%S'), 'images': images, 'todo': todo,
                    'warnings': survey_warnings(get_survey(survey_id))})


def blank_design():
    """The design a new group starts from: Control and Treatment, one empty multiple-choice question."""
    arms = [{'label': 'Control'}, {'label': 'Treatment'}]
    questions = [{'question_type': 'multiple_choice', 'label': '',
                  'arms': {0: {'question_text': '', 'options': []}, 1: {'question_text': '', 'options': []}}}]
    return arms, questions


@bp.route('/<int:survey_id>/start-over', methods=['POST'])
def start_over(code, survey_id):
    """Wipe the design (arms, questions, images) back to the blank starting point.
    The title, group and members stay. Refused once the survey has responses."""
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return denied
    survey, denied = _load_survey(classroom, code, survey_id, student)
    if denied:
        return denied
    if _locked_for(classroom, survey):
        flash('This survey is locked. Ask your instructor if you need to change it.', 'danger')
    elif respondent_count(survey_id):
        flash('This survey already has responses, so it can\'t be cleared. Ask your instructor.', 'danger')
    else:
        arms, questions = blank_design()
        update_survey(survey_id, survey['title'], survey['group_number'], arms, questions)
        db = get_db()
        db.execute('UPDATE survey SET part2_from=NULL WHERE id=?', (survey_id,))  # one question left: one part
        db.commit()
        _cleanup_orphan_uploads()
        flash('Survey cleared. Start your design again below. (Changed your mind? "Discard all changes from '
              'this session" brings the old version back, in the same browser tab.)', 'success')
    return redirect(url_for('builder.edit', code=code, survey_id=survey_id))


@bp.route('/<int:survey_id>/delete', methods=['POST'])
def delete(code, survey_id):
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return denied
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or not _can_edit(classroom, student, survey_id):
        abort(403)
    if _locked_for(classroom, survey):
        flash('This survey is locked. Ask your instructor if you need to change it.', 'danger')
        return redirect(url_for('classroom.lobby', code=code))

    try:
        removed_files = delete_survey(survey_id)
        for fn in removed_files:
            _delete_upload(fn)
        flash('Survey deleted.', 'success')
    except Exception as e:
        flash(f'Error deleting survey: {e}', 'danger')
    if _is_classroom_host(classroom['id']):
        return redirect(url_for('builder.index', code=code))
    return redirect(url_for('classroom.lobby', code=code))


# --- Previews (nothing here is written to the database) ---

def _can_preview(classroom, student, survey):
    """Group members and the host always; classmates once the survey has gone live
    (so nobody sees the arms before answering), so they can write feedback."""
    from models.feedback import survey_commentable
    return _can_edit(classroom, student, survey['id']) or (
        student is not None and survey_commentable(classroom, survey))


def _survey_parts(survey_id):
    from sockets.events import _get_survey_with_arms_and_questions
    return _get_survey_with_arms_and_questions(get_db(), survey_id)


@bp.route('/<int:survey_id>/preview')
def preview_survey(code, survey_id):
    """The respondent's screen for one arm, using the real student page."""
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return denied
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or not _can_preview(classroom, student, survey):
        flash('You can look at other groups\' surveys once they are deployed.', 'danger')
        return redirect(url_for('classroom.lobby', code=code))
    arm = min(max(request.args.get('arm', 0, type=int), 0), len(survey['arms']) - 1)
    from models import reminders
    part = 2 if request.args.get('part') == '2' and reminders.is_two_part(survey) else 1
    from routes.reminders import parts_text
    return render_template('student/session.html', classroom=classroom, preview=True,
                           survey=survey, preview_arm=arm, preview_part=part,
                           two_part=reminders.is_two_part(survey), part_texts=parts_text(survey),
                           participant_id=0, student_id='preview',
                           student_name=student['full_name'] if student else 'Instructor',
                           state_url=url_for('builder.preview_state', code=code, survey_id=survey_id, arm=arm, part=part),
                           submit_url=url_for('builder.preview_submit', code=code, survey_id=survey_id))


@bp.route('/<int:survey_id>/preview/state')
def preview_state(code, survey_id):
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return jsonify({'ok': False}), 403
    from sockets.events import _build_assignment_payload
    parts = _survey_parts(survey_id)
    if not parts or parts[0]['classroom_id'] != classroom['id']:
        return jsonify({'ok': False}), 404
    if not _can_preview(classroom, student, parts[0]):
        return jsonify({'ok': False}), 403
    survey, arms, questions = parts
    arm = min(max(request.args.get('arm', 0, type=int), 0), len(arms) - 1)
    payload = _build_assignment_payload(survey, arms, questions, 'preview', arm_position=arm,
                                        part=2 if request.args.get('part') == '2' else 1)
    if payload['part'] == 2:
        payload['title'] += ' (part 2)'
    return jsonify({'ok': True, 'state': 'assignment', 'assignment': payload})


@bp.route('/<int:survey_id>/preview/submit', methods=['POST'])
def preview_submit(code, survey_id):
    """Pretend to save: previews never store answers."""
    return jsonify({'ok': True, 'status': 'preview'})


@bp.route('/<int:survey_id>/preview-dashboard')
def preview_dashboard(code, survey_id):
    """The host dashboard's charts for this survey, filled with random sample responses."""
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return denied
    survey, denied = _load_survey(classroom, code, survey_id, student)
    if denied:
        return denied
    return render_template('builder/preview_dashboard.html', **preview_dashboard_context(classroom, survey))


def preview_dashboard_context(classroom, survey):
    """Template values for the dashboard preview (also the instructor's demo dashboard)."""
    code, survey_id = classroom['code'], survey['id']
    n = min(max(request.args.get('n', 30, type=int), 1), 500)
    # One seed per sample, so the charts and the example download show the same made-up answers
    seed = request.args.get('seed', type=int) or random.randint(1, 10**9)
    return dict(classroom=classroom, survey=survey, n=n, seed=seed,
                state_url=url_for('builder.preview_dashboard_state', code=code, survey_id=survey_id, n=n, seed=seed),
                example_url=url_for('builder.preview_example_csv', code=code, survey_id=survey_id, n=n, seed=seed),
                example_long_url=url_for('builder.preview_example_csv', code=code, survey_id=survey_id, n=n, seed=seed,
                                         format='long'))


@bp.route('/<int:survey_id>/preview-dashboard/state')
def preview_dashboard_state(code, survey_id):
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied or not _can_edit(classroom, student, survey_id):
        return jsonify({'ok': False}), 403
    from sockets.events import _aggregate_responses
    parts = _survey_parts(survey_id)
    if not parts or parts[0]['classroom_id'] != classroom['id']:
        return jsonify({'ok': False}), 404
    survey, arms, questions = parts
    n = min(max(request.args.get('n', 30, type=int), 1), 500)
    seed = request.args.get('seed', type=int)
    results = _aggregate_responses(survey, arms, questions, fake_responses(arms, questions, n, seed=seed))
    results['participant_count'] = n
    return jsonify({'ok': True, 'active_survey_id': survey_id, 'participant_count': n, 'results': results})


@bp.route('/<int:survey_id>/flow')
def flow_chart(code, survey_id):
    """The survey drawn as a flow chart, one column per arm (who sees which questions, in what
    order, with follow-ups and timers). Same access as the respondent preview."""
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return denied
    survey = get_survey(survey_id)
    if not survey or survey['classroom_id'] != classroom['id'] or not _can_preview(classroom, student, survey):
        flash("You can look at other groups' surveys once they are deployed.", 'danger')
        return redirect(url_for('classroom.lobby', code=code))
    if _can_edit(classroom, student, survey_id):
        base, back = url_for('builder.edit', code=code, survey_id=survey_id), 'edit'
    else:
        base, back = url_for('feedback.view_survey', code=code, survey_id=survey_id), 'view'
    flows = survey_flows(survey, link=lambda qi: f'{base}#q-{qi + 1}')
    return render_template('builder/flow.html', classroom=classroom, survey=survey, flows=flows,
                           back_url=base, back=back)


@bp.route('/<int:survey_id>/preview-dashboard/example.csv')
def preview_example_csv(code, survey_id):
    """The dashboard preview's made-up answers in the exact format of the real anonymized
    download, so groups can prepare their analysis before class."""
    classroom = _get_classroom_or_404(code)
    student, denied = _require_classroom_access(classroom, code)
    if denied or not _can_edit(classroom, student, survey_id):
        abort(403)
    parts = _survey_parts(survey_id)
    if not parts or parts[0]['classroom_id'] != classroom['id']:
        abort(404)
    survey, arms, questions = parts
    n = min(max(request.args.get('n', 30, type=int), 1), 500)
    seed = request.args.get('seed', type=int)
    rows = [dict(r, participant_id=r['respondent'], anon_id=f'EXAMPLE-{r["respondent"]:03d}')
            for r in fake_responses(arms, questions, n, seed=seed)]
    from models import reminders
    from models.download import anon_responses_long_csv
    long = request.args.get('format') == 'long'
    writer = anon_responses_long_csv if long else anon_responses_csv
    csv_text = writer(questions, rows, part2_from=reminders.part2_start(survey))
    name = 'EXAMPLE_responses_long' if long else 'EXAMPLE_responses'
    return Response(csv_text, mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={_group_filename(survey_id, name)}'})


# --- Per-survey download routes ---

def _require_download_access(classroom, code, survey_id):
    """Only the host or members of the survey's group can download its data. Returns redirect or None."""
    student, denied = _require_classroom_access(classroom, code)
    if denied:
        return denied
    if not _can_edit(classroom, student, survey_id):
        flash('Only members of this group can download its data.', 'danger')
        return redirect(url_for('classroom.lobby', code=code))
    return None


def _group_filename(survey_id, name):
    survey = get_survey(survey_id)
    return f'group{survey["group_number"]}_{name}.csv' if survey else f'{name}.csv'


@bp.route('/<int:survey_id>/download/responses')
def download_responses(code, survey_id):
    """Students get anonymized responses (respondent IDs, no names); the host gets everything."""
    classroom = _get_classroom_or_404(code)
    denied = _require_download_access(classroom, code, survey_id)
    if denied:
        return denied
    if _is_classroom_host(classroom['id']) and request.args.get('anonymized') != '1':
        csv_data = export_survey_responses_csv(survey_id, classroom['id'])
        filename = _group_filename(survey_id, 'responses_with_names')
    else:
        long = request.args.get('format') == 'long'
        csv_data = export_survey_responses_anon_csv(survey_id, classroom['id'], long=long)
        filename = _group_filename(survey_id, 'responses_long' if long else 'responses')
    return Response(csv_data, mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


@bp.route('/<int:survey_id>/download/config')
def download_config(code, survey_id):
    classroom = _get_classroom_or_404(code)
    denied = _require_download_access(classroom, code, survey_id)
    if denied:
        return denied
    csv_data = export_single_survey_config_csv(survey_id, classroom['id'])
    return Response(csv_data, mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={_group_filename(survey_id, "config")}'})


@bp.route('/<int:survey_id>/download/designers')
def download_designers(code, survey_id):
    classroom = _get_classroom_or_404(code)
    denied = _require_download_access(classroom, code, survey_id)
    if denied:
        return denied
    csv_data = export_single_survey_designers_csv(survey_id, classroom['id'])
    return Response(csv_data, mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={_group_filename(survey_id, "designers")}'})


@bp.route('/<int:survey_id>/download/participation')
def download_participation(code, survey_id):
    """Names of who answered: host only (it would de-anonymize the responses)."""
    classroom = _get_classroom_or_404(code)
    if not _is_classroom_host(classroom['id']):
        abort(403)
    csv_data = export_single_survey_participation_csv(survey_id, classroom['id'])
    return Response(csv_data, mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={_group_filename(survey_id, "participation")}'})
