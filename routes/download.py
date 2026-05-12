from flask import Blueprint, Response, session, abort

from models.classroom import get_classroom_by_code
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
