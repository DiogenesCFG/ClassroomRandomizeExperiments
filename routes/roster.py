import json
import os
import time
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort, current_app

from models.classroom import get_classroom_by_code, set_max_groups, parse_max_groups, set_max_group_size, parse_max_group_size
from models import roster as roster_model

bp = Blueprint('roster', __name__, url_prefix='/c/<code>/host/roster')


def _get_host_classroom(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    if not session.get(f'host_authenticated_{classroom["id"]}'):
        abort(403)
    return classroom


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def render_import_preview(classroom, csv_text, mapping=None, hide_missing=False):
    """Render the column-mapping preview for an uploaded roster CSV."""
    rows = roster_model.read_csv_rows(csv_text)
    if not rows:
        flash('That file appears to be empty.', 'danger')
        return redirect(url_for('roster.index', code=classroom['code']))
    headers, data = rows[0], rows[1:]
    if mapping is None:
        mapping = roster_model.guess_mapping(headers)
    students, skipped = [], []
    ready = mapping['id_col'] is not None and (
        mapping['full_col'] is not None if mapping['name_mode'] == 'full'
        else mapping['first_col'] is not None or mapping['last_col'] is not None)
    if ready:
        students, skipped = roster_model.parse_roster(data, mapping)
    return render_template('host/roster_import.html', classroom=classroom, csv_text=csv_text,
                           headers=headers, mapping=mapping, students=students, skipped=skipped,
                           ready=ready, hide_missing=hide_missing,
                           existing_count=len(roster_model.list_roster(classroom['id'])))


def _upload_dir():
    path = os.path.join(current_app.instance_path, 'roster_uploads')
    os.makedirs(path, exist_ok=True)
    return path


def _keep_csv(csv_text):
    """Keep an uploaded roster CSV for a day so its import can be undone and redone with other columns."""
    folder = _upload_dir()
    cutoff = time.time() - 24 * 3600
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass
    token = uuid.uuid4().hex
    with open(os.path.join(folder, token + '.csv'), 'w', encoding='utf-8') as f:
        f.write(csv_text)
    return token


def import_or_preview(classroom, csv_text, hide_missing=False):
    """Save the roster straight away when the ID and name columns are recognized
    (the roster page then shows which columns were used, with an undo). Otherwise
    show the column-choice preview."""
    rows = roster_model.read_csv_rows(csv_text)
    if not rows:
        flash('That file appears to be empty.', 'danger')
        return redirect(url_for('roster.index', code=classroom['code']))
    headers, data = rows[0], rows[1:]
    mapping = roster_model.guess_mapping(headers)
    complete = mapping['id_col'] is not None and (
        mapping['full_col'] is not None if mapping['name_mode'] == 'full'
        else mapping['first_col'] is not None and mapping['last_col'] is not None)
    students, skipped = roster_model.parse_roster(data, mapping) if complete else ([], [])
    if not students:
        return render_import_preview(classroom, csv_text, hide_missing=hide_missing)

    counts = roster_model.import_students(classroom['id'], students, hide_missing=hide_missing)
    if mapping['name_mode'] == 'full':
        name_cols = [headers[mapping['full_col']]]
    else:
        name_cols = [headers[mapping['first_col']], headers[mapping['last_col']]]
    token = _keep_csv(csv_text)
    # The added IDs can be long for big classes, so they live next to the CSV rather than in the cookie
    with open(os.path.join(_upload_dir(), token + '.json'), 'w', encoding='utf-8') as f:
        json.dump(counts['added_ids'], f)
    session['last_import'] = {
        'classroom_id': classroom['id'], 'token': token,
        'added': counts['added'], 'updated': counts['updated'],
        'hidden': counts['hidden'], 'skipped': len(skipped),
        'id_col': headers[mapping['id_col']], 'name_cols': name_cols,
        'example': f'{students[0]["full_name"]} ({students[0]["sis_id"]}), shown as "{students[0]["first_name"]}"',
    }
    return redirect(url_for('roster.index', code=classroom['code']))


@bp.route('/')
def index(code):
    classroom = _get_host_classroom(code)
    students = roster_model.list_roster(classroom['id'])
    last_import = session.get('last_import')
    if not last_import or last_import.get('classroom_id') != classroom['id']:
        last_import = None
    return render_template('host/roster.html', classroom=classroom, students=students, last_import=last_import)


@bp.route('/upload', methods=['POST'])
def upload(code):
    classroom = _get_host_classroom(code)
    f = request.files.get('roster_file')
    if not f or not f.filename:
        flash('Choose a CSV file to upload.', 'danger')
        return redirect(url_for('roster.index', code=code))
    csv_text = roster_model.decode_csv_bytes(f.read())
    return import_or_preview(classroom, csv_text, hide_missing=request.form.get('hide_missing') == '1')


@bp.route('/dismiss-import', methods=['POST'])
def dismiss_import(code):
    _get_host_classroom(code)
    session.pop('last_import', None)
    return redirect(url_for('roster.index', code=code))


@bp.route('/undo-import', methods=['POST'])
def undo_import(code):
    """Remove the students the last automatic import added, then let the host pick the columns."""
    classroom = _get_host_classroom(code)
    last_import = session.pop('last_import', None)
    if not last_import or last_import.get('classroom_id') != classroom['id']:
        flash('There is no import to undo.', 'danger')
        return redirect(url_for('roster.index', code=code))
    base = os.path.join(_upload_dir(), last_import['token'])
    try:
        with open(base + '.json', encoding='utf-8') as f:
            added_ids = json.load(f)
        with open(base + '.csv', encoding='utf-8') as f:
            csv_text = f.read()
    except (OSError, ValueError):
        flash('That import is too old to undo. Remove students from the roster table instead.', 'danger')
        return redirect(url_for('roster.index', code=code))
    removed = roster_model.undo_added_students(classroom['id'], added_ids)
    kept = len(added_ids) - removed
    flash(f'Removed {removed} students from that import. Choose the right columns below.' +
          (f' {kept} were kept because they had already signed up or joined a group.' if kept else ''), 'info')
    return render_import_preview(classroom, csv_text)


@bp.route('/import', methods=['POST'])
def import_roster(code):
    classroom = _get_host_classroom(code)
    csv_text = request.form.get('csv_text', '')
    mapping = {
        'id_col': _int_or_none(request.form.get('id_col')),
        'name_mode': 'split' if request.form.get('name_mode') == 'split' else 'full',
        'full_col': _int_or_none(request.form.get('full_col')),
        'first_col': _int_or_none(request.form.get('first_col')),
        'last_col': _int_or_none(request.form.get('last_col')),
    }
    hide_missing = request.form.get('hide_missing') == '1'

    if request.form.get('action') != 'save':
        return render_import_preview(classroom, csv_text, mapping, hide_missing)

    rows = roster_model.read_csv_rows(csv_text)
    students, _ = roster_model.parse_roster(rows[1:], mapping) if rows else ([], [])
    if not students:
        flash('No students found with those column choices.', 'danger')
        return render_import_preview(classroom, csv_text, mapping, hide_missing)
    counts = roster_model.import_students(classroom['id'], students, hide_missing=hide_missing)
    session.pop('last_import', None)
    msg = f'Roster saved: {counts["added"]} added, {counts["updated"]} already on the roster (names updated).'
    if hide_missing:
        msg += f' {counts["hidden"]} hidden (not in the file).'
    flash(msg, 'success')
    return redirect(url_for('roster.index', code=code))


@bp.route('/add', methods=['POST'])
def add(code):
    classroom = _get_host_classroom(code)
    error = roster_model.add_student(classroom['id'], request.form.get('sis_id', ''),
                                     request.form.get('full_name', ''))
    if error:
        flash(error, 'danger')
    else:
        flash('Student added.', 'success')
    return redirect(url_for('roster.index', code=code))


@bp.route('/<int:student_id>/reset-password', methods=['POST'])
def reset_password(code, student_id):
    classroom = _get_host_classroom(code)
    student = roster_model.get_student(classroom['id'], student_id)
    if student:
        roster_model.reset_password(classroom['id'], student_id)
        flash(f'Password reset for {student["full_name"]}. They will choose a new one next time they sign in.',
              'success')
    return redirect(url_for('roster.index', code=code))


@bp.route('/<int:student_id>/hide', methods=['POST'])
def hide(code, student_id):
    classroom = _get_host_classroom(code)
    roster_model.set_hidden(classroom['id'], student_id, True)
    return redirect(url_for('roster.index', code=code))


@bp.route('/<int:student_id>/unhide', methods=['POST'])
def unhide(code, student_id):
    classroom = _get_host_classroom(code)
    roster_model.set_hidden(classroom['id'], student_id, False)
    return redirect(url_for('roster.index', code=code))


@bp.route('/max-group-size', methods=['POST'])
def max_group_size(code):
    classroom = _get_host_classroom(code)
    value, error = parse_max_group_size(request.form.get('max_group_size'))
    if error:
        flash(error, 'danger')
    else:
        set_max_group_size(classroom['id'], value)
        flash('Group size limit saved: ' + (f'at most {value} members per group.' if value else 'no limit.')
              + ' Groups already above it keep their members.', 'success')
    return redirect(url_for('roster.index', code=code))


@bp.route('/max-groups', methods=['POST'])
def max_groups(code):
    classroom = _get_host_classroom(code)
    value, error = parse_max_groups(request.form.get('max_groups'))
    if error:
        flash(error, 'danger')
    else:
        set_max_groups(classroom['id'], value)
        flash('Group limit saved: ' + (f'{value} per student.' if value else 'no limit.'), 'success')
    nxt = request.form.get('next', '')
    if not nxt.startswith('/') or nxt.startswith('//'):
        nxt = url_for('roster.index', code=code)
    return redirect(nxt)
