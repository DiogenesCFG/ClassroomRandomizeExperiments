from flask import Blueprint, Response, request, current_app, abort

from models.download import export_all_responses_csv, export_surveys_config_csv, export_participants_csv

bp = Blueprint('download', __name__, url_prefix='/download')


def _check_token():
    token = request.args.get('token', '')
    if token != current_app.config['HOST_TOKEN']:
        abort(403)


@bp.route('/all')
def download_all():
    _check_token()
    csv_data = export_all_responses_csv()
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=all_responses.csv'}
    )


@bp.route('/surveys-config')
def download_surveys_config():
    _check_token()
    csv_data = export_surveys_config_csv()
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=surveys_config.csv'}
    )


@bp.route('/participants')
def download_participants():
    _check_token()
    csv_data = export_participants_csv()
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=participants.csv'}
    )
