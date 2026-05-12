from flask import Blueprint, Response, session, abort, redirect, url_for

from models.classroom import get_classroom_by_code
from models.db import get_db
from models.download import export_all_responses_csv, export_surveys_config_csv, export_participants_csv

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


@bp.route('/clear-responses', methods=['POST'])
def clear_responses(code):
    """Delete all responses for this classroom (keeps surveys and participants)."""
    classroom = _get_classroom_or_403(code)
    db = get_db()
    db.execute(
        'DELETE FROM response WHERE survey_id IN (SELECT id FROM survey WHERE classroom_id=?)',
        (classroom['id'],)
    )
    db.commit()
    return redirect(url_for('host.dashboard', code=code))
