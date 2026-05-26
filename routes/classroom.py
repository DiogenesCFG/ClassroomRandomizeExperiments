import sqlite3

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from models.classroom import create_classroom, get_classroom_by_code, check_host_password, check_classroom_password

bp = Blueprint('classroom', __name__, url_prefix='/c')


@bp.route('/create', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        name = request.form.get('name', '').strip()
        host_password = request.form.get('host_password', '').strip()
        host_password_confirm = request.form.get('host_password_confirm', '').strip()
        classroom_password = request.form.get('classroom_password', '').strip()
        classroom_password_confirm = request.form.get('classroom_password_confirm', '').strip()

        errors = []
        if not code:
            errors.append('Classroom code is required.')
        if not name:
            errors.append('Classroom name is required.')
        if not host_password:
            errors.append('Host password is required.')
        elif host_password != host_password_confirm:
            errors.append('Host passwords do not match.')
        if not classroom_password:
            errors.append('Classroom password is required.')
        elif classroom_password != classroom_password_confirm:
            errors.append('Classroom passwords do not match.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('classroom/create.html', code=code, name=name)

        try:
            classroom = create_classroom(code, name, host_password, classroom_password)
            session[f'classroom_joined_{classroom["id"]}'] = True
            flash(f'Classroom "{name}" created with code {classroom["code"]}!', 'success')
            return redirect(url_for('classroom.lobby', code=classroom['code']))
        except sqlite3.IntegrityError:
            flash('A classroom with that code already exists.', 'danger')
            return render_template('classroom/create.html', code=code, name=name)

    return render_template('classroom/create.html', code='', name='')


@bp.route('/join', methods=['GET', 'POST'])
def join():
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        password = request.form.get('password', '').strip()
        classroom = get_classroom_by_code(code)
        if not classroom:
            flash('Classroom not found. Check the code and try again.', 'danger')
            return render_template('classroom/join.html', prefill_code=code)

        if not check_classroom_password(classroom['id'], password):
            flash('Incorrect classroom password.', 'danger')
            return render_template('classroom/join.html', prefill_code=code)

        session['classroom_id'] = classroom['id']
        session['classroom_code'] = classroom['code']
        session['classroom_name'] = classroom['name']
        session[f'classroom_joined_{classroom["id"]}'] = True
        return redirect(url_for('classroom.lobby', code=classroom['code']))

    prefill_code = request.args.get('code', '')
    prefill_password = request.args.get('password', '')
    return render_template('classroom/join.html', prefill_code=prefill_code, prefill_password=prefill_password)


@bp.route('/<code>/lobby')
def lobby(code):
    classroom = get_classroom_by_code(code)
    if not classroom:
        flash('Classroom not found.', 'danger')
        return redirect(url_for('main.index'))

    # Allow access if student joined via password or host is authenticated
    if not session.get(f'classroom_joined_{classroom["id"]}') and \
       not session.get(f'host_authenticated_{classroom["id"]}'):
        flash('Please join the classroom first.', 'danger')
        return redirect(url_for('classroom.join', code=code))

    session['classroom_id'] = classroom['id']
    session['classroom_code'] = classroom['code']
    session['classroom_name'] = classroom['name']
    return render_template('classroom/lobby.html', classroom=classroom)


@bp.route('/host-join', methods=['GET', 'POST'])
def host_join():
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        password = request.form.get('password', '').strip()
        classroom = get_classroom_by_code(code)
        if not classroom:
            flash('Classroom not found. Check the code and try again.', 'danger')
            return render_template('classroom/host_join.html')
        if not check_host_password(classroom['id'], password):
            flash('Incorrect host password.', 'danger')
            return render_template('classroom/host_join.html')

        session[f'host_authenticated_{classroom["id"]}'] = True
        session['classroom_id'] = classroom['id']
        session['classroom_code'] = classroom['code']
        session['classroom_name'] = classroom['name']
        return redirect(url_for('host.dashboard', code=classroom['code']))

    return render_template('classroom/host_join.html')
