from flask import current_app, session
from flask_socketio import emit, join_room, leave_room

from app import socketio
from models.db import get_socket_db
from sockets.assignment import assign_arm


def _get_survey_with_arms(db, survey_id):
    """Helper to get survey + arms + options."""
    survey = db.execute('SELECT * FROM survey WHERE id=?', (survey_id,)).fetchone()
    if not survey:
        return None
    arms = db.execute(
        'SELECT * FROM survey_arm WHERE survey_id=? ORDER BY arm_index', (survey_id,)
    ).fetchall()
    arms_list = []
    for arm in arms:
        arm_dict = dict(arm)
        options = db.execute(
            'SELECT * FROM arm_option WHERE arm_id=? ORDER BY option_index', (arm['id'],)
        ).fetchall()
        arm_dict['options'] = [dict(o) for o in options]
        arms_list.append(arm_dict)
    return dict(survey), arms_list


def _build_assignment_payload(survey, arms, student_id):
    """Build the assignment payload for a specific student."""
    num_arms = len(arms)
    arm_index = assign_arm(student_id, survey['id'], num_arms)
    arm = arms[arm_index]

    payload = {
        'survey_id': survey['id'],
        'group_number': survey['group_number'],
        'title': survey['title'],
        'question_type': survey['question_type'],
        'arm_id': arm['id'],
        'arm_index': arm['arm_index'],
        'arm_label': arm['label'],
        'question_text': arm['question_text'],
        'options': [o['option_text'] for o in arm['options']],
    }
    return payload


def _get_aggregated_results(db, survey_id):
    """Get results for broadcasting to host."""
    survey = db.execute('SELECT * FROM survey WHERE id=?', (survey_id,)).fetchone()
    if not survey:
        return None

    arms = db.execute(
        'SELECT * FROM survey_arm WHERE survey_id=? ORDER BY arm_index', (survey_id,)
    ).fetchall()

    result = {
        'survey_id': survey_id,
        'question_type': survey['question_type'],
        'title': survey['title'],
        'group_number': survey['group_number'],
        'arms': [],
        'total_responses': 0,
    }

    for arm in arms:
        arm_data = {
            'arm_id': arm['id'],
            'arm_index': arm['arm_index'],
            'label': arm['label'],
            'question_text': arm['question_text'],
        }

        responses = db.execute(
            'SELECT answer_text, answer_index FROM response WHERE survey_id=? AND arm_id=?',
            (survey_id, arm['id']),
        ).fetchall()

        result['total_responses'] += len(responses)

        if survey['question_type'] == 'multiple_choice':
            options = db.execute(
                'SELECT * FROM arm_option WHERE arm_id=? ORDER BY option_index', (arm['id'],)
            ).fetchall()
            option_texts = [o['option_text'] for o in options]

            counts = {opt: 0 for opt in option_texts}
            for r in responses:
                if r['answer_text'] in counts:
                    counts[r['answer_text']] += 1

            arm_data['options'] = option_texts
            arm_data['counts'] = counts
            arm_data['n'] = len(responses)
        else:
            values = []
            for r in responses:
                try:
                    values.append(float(r['answer_text']))
                except (ValueError, TypeError):
                    pass

            arm_data['values'] = values
            arm_data['n'] = len(values)
            if values:
                sorted_vals = sorted(values)
                mean = sum(values) / len(values)
                arm_data['stats'] = {
                    'mean': round(mean, 2),
                    'median': round(sorted_vals[len(sorted_vals) // 2], 2),
                    'min': round(min(values), 2),
                    'max': round(max(values), 2),
                    'std': round((sum((x - mean)**2 for x in values) / len(values)) ** 0.5, 2),
                }
            else:
                arm_data['stats'] = None

        result['arms'].append(arm_data)

    participant_count = db.execute('SELECT COUNT(*) as cnt FROM participant').fetchone()['cnt']
    result['participant_count'] = participant_count

    return result


@socketio.on('join_student')
def handle_join_student(data):
    """Student connects to the session."""
    participant_id = data.get('participant_id')
    student_id = data.get('student_id')
    join_room('students')

    db = get_socket_db()
    try:
        # Check if there's an active survey
        active = db.execute('SELECT * FROM survey WHERE is_active=1').fetchone()
        if active:
            survey_data = _get_survey_with_arms(db, active['id'])
            if survey_data:
                survey, arms = survey_data
                # Check if already answered
                already = db.execute(
                    'SELECT id FROM response WHERE participant_id=? AND survey_id=?',
                    (participant_id, active['id']),
                ).fetchone()

                if already:
                    emit('already_answered', {'survey_id': active['id']})
                else:
                    payload = _build_assignment_payload(survey, arms, student_id)
                    emit('assignment', payload)
        else:
            emit('waiting', {})

        # Broadcast updated participant count to host
        count = db.execute('SELECT COUNT(*) as cnt FROM participant').fetchone()['cnt']
        emit('participant_count', {'count': count}, room='host')
    finally:
        db.close()


@socketio.on('join_host')
def handle_join_host(data):
    """Host connects to the dashboard."""
    join_room('host')

    db = get_socket_db()
    try:
        count = db.execute('SELECT COUNT(*) as cnt FROM participant').fetchone()['cnt']
        emit('participant_count', {'count': count})

        # Send current active survey results if any
        active = db.execute('SELECT * FROM survey WHERE is_active=1').fetchone()
        if active:
            results = _get_aggregated_results(db, active['id'])
            if results:
                emit('results_update', results)
    finally:
        db.close()


@socketio.on('activate_survey')
def handle_activate_survey(data):
    """Host activates a survey."""
    survey_id = data.get('survey_id')

    db = get_socket_db()
    try:
        # Deactivate all, activate this one
        db.execute('UPDATE survey SET is_active=0 WHERE is_active=1')
        db.execute('UPDATE survey SET is_active=1 WHERE id=?', (survey_id,))
        db.commit()

        survey_data = _get_survey_with_arms(db, survey_id)
        if not survey_data:
            return

        survey, arms = survey_data

        # Notify all students
        emit('survey_activated', {
            'survey_id': survey_id,
            'group_number': survey['group_number'],
            'title': survey['title'],
        }, room='students')

        # Send initial (empty) results to host
        results = _get_aggregated_results(db, survey_id)
        emit('results_update', results, room='host')
    finally:
        db.close()


@socketio.on('request_assignment')
def handle_request_assignment(data):
    """Student requests their arm assignment for the active survey."""
    participant_id = data.get('participant_id')
    student_id = data.get('student_id')
    survey_id = data.get('survey_id')

    db = get_socket_db()
    try:
        # Check if already answered
        already = db.execute(
            'SELECT id FROM response WHERE participant_id=? AND survey_id=?',
            (participant_id, survey_id),
        ).fetchone()

        if already:
            emit('already_answered', {'survey_id': survey_id})
            return

        survey_data = _get_survey_with_arms(db, survey_id)
        if not survey_data:
            return

        survey, arms = survey_data
        payload = _build_assignment_payload(survey, arms, student_id)
        emit('assignment', payload)
    finally:
        db.close()


@socketio.on('submit_answer')
def handle_submit_answer(data):
    """Student submits their answer."""
    participant_id = data.get('participant_id')
    survey_id = data.get('survey_id')
    arm_id = data.get('arm_id')
    answer_text = data.get('answer_text')
    answer_index = data.get('answer_index')

    db = get_socket_db()
    try:
        try:
            db.execute(
                'INSERT INTO response (participant_id, survey_id, arm_id, answer_text, answer_index) '
                'VALUES (?, ?, ?, ?, ?)',
                (participant_id, survey_id, arm_id, answer_text, answer_index),
            )
            db.commit()
            emit('answer_saved', {'survey_id': survey_id})
        except Exception:
            emit('already_answered', {'survey_id': survey_id})
            return

        # Broadcast updated results to host
        results = _get_aggregated_results(db, survey_id)
        if results:
            emit('results_update', results, room='host')
    finally:
        db.close()


@socketio.on('next_survey')
def handle_next_survey(data):
    """Host advances to the next survey."""
    db = get_socket_db()
    try:
        current = db.execute('SELECT * FROM survey WHERE is_active=1').fetchone()
        if current:
            next_row = db.execute(
                'SELECT id FROM survey WHERE group_number > ? ORDER BY group_number LIMIT 1',
                (current['group_number'],),
            ).fetchone()

            # Deactivate current
            db.execute('UPDATE survey SET is_active=0 WHERE id=?', (current['id'],))
            db.commit()

            if next_row:
                # Activate next
                db.execute('UPDATE survey SET is_active=1 WHERE id=?', (next_row['id'],))
                db.commit()

                survey_data = _get_survey_with_arms(db, next_row['id'])
                if survey_data:
                    survey, arms = survey_data
                    emit('survey_activated', {
                        'survey_id': next_row['id'],
                        'group_number': survey['group_number'],
                        'title': survey['title'],
                    }, room='students')

                    results = _get_aggregated_results(db, next_row['id'])
                    emit('results_update', results, room='host')
                    emit('survey_changed', {'survey_id': next_row['id']}, room='host')
            else:
                # No more surveys
                emit('survey_deactivated', {}, room='students')
                emit('all_done', {}, room='host')
        else:
            # No active survey; activate the first one
            first = db.execute('SELECT id FROM survey ORDER BY group_number LIMIT 1').fetchone()
            if first:
                handle_activate_survey({'survey_id': first['id']})
    finally:
        db.close()


@socketio.on('deactivate_all')
def handle_deactivate_all(data):
    """Host resets the session."""
    db = get_socket_db()
    try:
        db.execute('UPDATE survey SET is_active=0 WHERE is_active=1')
        db.commit()
        emit('survey_deactivated', {}, room='students')
        emit('session_reset', {}, room='host')
    finally:
        db.close()
