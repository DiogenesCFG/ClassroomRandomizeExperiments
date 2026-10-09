from flask import Blueprint, render_template, send_from_directory, current_app

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    return render_template('index.html')


@bp.route('/sw.js')
def service_worker():
    """The notification service worker, served from the root so it covers every page."""
    response = send_from_directory(current_app.static_folder, 'js/sw.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response
