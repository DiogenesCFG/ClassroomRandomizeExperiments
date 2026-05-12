from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort

from models.classroom import get_classroom_by_code, check_host_password
from models.survey import list_surveys

bp = Blueprint('host', __name__, url_prefix='/c/<code>/host')


def _get_classroom_or_404(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        abort(404)
    return classroom


@bp.route('/', methods=['GET', 'POST'])
def login(code):
    classroom = _get_classroom_or_404(code)

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        if check_host_password(classroom['id'], password):
            session[f'host_authenticated_{classroom["id"]}'] = True
            return redirect(url_for('host.dashboard', code=code))
        else:
            flash('Incorrect host password.', 'danger')

    # If already authenticated, go straight to dashboard
    if session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.dashboard', code=code))

    return render_template('host/login.html', classroom=classroom)


@bp.route('/dashboard')
def dashboard(code):
    classroom = _get_classroom_or_404(code)

    if not session.get(f'host_authenticated_{classroom["id"]}'):
        return redirect(url_for('host.login', code=code))

    surveys = list_surveys(classroom['id'])
    return render_template('host/dashboard.html',
                           surveys=surveys,
                           classroom=classroom)
