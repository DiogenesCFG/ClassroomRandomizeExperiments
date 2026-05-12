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
    """Parse the builder form data into structured dicts."""
    title = form.get('title', '').strip()
    group_number = form.get('group_number', '').strip()
    question_type = form.get('question_type', 'multiple_choice')

    # Parse arms
    arms = []
    arm_idx = 0
    while f'arms[{arm_idx}][label]' in form:
        arm = {
            'label': form.get(f'arms[{arm_idx}][label]', '').strip(),
            'question_text': form.get(f'arms[{arm_idx}][question_text]', '').strip(),
            'options': [],
        }
        if question_type == 'multiple_choice':
            opt_idx = 0
            while f'arms[{arm_idx}][options][{opt_idx}]' in form:
                opt = form.get(f'arms[{arm_idx}][options][{opt_idx}]', '').strip()
                if opt:
                    arm['options'].append(opt)
                opt_idx += 1
        arms.append(arm)
        arm_idx += 1

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

    return title, group_number, question_type, arms, members


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
        title, group_number, question_type, arms, members = _parse_form(request.form)
        password = request.form.get('password', '').strip()

        # Validation
        errors = []
        if not title:
            errors.append('Title is required.')
        if not group_number or not group_number.isdigit():
            errors.append('Group number must be a valid number.')
        if not password:
            errors.append('A password is required to protect your survey.')
        if len(arms) < 2:
            errors.append('At least 2 arms are required.')
        for i, arm in enumerate(arms):
            if not arm['label']:
                errors.append(f'Arm {i+1} needs a label.')
            if not arm['question_text']:
                errors.append(f'Arm {i+1} needs question text.')
            if question_type == 'multiple_choice' and len(arm['options']) < 2:
                errors.append(f'Arm {i+1} needs at least 2 options for multiple choice.')
        if not members:
            errors.append('At least one group member is required.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('builder/form.html', mode='new',
                                   title=title, group_number=group_number,
                                   question_type=question_type, arms=arms, members=members,
                                   classroom=classroom)

        try:
            survey_id = create_survey(classroom['id'], title, int(group_number), question_type, password, arms, members)
            flash('Survey created successfully!', 'success')
            return redirect(url_for('builder.index', code=code))
        except Exception as e:
            flash(f'Error creating survey: {e}', 'danger')
            return render_template('builder/form.html', mode='new',
                                   title=title, group_number=group_number,
                                   question_type=question_type, arms=arms, members=members,
                                   classroom=classroom)

    # GET - show empty form
    default_arms = [
        {'label': 'Control', 'question_text': '', 'options': ['', '']},
        {'label': 'Treatment', 'question_text': '', 'options': ['', '']},
    ]
    default_members = [{'name': '', 'sis_code': ''}]
    return render_template('builder/form.html', mode='new',
                           title='', group_number='', question_type='multiple_choice',
                           arms=default_arms, members=default_members,
                           classroom=classroom)


@bp.route('/<int:survey_id>/edit', methods=['GET', 'POST'])
def edit(code, survey_id):
    classroom = _get_classroom_or_404(code)
    survey = get_survey(survey_id)
    if not survey:
        flash('Survey not found.', 'danger')
        return redirect(url_for('builder.index', code=code))

    is_host = _is_classroom_host(classroom['id'])

    if request.method == 'POST':
        # Check password (unless host)
        password = request.form.get('password', '').strip()
        if not is_host and not check_password(survey_id, password):
            flash('Incorrect password.', 'danger')
            title, group_number, question_type, arms, members = _parse_form(request.form)
            return render_template('builder/form.html', mode='edit', survey_id=survey_id,
                                   title=title, group_number=group_number,
                                   question_type=question_type, arms=arms, members=members,
                                   is_host=is_host, classroom=classroom)

        title, group_number, question_type, arms, members = _parse_form(request.form)

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
            if not arm['question_text']:
                errors.append(f'Arm {i+1} needs question text.')
            if question_type == 'multiple_choice' and len(arm['options']) < 2:
                errors.append(f'Arm {i+1} needs at least 2 options for multiple choice.')
        if not members:
            errors.append('At least one group member is required.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('builder/form.html', mode='edit', survey_id=survey_id,
                                   title=title, group_number=group_number,
                                   question_type=question_type, arms=arms, members=members,
                                   is_host=is_host, classroom=classroom)

        try:
            update_survey(survey_id, title, int(group_number), question_type, arms, members)
            flash('Survey updated successfully!', 'success')
            return redirect(url_for('builder.index', code=code))
        except Exception as e:
            flash(f'Error updating survey: {e}', 'danger')
            return render_template('builder/form.html', mode='edit', survey_id=survey_id,
                                   title=title, group_number=group_number,
                                   question_type=question_type, arms=arms, members=members,
                                   is_host=is_host, classroom=classroom)

    # GET - populate form from existing survey
    arms = []
    for arm in survey['arms']:
        arms.append({
            'label': arm['label'],
            'question_text': arm['question_text'],
            'options': [o['option_text'] for o in arm['options']] if arm['options'] else ['', ''],
        })

    members = [{'name': m['name'], 'sis_code': m['sis_code']} for m in survey['members']]
    if not members:
        members = [{'name': '', 'sis_code': ''}]

    return render_template('builder/form.html', mode='edit', survey_id=survey_id,
                           title=survey['title'], group_number=survey['group_number'],
                           question_type=survey['question_type'],
                           arms=arms, members=members, is_host=is_host,
                           classroom=classroom)


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
