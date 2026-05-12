from flask import Blueprint, render_template, request, current_app, abort

from models.survey import list_surveys

bp = Blueprint('host', __name__, url_prefix='/host')


@bp.route('/')
def login():
    return render_template('host/login.html')


@bp.route('/dashboard')
def dashboard():
    token = request.args.get('token', '')
    if token != current_app.config['HOST_TOKEN']:
        abort(403)

    surveys = list_surveys()
    return render_template('host/dashboard.html',
                           surveys=surveys,
                           token=token)
