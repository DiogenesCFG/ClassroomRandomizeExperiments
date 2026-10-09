import json
import logging
import sqlite3

from flask import current_app, session
from flask_socketio import emit, join_room, leave_room

from app import socketio
from models.db import get_socket_db
from models import reminders, rules
from sockets.assignment import assign_arm

logger = logging.getLogger(__name__)

# Stored answer for the "Other" choice; what the respondent typed goes in response.other_text
OTHER_LABEL = 'Other'


def _get_survey_with_arms_and_questions(db, survey_id):
    """Helper to get survey + arms + questions with per-arm texts/options."""
    survey = db.execute('SELECT * FROM survey WHERE id=?', (survey_id,)).fetchone()
    if not survey:
        return None

    arms = db.execute(
        'SELECT * FROM survey_arm WHERE survey_id=? ORDER BY arm_index', (survey_id,)
    ).fetchall()

    questions = db.execute(
        'SELECT * FROM survey_question WHERE survey_id=? ORDER BY question_index', (survey_id,)
    ).fetchall()

    # Batch-fetch all arm_questions for this survey's arms and questions
    arm_ids = [a['id'] for a in arms]
    question_ids = [q['id'] for q in questions]

    aq_by_key = {}
    options_by_aq = {}

    if arm_ids and question_ids:
        ph_arms = ','.join('?' * len(arm_ids))
        ph_qs = ','.join('?' * len(question_ids))
        arm_questions = db.execute(
            'SELECT * FROM arm_question WHERE arm_id IN ({}) AND question_id IN ({})'.format(ph_arms, ph_qs),
            arm_ids + question_ids
        ).fetchall()

        for aq in arm_questions:
            aq_by_key[(aq['arm_id'], aq['question_id'])] = aq

        aq_ids = [aq['id'] for aq in arm_questions]
        if aq_ids:
            ph_aq = ','.join('?' * len(aq_ids))
            all_options = db.execute(
                'SELECT * FROM arm_question_option WHERE arm_question_id IN ({}) ORDER BY option_index'.format(ph_aq),
                aq_ids
            ).fetchall()
            for o in all_options:
                options_by_aq.setdefault(o['arm_question_id'], []).append(o['option_text'])

    questions_list = []
    for q in questions:
        q_dict = dict(q)
        q_dict.update(rules.from_row(q))
        q_dict['arm_texts'] = {}
        for arm in arms:
            aq = aq_by_key.get((arm['id'], q['id']))
            if aq:
                q_dict['arm_texts'][arm['id']] = {
                    'question_text': aq['question_text'],
                    'options': options_by_aq.get(aq['id'], []),
                    'image_filename': aq['image_filename'],
                    'allow_other': bool(aq['allow_other']),
                    'timer_seconds': aq['timer_seconds'],
                    'timer_display': aq['timer_display'] or 'both',
                    'timer_default': aq['timer_default'] or '',
                }
            else:
                q_dict['arm_texts'][arm['id']] = {
                    'question_text': '',
                    'options': [],
                    'image_filename': None,
                    'allow_other': False,
                }
        questions_list.append(q_dict)

    return dict(survey), [dict(a) for a in arms], questions_list


def _build_assignment_payload(survey, arms, questions, student_id, arm_position=None, part=1):
    """Build the assignment payload for a specific student.

    arm_position forces a specific arm (used by the builder's "Preview survey").
    part: which part of a two-part survey (part 1 runs live; part 2 is answered later).
    """
    two_part = reminders.is_two_part(survey)
    num_arms = len(arms)
    if arm_position is None:
        arm_position = assign_arm(student_id, survey['id'], num_arms)
    arm = arms[arm_position]

    payload = {
        'survey_id': survey['id'],
        'group_number': survey['group_number'],
        'title': survey['title'],
        'arm_id': arm['id'],
        'arm_index': arm['arm_index'],
        'arm_label': arm['label'],
        'part': part if two_part else None,
        'questions': [],
    }

    for q in questions:
        if not rules.shown_in_arm(q, arm['arm_index']):
            continue  # display rule: this arm doesn't see the question
        if reminders.question_part(survey, q) != part:
            continue  # the other part of a two-part survey
        arm_data = q['arm_texts'].get(arm['id'], {})
        q_payload = {
            'question_id': q['id'],
            'question_index': q['question_index'],
            'question_type': q['question_type'],
            'label': q.get('label', ''),
            'question_text': arm_data.get('question_text', ''),
            'options': arm_data.get('options', []),
            'allow_other': bool(arm_data.get('allow_other')) and q['question_type'] in ('multiple_choice', 'multiple_answer'),
        }
        if q.get('cond_question') is not None:
            # Shown only if the respondent answered that earlier question with one of these
            q_payload['condition'] = {'question_index': q['cond_question'], 'values': q.get('cond_values') or []}
        if arm_data.get('timer_seconds'):
            q_payload['timer'] = {'seconds': arm_data['timer_seconds'],
                                  'display': arm_data.get('timer_display') or 'both',
                                  'default': arm_data.get('timer_default') or ''}
        if q['question_type'] == 'slider':
            q_payload['slider_min'] = q.get('slider_min', 0) or 0
            q_payload['slider_max'] = q.get('slider_max', 100) or 100
            q_payload['slider_step'] = q.get('slider_step', 1) or 1
        image_fn = arm_data.get('image_filename')
        if image_fn:
            q_payload['image_url'] = '/uploads/' + image_fn
        payload['questions'].append(q_payload)

    return payload


def _get_aggregated_results(db, survey_id):
    """Get results for broadcasting to host, organized per question."""
    result = _get_survey_with_arms_and_questions(db, survey_id)
    if not result:
        return None

    survey, arms, questions = result

    # Batch-fetch ALL responses for this survey in one query
    all_responses = db.execute(
        'SELECT arm_id, question_id, answer_text, answer_index, other_text, timed_out FROM response WHERE survey_id=?',
        (survey_id,)
    ).fetchall()

    output = _aggregate_responses(survey, arms, questions, all_responses)

    # Participant count scoped to classroom
    classroom_id = survey['classroom_id']
    participant_count = db.execute(
        'SELECT COUNT(*) as cnt FROM participant WHERE classroom_id=?', (classroom_id,)
    ).fetchone()['cnt']
    output['participant_count'] = participant_count

    return output


def _aggregate_responses(survey, arms, questions, all_responses):
    """Turn response rows (arm_id, question_id, answer_text, answer_index) into the
    per-question chart/table payload the host dashboard renders."""
    survey_id = survey['id']

    # Index responses by (arm_id, question_id)
    responses_by_key = {}
    for r in all_responses:
        responses_by_key.setdefault((r['arm_id'], r['question_id']), []).append(r)

    output = {
        'survey_id': survey_id,
        'title': survey['title'],
        'group_number': survey['group_number'],
        'questions': [],
    }

    for q in questions:
        q_data = {
            'question_id': q['id'],
            'question_index': q['question_index'],
            'question_type': q['question_type'],
            'label': q.get('label', ''),
            'part': reminders.question_part(survey, q) if reminders.is_two_part(survey) else None,
            'arms': [],
            'total_responses': 0,
        }
        if q['question_type'] == 'slider':
            q_data['slider_min'] = q.get('slider_min', 0) or 0
            q_data['slider_max'] = q.get('slider_max', 100) or 100
            q_data['slider_step'] = q.get('slider_step', 1) or 1

        for arm in arms:
            arm_q_info = q['arm_texts'].get(arm['id'], {})
            arm_data = {
                'arm_id': arm['id'],
                'arm_index': arm['arm_index'],
                'label': arm['label'],
                'question_text': arm_q_info.get('question_text', ''),
            }
            if not rules.shown_in_arm(q, arm['arm_index']):
                arm_data['not_shown'] = True
            image_fn = arm_q_info.get('image_filename')
            if image_fn:
                arm_data['image_url'] = '/uploads/' + image_fn

            responses = responses_by_key.get((arm['id'], q['id']), [])
            q_data['total_responses'] += len(responses)

            if arm_q_info.get('timer_seconds'):
                arm_data['timer_seconds'] = arm_q_info['timer_seconds']
                arm_data['timed_out'] = sum(1 for r in responses if 'timed_out' in r.keys() and r['timed_out'])
                arm_data['respondents'] = len(responses)  # n can exclude blank timed-out answers
            if q['question_type'] in ('multiple_choice', 'multiple_answer'):
                # "Other" is counted like an option; what people typed is listed separately
                arm_data['other_texts'] = [r['other_text'] for r in responses
                                           if 'other_text' in r.keys() and r['other_text']]
            if q['question_type'] == 'multiple_choice':
                option_texts = list(arm_q_info.get('options', []))
                if arm_q_info.get('allow_other'):
                    option_texts.append(OTHER_LABEL)
                counts = {opt: 0 for opt in option_texts}
                for r in responses:
                    if r['answer_text'] in counts:
                        counts[r['answer_text']] += 1
                arm_data['options'] = option_texts
                arm_data['counts'] = counts
                arm_data['n'] = len(responses)
            elif q['question_type'] == 'multiple_answer':
                option_texts = list(arm_q_info.get('options', []))
                if arm_q_info.get('allow_other'):
                    option_texts.append(OTHER_LABEL)
                counts = {opt: 0 for opt in option_texts}
                for r in responses:
                    try:
                        selected = json.loads(r['answer_text'])
                        for s in selected:
                            if s in counts:
                                counts[s] += 1
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
                arm_data['options'] = option_texts
                arm_data['counts'] = counts
                arm_data['n'] = len(responses)
            elif q['question_type'] == 'short_answer':
                texts = [r['answer_text'] for r in responses if r['answer_text']]
                arm_data['responses'] = texts
                arm_data['n'] = len(texts)
            elif q['question_type'] == 'slider':
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
            else:
                # numeric
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

            q_data['arms'].append(arm_data)
        output['questions'].append(q_data)

    return output


def _is_fully_answered(db, participant_id, survey_id, part=1):
    """Has the student answered every question they were shown (in this part of a two-part survey)?

    With display rules a respondent sees only their arm's questions, and conditional
    questions only after the matching answer, so this replays the rules on their answers.
    """
    survey = db.execute('SELECT * FROM survey WHERE id=?', (survey_id,)).fetchone()
    if not survey:
        return False
    survey = dict(survey)
    responses = db.execute(
        'SELECT r.question_id, r.answer_text, sa.arm_index FROM response r '
        'JOIN survey_arm sa ON r.arm_id = sa.id WHERE r.participant_id=? AND r.survey_id=?',
        (participant_id, survey_id)).fetchall()
    if not responses:
        return False
    questions = []
    for row in db.execute('SELECT * FROM survey_question WHERE survey_id=? ORDER BY question_index', (survey_id,)):
        q = dict(row)
        q.update(rules.from_row(row))
        if reminders.question_part(survey, q) == part:
            questions.append(q)
    if not questions:
        return False
    index_of = {q['id']: q['question_index'] for q in questions}
    responses = [r for r in responses if r['question_id'] in index_of]
    if not responses:
        return False
    answers = {index_of[r['question_id']]: r['answer_text'] for r in responses if r['question_id'] in index_of}
    visible = rules.visible_questions(questions, responses[0]['arm_index'], answers)
    return all(q['question_index'] in answers for q in visible)


@socketio.on('join_student')
def handle_join_student(data):
    """Student connects to the session."""
    participant_id = data.get('participant_id')
    student_id = data.get('student_id')
    classroom_id = data.get('classroom_id')
    logger.info('join_student: participant=%s student_id=%s classroom=%s', participant_id, student_id, classroom_id)
    join_room(f'students_{classroom_id}')

    db = get_socket_db()
    try:
        active = db.execute(
            'SELECT * FROM survey WHERE is_active=1 AND classroom_id=?', (classroom_id,)
        ).fetchone()
        if active:
            if _is_fully_answered(db, participant_id, active['id']):
                logger.info('join_student: already answered survey=%s', active['id'])
                emit('already_answered', {'survey_id': active['id']})
            else:
                result = _get_survey_with_arms_and_questions(db, active['id'])
                if result:
                    survey, arms, questions = result
                    payload = _build_assignment_payload(survey, arms, questions, student_id)
                    logger.info('join_student: assignment survey=%s arm=%s questions=%d',
                                active['id'], payload['arm_id'], len(payload['questions']))
                    emit('assignment', payload)
                else:
                    logger.warning('join_student: no data for survey=%s', active['id'])
        else:
            logger.info('join_student: no active survey, waiting')
            emit('waiting', {})

        count = db.execute(
            'SELECT COUNT(*) as cnt FROM participant WHERE classroom_id=?', (classroom_id,)
        ).fetchone()['cnt']
        emit('participant_count', {'count': count}, room=f'host_{classroom_id}')
    finally:
        db.close()


@socketio.on('join_host')
def handle_join_host(data):
    """Host connects to the dashboard."""
    classroom_id = data.get('classroom_id')
    logger.info('join_host: classroom=%s', classroom_id)
    join_room(f'host_{classroom_id}')

    db = get_socket_db()
    try:
        count = db.execute(
            'SELECT COUNT(*) as cnt FROM participant WHERE classroom_id=?', (classroom_id,)
        ).fetchone()['cnt']
        emit('participant_count', {'count': count})

        active = db.execute(
            'SELECT * FROM survey WHERE is_active=1 AND classroom_id=?', (classroom_id,)
        ).fetchone()
        if active:
            results = _get_aggregated_results(db, active['id'])
            if results:
                logger.info('join_host: sending results for active survey=%s', active['id'])
                emit('results_update', results)
            else:
                logger.warning('join_host: no results for active survey=%s', active['id'])
        else:
            logger.info('join_host: no active survey')
    finally:
        db.close()


@socketio.on('activate_survey')
def handle_activate_survey(data):
    """Host activates a survey."""
    survey_id = data.get('survey_id')
    classroom_id = data.get('classroom_id')
    logger.info('activate_survey: survey=%s classroom=%s', survey_id, classroom_id)

    db = get_socket_db()
    try:
        db.execute('UPDATE survey SET is_active=0 WHERE is_active=1 AND classroom_id=?', (classroom_id,))
        db.execute('UPDATE survey SET is_active=1 WHERE id=?', (survey_id,))
        db.commit()

        result = _get_survey_with_arms_and_questions(db, survey_id)
        if not result:
            logger.warning('activate_survey: no data for survey=%s', survey_id)
            return
        survey, arms, questions = result

        emit('survey_activated', {
            'survey_id': survey_id,
            'group_number': survey['group_number'],
            'title': survey['title'],
        }, room=f'students_{classroom_id}')

        try:
            results = _get_aggregated_results(db, survey_id)
            logger.info('activate_survey: broadcasting results to host_%s', classroom_id)
            emit('results_update', results, room=f'host_{classroom_id}')
        except Exception as e:
            logger.error('activate_survey: aggregation failed for survey=%s: %s', survey_id, e)
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
        if _is_fully_answered(db, participant_id, survey_id):
            emit('already_answered', {'survey_id': survey_id})
            return

        result = _get_survey_with_arms_and_questions(db, survey_id)
        if not result:
            return
        survey, arms, questions = result
        payload = _build_assignment_payload(survey, arms, questions, student_id)
        emit('assignment', payload)
    finally:
        db.close()


@socketio.on('submit_answer')
def handle_submit_answer(data):
    """Student submits their answers (one per question)."""
    participant_id = data.get('participant_id')
    survey_id = data.get('survey_id')
    arm_id = data.get('arm_id')
    answers = data.get('answers', [])

    logger.info('submit_answer: participant=%s survey=%s arm=%s answers=%d',
                participant_id, survey_id, arm_id, len(answers))

    if not answers:
        logger.warning('submit_answer: empty answers from participant=%s', participant_id)
        emit('submit_error', {
            'survey_id': survey_id,
            'message': 'No answers were received. Please try submitting again.',
        })
        return {'ok': False, 'error': 'empty_answers'}

    db = get_socket_db()
    try:
        # Check if already fully answered
        if _is_fully_answered(db, participant_id, survey_id):
            logger.info('submit_answer: already answered participant=%s survey=%s', participant_id, survey_id)
            emit('already_answered', {'survey_id': survey_id})
            return {'ok': True, 'status': 'already_answered'}

        try:
            for answer in answers:
                db.execute(
                    'INSERT INTO response (participant_id, survey_id, arm_id, question_id, answer_text, answer_index) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (participant_id, survey_id, arm_id,
                     answer.get('question_id'), str(answer.get('answer_text', '')),
                     answer.get('answer_index')),
                )
            db.commit()
            logger.info('submit_answer: saved %d answers for participant=%s survey=%s',
                        len(answers), participant_id, survey_id)
            emit('answer_saved', {'survey_id': survey_id})
        except sqlite3.IntegrityError as e:
            logger.warning('submit_answer: duplicate/integrity failure participant=%s survey=%s: %s',
                           participant_id, survey_id, e)
            db.rollback()
            if _is_fully_answered(db, participant_id, survey_id):
                emit('already_answered', {'survey_id': survey_id})
                return {'ok': True, 'status': 'already_answered'}
            emit('submit_error', {
                'survey_id': survey_id,
                'message': 'Your answer was not saved. Please try again.',
            })
            return {'ok': False, 'error': 'integrity_error'}
        except Exception as e:
            logger.exception('submit_answer: INSERT failed participant=%s survey=%s', participant_id, survey_id)
            db.rollback()
            emit('submit_error', {
                'survey_id': survey_id,
                'message': 'Your answer was not saved. Please try again.',
            })
            return {'ok': False, 'error': 'insert_failed'}

        return {'ok': True, 'status': 'saved'}
    finally:
        db.close()


@socketio.on('next_survey')
def handle_next_survey(data):
    """Host advances to the next survey."""
    classroom_id = data.get('classroom_id')

    db = get_socket_db()
    try:
        current = db.execute(
            'SELECT * FROM survey WHERE is_active=1 AND classroom_id=?', (classroom_id,)
        ).fetchone()
        if current:
            next_row = db.execute(
                'SELECT id FROM survey WHERE group_number > ? AND classroom_id=? ORDER BY group_number LIMIT 1',
                (current['group_number'], classroom_id),
            ).fetchone()

            db.execute('UPDATE survey SET is_active=0 WHERE id=?', (current['id'],))
            db.commit()

            if next_row:
                db.execute('UPDATE survey SET is_active=1 WHERE id=?', (next_row['id'],))
                db.commit()

                result = _get_survey_with_arms_and_questions(db, next_row['id'])
                if result:
                    survey, arms, questions = result
                    emit('survey_activated', {
                        'survey_id': next_row['id'],
                        'group_number': survey['group_number'],
                        'title': survey['title'],
                    }, room=f'students_{classroom_id}')

                    results = _get_aggregated_results(db, next_row['id'])
                    emit('results_update', results, room=f'host_{classroom_id}')
                    emit('survey_changed', {'survey_id': next_row['id']}, room=f'host_{classroom_id}')
            else:
                emit('survey_deactivated', {}, room=f'students_{classroom_id}')
                emit('all_done', {}, room=f'host_{classroom_id}')
        else:
            first = db.execute(
                'SELECT id FROM survey WHERE classroom_id=? ORDER BY group_number LIMIT 1',
                (classroom_id,),
            ).fetchone()
            if first:
                handle_activate_survey({'survey_id': first['id'], 'classroom_id': classroom_id})
    finally:
        db.close()


@socketio.on('deactivate_all')
def handle_deactivate_all(data):
    """Host resets the session."""
    classroom_id = data.get('classroom_id')

    db = get_socket_db()
    try:
        db.execute('UPDATE survey SET is_active=0 WHERE is_active=1 AND classroom_id=?', (classroom_id,))
        db.commit()
        emit('survey_deactivated', {}, room=f'students_{classroom_id}')
        emit('session_reset', {}, room=f'host_{classroom_id}')
    finally:
        db.close()
