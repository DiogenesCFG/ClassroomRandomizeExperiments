import csv
import io
import os
import zipfile
from datetime import datetime

from flask import Blueprint, Response, session, abort, redirect, url_for, request, flash, current_app
from werkzeug.utils import secure_filename

from models.classroom import get_classroom_by_code, check_host_password
from models.db import get_db
from models.download import (
    export_all_responses_csv, export_surveys_config_csv, export_participants_csv,
    export_survey_designers_csv, export_survey_participation_csv,
)

bp = Blueprint('download', __name__, url_prefix='/c/<code>/download')


def _get_classroom_or_403(code):
    """Get classroom and verify host authentication."""
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    if not session.get(f'host_authenticated_{classroom["id"]}'):
        abort(403)
    return classroom


@bp.route('/all')
def download_all(code):
    classroom = _get_classroom_or_403(code)
    csv_data = export_all_responses_csv(classroom['id'])
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=all_responses.csv'}
    )


@bp.route('/surveys-config')
def download_surveys_config(code):
    classroom = _get_classroom_or_403(code)
    csv_data = export_surveys_config_csv(classroom['id'])
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=surveys_config.csv'}
    )


@bp.route('/participants')
def download_participants(code):
    classroom = _get_classroom_or_403(code)
    csv_data = export_participants_csv(classroom['id'])
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=participants.csv'}
    )


@bp.route('/designers')
def download_designers(code):
    classroom = _get_classroom_or_403(code)
    csv_data = export_survey_designers_csv(classroom['id'])
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=survey_designers.csv'}
    )


@bp.route('/participation')
def download_participation(code):
    classroom = _get_classroom_or_403(code)
    csv_data = export_survey_participation_csv(classroom['id'])
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=survey_participation.csv'}
    )


@bp.route('/everything')
def download_everything(code):
    """Download all CSV exports plus uploaded images as a single .zip archive."""
    classroom = _get_classroom_or_403(code)
    cid = classroom['id']

    images = get_db().execute('''
        SELECT s.group_number, s.title AS survey_title, sa.label AS arm_label,
               sq.question_index, aq.image_filename
        FROM arm_question aq
        JOIN survey_arm sa ON aq.arm_id = sa.id
        JOIN survey s ON sa.survey_id = s.id
        JOIN survey_question sq ON aq.question_id = sq.id
        WHERE s.classroom_id = ? AND aq.image_filename IS NOT NULL
        ORDER BY s.group_number, sq.question_index, sa.arm_index
    ''', (cid,)).fetchall()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('all_responses.csv', export_all_responses_csv(cid))
        zf.writestr('surveys_config.csv', export_surveys_config_csv(cid))
        zf.writestr('participants.csv', export_participants_csv(cid))
        zf.writestr('survey_designers.csv', export_survey_designers_csv(cid))
        zf.writestr('survey_participation.csv', export_survey_participation_csv(cid))

        index = io.StringIO()
        writer = csv.writer(index)
        writer.writerow(['group_number', 'survey_title', 'arm_label', 'question_index', 'file', 'found'])
        written = set()
        for img in images:
            fn = img['image_filename']
            arcname = f'images/{fn}'
            path = os.path.join(current_app.config['UPLOAD_FOLDER'], fn)
            found = os.path.isfile(path)
            if found and arcname not in written:
                zf.write(path, arcname)
                written.add(arcname)
            writer.writerow([img['group_number'], img['survey_title'], img['arm_label'],
                             img['question_index'], arcname, 'yes' if found else 'missing'])
        zf.writestr('images_index.csv', index.getvalue())

    stamp = datetime.now().strftime('%Y-%m-%d')
    filename = secure_filename(f'{classroom["code"]}_export_{stamp}.zip')
    return Response(
        buf.getvalue(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@bp.route('/clear-responses', methods=['POST'])
def clear_responses(code):
    """Delete all responses for this classroom (keeps surveys and participants)."""
    classroom = _get_classroom_or_403(code)

    password = request.form.get('host_password', '').strip()
    if not check_host_password(classroom['id'], password):
        flash('Incorrect host password.', 'danger')
        return redirect(url_for('host.dashboard', code=code))

    db = get_db()
    db.execute(
        'DELETE FROM response WHERE survey_id IN (SELECT id FROM survey WHERE classroom_id=?)',
        (classroom['id'],)
    )
    db.commit()
    return redirect(url_for('host.dashboard', code=code))
