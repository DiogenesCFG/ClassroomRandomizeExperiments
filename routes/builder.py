from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort

from models.classroom import get_classroom_by_code
from models.survey import (
    create_survey, get_survey, list_surveys, update_survey, delete_survey, check_password,
)

bp = Blueprint('builder', __name__, url_prefix='/c/<code>/builder')


def _get_classroom_or_404(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


def _is_classroom_host(classroom_id):
    """Check if the current session user is authenticated as host for this classroom."""
    return session.get(f'host_authenticated_{classroom_id}') is True


def _parse_form(form):
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
        question = {
            'question_type': form.get(f'questions[{q_idx}][question_type]', 'multiple_choice'),
            'label': form.get(f'questions[{q_idx}][label]', '').strip(),
            'arms': {},
        }
        for ai in range(len(arms)):
            q_text = form.get(f'questions[{q_idx}][arms][{ai}][question_text]', '').strip()
            options = []
            if question['question_type'] == 'multiple_choice':
                opt_idx = 0
                while f'questions[{q_idx}][arms][{ai}][options][{opt_idx}]' in form:
                    opt = form.get(f'questions[{q_idx}][arms][{ai}][options][{opt_idx}]', '').strip()
                    if opt:
                        options.append(opt)
                    opt_idx += 1
            question['arms'][ai] = {
                'question_text': q_text,
                'options': options,
            }
        questions.append(question)
        q_idx += 1

    # Parse members
    members = []
    mem_idx = 0
    while f'members[{mem_idx}][name]' in form:
        member = {
            'name': form.get(f'members[{mem_idx}][name]', '').strip(),
            'sis_code': form.get(f'members[{mem_idx}][sis_code]', '').strip(),
        }
        if member['name'] and member['sis_code']:
            members.append(member)
        mem_idx += 1

    return title, group_number, arms, questions, members


def _validate(title, group_number, arms, questions, members):
    """Validate form data. Returns list of error messages."""
    errors = []
    if not title:
        errors.append('Title is required.')
    if not group_number or not group_number.isdigit():
        errors.append('Group number must be a valid number.')
    if len(arms) < 2:
        errors.append('At least 2 arms are required.')
    for i, arm in enumerate(arms):
        if not arm['label']:
            errors.append(f'Arm {i+1} needs a label.')
    if not questions:
        errors.append('At least one question is required.')
    for qi, q in enumerate(questions):
        for ai in range(len(arms)):
            arm_data = q.get('arms', {}).get(ai, {})
            if not arm_data.get('question_text'):
                errors.append(f'Question {qi+1}, Arm {ai+1} needs question text.')
            if q['question_type'] == 'multiple_choice' and len(arm_data.get('options', [])) < 2:
                errors.append(f'Question {qi+1}, Arm {ai+1} needs at least 2 options.')
    if not members:
        errors.append('At least one group member is required.')
    return errors


@bp.route('/')
def index(code):
    classroom = _get_classroom_or_404(code)
    surveys = list_surveys(classroom['id'])
    is_host = _is_classroom_host(classroom['id'])
    return render_template('builder/list.html', surveys=surveys, is_host=is_host,
                           classroom=classroom)


@bp.route('/new', methods=['GET', 'POST'])
def new(code):
    classroom = _get_classroom_or_404(code)

    if request.method == 'POST':
        title, group_number, arms, questions, members = _parse_form(request.form)
        password = request.form.get('password', '').strip()

        errors = _validate(title, group_number, arms, questions, members)
        if not password:
            errors.append('A password is required to protect your survey.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('builder/form.html', mode='new',
                                   title=title, group_number=group_number,
                                   arms=arms, questions=questions, members=members,
                                   classroom=classroom)

        try:
            create_survey(classroom['id'], title, int(group_number), password, arms, questions, members)
            flash('Survey created successfully!', 'success')
            return redirect(url_for('builder.index', code=code))
        except Exception as e:
            flash(f'Error creating survey: {e}', 'danger')
            return render_template('builder/form.html', mode='new',
                                   title=title, group_number=group_number,
                                   arms=arms, questions=questions, members=members,
                                   classroom=classroom)

    # GET - show empty form with defaults
    default_arms = [
        {'label': 'Control'},
        {'label': 'Treatment'},
    ]
    default_questions = [{
        'question_type': 'multiple_choice',
        'label': '',
        'arms': {
            0: {'question_text': '', 'options': ['', '']},
            1: {'question_text': '', 'options': ['', '']},
        },
    }]
    default_members = [{'name': '', 'sis_code': ''}]
    return render_template('builder/form.html', mode='new',
                           title='', group_number='',
                           arms=default_arms, questions=default_questions,
                           members=default_members, classroom=classroom)


@bp.route('/<int:survey_id>/edit', methods=['GET', 'POST'])
def edit(code, survey_id):
    classroom = _get_classroom_or_404(code)
    survey = get_survey(survey_id)
    if not survey:
        flash('Survey not found.', 'danger')
        return redirect(url_for('builder.index', code=code))

    is_host = _is_classroom_host(classroom['id'])

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        if not is_host and not check_password(survey_id, password):
            flash('Incorrect password.', 'danger')
            title, group_number, arms, questions, members = _parse_form(request.form)
            return render_template('builder/form.html', mode='edit', survey_id=survey_id,
                                   title=title, group_number=group_number,
                                   arms=arms, questions=questions, members=members,
                                   is_host=is_host, classroom=classroom)

        title, group_number, arms, questions, members = _parse_form(request.form)

        errors = _validate(title, group_number, arms, questions, members)

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('builder/form.html', mode='edit', survey_id=survey_id,
                                   title=title, group_number=group_number,
                                   arms=arms, questions=questions, members=members,
                                   is_host=is_host, classroom=classroom)

        try:
            update_survey(survey_id, title, int(group_number), arms, questions, members)
            flash('Survey updated successfully!', 'success')
            return redirect(url_for('builder.index', code=code))
        except Exception as e:
            flash(f'Error updating survey: {e}', 'danger')
            return render_template('builder/form.html', mode='edit', survey_id=survey_id,
                                   title=title, group_number=group_number,
                                   arms=arms, questions=questions, members=members,
                                   is_host=is_host, classroom=classroom)

    # GET - populate form from existing survey
    arms = [{'label': a['label']} for a in survey['arms']]

    questions = []
    for q in survey.get('questions', []):
        question = {
            'question_type': q['question_type'],
            'label': q.get('label', ''),
            'arms': {},
        }
        for ai in range(len(arms)):
            arm_data = q.get('arms', {}).get(ai, {})
            options = arm_data.get('options', [])
            if not options and q['question_type'] == 'multiple_choice':
                options = ['', '']
            question['arms'][ai] = {
                'question_text': arm_data.get('question_text', ''),
                'options': options,
            }
        questions.append(question)

    # Fallback if no questions found (legacy data)
    if not questions:
        questions = [{
            'question_type': survey.get('question_type', 'multiple_choice'),
            'label': '',
            'arms': {
                ai: {
                    'question_text': a.get('question_text', ''),
                    'options': ['', ''],
                } for ai, a in enumerate(survey.get('arms', []))
            },
        }]

    members = [{'name': m['name'], 'sis_code': m['sis_code']} for m in survey.get('members', [])]
    if not members:
        members = [{'name': '', 'sis_code': ''}]

    return render_template('builder/form.html', mode='edit', survey_id=survey_id,
                           title=survey['title'], group_number=survey['group_number'],
                           arms=arms, questions=questions, members=members,
                           is_host=is_host, classroom=classroom)


@bp.route('/<int:survey_id>/delete', methods=['POST'])
def delete(code, survey_id):
    classroom = _get_classroom_or_404(code)
    is_host = _is_classroom_host(classroom['id'])
    password = request.form.get('password', '').strip()

    if not is_host and not check_password(survey_id, password):
        flash('Incorrect password. Cannot delete survey.', 'danger')
        return redirect(url_for('builder.index', code=code))

    try:
        delete_survey(survey_id)
        flash('Survey deleted.', 'success')
    except Exception as e:
        flash(f'Error deleting survey: {e}', 'danger')
    return redirect(url_for('builder.index', code=code))
