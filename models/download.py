import csv
import io

from models.db import get_db

OUTSIDE = '(run on another platform)'
OUTSIDE_ANSWERS = '(group ran this survey on another platform; answers not available here)'


def _external_surveys(db, classroom_id):
    """Surveys a group runs on another platform (e.g. Google Forms). The exports list them as
    placeholder rows so they aren't forgotten when grading."""
    return db.execute('SELECT * FROM survey WHERE classroom_id=? AND external=1 ORDER BY group_number',
                      (classroom_id,)).fetchall()


def export_all_responses_csv(classroom_id):
    """Export all responses for a classroom as a flat CSV. Returns a string."""
    db = get_db()
    rows = db.execute('''
        SELECT
            s.group_number,
            s.title AS survey_title,
            sq.question_index,
            sq.question_type,
            sq.label AS question_label,
            sa.label AS arm_label,
            aq.question_text AS arm_question,
            p.name AS participant_name,
            p.student_id AS participant_student_id,
            rs.anon_id AS respondent_id,
            r.answer_text,
            r.answer_index,
            r.answered_at
        FROM response r
        JOIN survey s ON r.survey_id = s.id
        JOIN survey_arm sa ON r.arm_id = sa.id
        JOIN participant p ON r.participant_id = p.id
        LEFT JOIN roster_student rs ON rs.classroom_id = s.classroom_id AND rs.sis_id = p.student_id
        LEFT JOIN survey_question sq ON r.question_id = sq.id
        LEFT JOIN arm_question aq ON aq.arm_id = sa.id AND aq.question_id = sq.id
        WHERE s.classroom_id = ?
        ORDER BY s.group_number, sq.question_index, sa.arm_index, r.answered_at
    ''', (classroom_id,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'group_number', 'survey_title', 'question_index', 'question_type', 'question_label',
        'arm_label', 'arm_question',
        'participant_name', 'participant_student_id', 'respondent_id',
        'answer_text', 'answer_index', 'answered_at'
    ])
    for row in rows:
        writer.writerow([
            row['group_number'], row['survey_title'],
            row['question_index'], row['question_type'], row['question_label'],
            row['arm_label'], row['arm_question'],
            row['participant_name'], row['participant_student_id'], row['respondent_id'],
            row['answer_text'], row['answer_index'], row['answered_at']
        ])
    for s in _external_surveys(db, classroom_id):
        writer.writerow([s['group_number'], s['title'], '', OUTSIDE, '', '', s['external_note'] or '',
                         '', '', '', OUTSIDE_ANSWERS, '', ''])

    return output.getvalue()


def export_surveys_config_csv(classroom_id):
    """Export survey configurations for a classroom as CSV."""
    db = get_db()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'group_number', 'survey_title',
        'question_index', 'question_type', 'question_label',
        'member_name', 'member_sis_code',
        'arm_index', 'arm_label', 'arm_question_text',
        'option_index', 'option_text'
    ])

    surveys = db.execute(
        'SELECT * FROM survey WHERE classroom_id=? ORDER BY group_number', (classroom_id,)
    ).fetchall()
    for survey in surveys:
        members = db.execute(
            'SELECT * FROM group_member WHERE survey_id=?', (survey['id'],)
        ).fetchall()
        arms = db.execute(
            'SELECT * FROM survey_arm WHERE survey_id=? ORDER BY arm_index', (survey['id'],)
        ).fetchall()
        questions = db.execute(
            'SELECT * FROM survey_question WHERE survey_id=? ORDER BY question_index', (survey['id'],)
        ).fetchall()

        for question in questions:
            for arm in arms:
                aq = db.execute(
                    'SELECT * FROM arm_question WHERE arm_id=? AND question_id=?',
                    (arm['id'], question['id'])
                ).fetchone()
                if not aq:
                    continue

                options = db.execute(
                    'SELECT * FROM arm_question_option WHERE arm_question_id=? ORDER BY option_index',
                    (aq['id'],)
                ).fetchall()

                if options:
                    for opt in options:
                        for member in members:
                            writer.writerow([
                                survey['group_number'], survey['title'],
                                question['question_index'], question['question_type'],
                                question['label'],
                                member['name'], member['sis_code'],
                                arm['arm_index'], arm['label'], aq['question_text'],
                                opt['option_index'], opt['option_text']
                            ])
                else:
                    for member in members:
                        writer.writerow([
                            survey['group_number'], survey['title'],
                            question['question_index'], question['question_type'],
                            question['label'],
                            member['name'], member['sis_code'],
                            arm['arm_index'], arm['label'], aq['question_text'],
                            '', ''
                        ])

    for survey in _external_surveys(db, classroom_id):
        members = db.execute('SELECT * FROM group_member WHERE survey_id=?', (survey['id'],)).fetchall()
        for member in members or [{'name': '', 'sis_code': ''}]:
            writer.writerow([survey['group_number'], survey['title'], '', OUTSIDE, '',
                             member['name'], member['sis_code'], '', '', survey['external_note'] or '', '', ''])

    return output.getvalue()


def export_participants_csv(classroom_id):
    """Export the class roster with each student's anonymized respondent ID (the key
    linking students' anonymized downloads back to names)."""
    db = get_db()
    rows = db.execute(
        'SELECT * FROM roster_student WHERE classroom_id=? ORDER BY full_name COLLATE NOCASE', (classroom_id,)
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'student_id', 'respondent_id', 'signed_up_at', 'removed'])
    for row in rows:
        writer.writerow([row['full_name'], row['sis_id'], row['anon_id'], row['registered_at'] or '',
                         'yes' if row['hidden'] else ''])

    return output.getvalue()


def export_survey_designers_csv(classroom_id):
    """Export which students designed each survey. One row per designer per survey."""
    db = get_db()
    rows = db.execute('''
        SELECT
            s.group_number,
            s.title AS survey_title,
            gm.name AS member_name,
            gm.sis_code AS member_sis_code,
            s.external
        FROM group_member gm
        JOIN survey s ON gm.survey_id = s.id
        WHERE s.classroom_id = ?
        ORDER BY s.group_number, gm.name
    ''', (classroom_id,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['group_number', 'survey_title', 'member_name', 'member_sis_code', 'runs'])
    for row in rows:
        writer.writerow([
            row['group_number'], row['survey_title'],
            row['member_name'], row['member_sis_code'],
            'another platform' if row['external'] else 'this site'
        ])

    return output.getvalue()


def export_survey_participation_csv(classroom_id):
    """Export which students participated in each survey. One row per student per survey."""
    db = get_db()
    rows = db.execute('''
        SELECT DISTINCT
            s.group_number,
            s.title AS survey_title,
            p.name AS participant_name,
            p.student_id AS participant_student_id,
            sa.label AS arm_label
        FROM response r
        JOIN survey s ON r.survey_id = s.id
        JOIN participant p ON r.participant_id = p.id
        JOIN survey_arm sa ON r.arm_id = sa.id
        WHERE s.classroom_id = ?
        ORDER BY s.group_number, p.name
    ''', (classroom_id,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['group_number', 'survey_title', 'participant_name', 'participant_student_id', 'arm_label'])
    for row in rows:
        writer.writerow([
            row['group_number'], row['survey_title'],
            row['participant_name'], row['participant_student_id'],
            row['arm_label']
        ])
    for s in _external_surveys(db, classroom_id):
        writer.writerow([s['group_number'], s['title'], OUTSIDE_ANSWERS, '', ''])

    return output.getvalue()


# --- Per-survey exports (filtered by survey_id AND classroom_id) ---

def export_survey_responses_csv(survey_id, classroom_id):
    """Export responses for a single survey as CSV."""
    db = get_db()
    rows = db.execute('''
        SELECT
            s.group_number,
            s.title AS survey_title,
            sq.question_index,
            sq.question_type,
            sq.label AS question_label,
            sa.label AS arm_label,
            aq.question_text AS arm_question,
            p.name AS participant_name,
            p.student_id AS participant_student_id,
            r.answer_text,
            r.answer_index,
            r.answered_at
        FROM response r
        JOIN survey s ON r.survey_id = s.id
        JOIN survey_arm sa ON r.arm_id = sa.id
        JOIN participant p ON r.participant_id = p.id
        LEFT JOIN survey_question sq ON r.question_id = sq.id
        LEFT JOIN arm_question aq ON aq.arm_id = sa.id AND aq.question_id = sq.id
        WHERE r.survey_id = ? AND s.classroom_id = ?
        ORDER BY sq.question_index, sa.arm_index, r.answered_at
    ''', (survey_id, classroom_id)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'group_number', 'survey_title', 'question_index', 'question_type', 'question_label',
        'arm_label', 'arm_question',
        'participant_name', 'participant_student_id',
        'answer_text', 'answer_index', 'answered_at'
    ])
    for row in rows:
        writer.writerow([
            row['group_number'], row['survey_title'],
            row['question_index'], row['question_type'], row['question_label'],
            row['arm_label'], row['arm_question'],
            row['participant_name'], row['participant_student_id'],
            row['answer_text'], row['answer_index'], row['answered_at']
        ])

    return output.getvalue()


def export_survey_responses_anon_csv(survey_id, classroom_id):
    """Anonymized responses for one survey, for the group's own analysis.

    Wide format: one row per respondent (identified only by their random roster
    anon_id), one column per question. Returns a string with a UTF-8 BOM so Excel
    shows accented characters correctly.
    """
    db = get_db()
    questions = db.execute(
        'SELECT sq.id, sq.question_index, sq.question_type, sq.label FROM survey_question sq '
        'JOIN survey s ON sq.survey_id = s.id WHERE sq.survey_id = ? AND s.classroom_id = ? '
        'ORDER BY sq.question_index', (survey_id, classroom_id)).fetchall()
    rows = db.execute('''
        SELECT r.participant_id, r.question_id, r.answer_text, sa.label AS arm_label, sa.arm_index,
               rs.anon_id
        FROM response r
        JOIN survey s ON r.survey_id = s.id
        JOIN survey_arm sa ON r.arm_id = sa.id
        JOIN participant p ON r.participant_id = p.id
        LEFT JOIN roster_student rs ON rs.classroom_id = s.classroom_id AND rs.sis_id = p.student_id
        WHERE r.survey_id = ? AND s.classroom_id = ?
    ''', (survey_id, classroom_id)).fetchall()

    respondents = {}
    for r in rows:
        resp = respondents.setdefault(r['participant_id'], {
            'id': r['anon_id'] or f'P-{r["participant_id"]}',
            'arm': r['arm_label'], 'arm_index': r['arm_index'], 'answers': {}})
        resp['answers'][r['question_id']] = r['answer_text']

    output = io.StringIO()
    writer = csv.writer(output)
    headers = ['respondent_id', 'arm']
    for q in questions:
        name = f'Q{q["question_index"] + 1}'
        if q['label']:
            name += f' {q["label"]}'
        headers.append(f'{name} ({q["question_type"]})')
    writer.writerow(headers)
    for resp in sorted(respondents.values(), key=lambda x: (x['arm_index'], x['id'])):
        writer.writerow([resp['id'], resp['arm']] + [resp['answers'].get(q['id'], '') for q in questions])

    return '﻿' + output.getvalue()


def export_single_survey_config_csv(survey_id, classroom_id):
    """Export configuration for a single survey as CSV."""
    db = get_db()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'group_number', 'survey_title',
        'question_index', 'question_type', 'question_label',
        'member_name', 'member_sis_code',
        'arm_index', 'arm_label', 'arm_question_text',
        'option_index', 'option_text'
    ])

    survey = db.execute(
        'SELECT * FROM survey WHERE id=? AND classroom_id=?', (survey_id, classroom_id)
    ).fetchone()
    if not survey:
        return output.getvalue()

    members = db.execute(
        'SELECT * FROM group_member WHERE survey_id=?', (survey['id'],)
    ).fetchall()
    arms = db.execute(
        'SELECT * FROM survey_arm WHERE survey_id=? ORDER BY arm_index', (survey['id'],)
    ).fetchall()
    questions = db.execute(
        'SELECT * FROM survey_question WHERE survey_id=? ORDER BY question_index', (survey['id'],)
    ).fetchall()

    for question in questions:
        for arm in arms:
            aq = db.execute(
                'SELECT * FROM arm_question WHERE arm_id=? AND question_id=?',
                (arm['id'], question['id'])
            ).fetchone()
            if not aq:
                continue

            options = db.execute(
                'SELECT * FROM arm_question_option WHERE arm_question_id=? ORDER BY option_index',
                (aq['id'],)
            ).fetchall()

            if options:
                for opt in options:
                    for member in members:
                        writer.writerow([
                            survey['group_number'], survey['title'],
                            question['question_index'], question['question_type'],
                            question['label'],
                            member['name'], member['sis_code'],
                            arm['arm_index'], arm['label'], aq['question_text'],
                            opt['option_index'], opt['option_text']
                        ])
            else:
                for member in members:
                    writer.writerow([
                        survey['group_number'], survey['title'],
                        question['question_index'], question['question_type'],
                        question['label'],
                        member['name'], member['sis_code'],
                        arm['arm_index'], arm['label'], aq['question_text'],
                        '', ''
                    ])

    return output.getvalue()


def export_single_survey_designers_csv(survey_id, classroom_id):
    """Export designers for a single survey. One row per designer."""
    db = get_db()
    rows = db.execute('''
        SELECT
            s.group_number,
            s.title AS survey_title,
            gm.name AS member_name,
            gm.sis_code AS member_sis_code,
            s.external
        FROM group_member gm
        JOIN survey s ON gm.survey_id = s.id
        WHERE gm.survey_id = ? AND s.classroom_id = ?
        ORDER BY gm.name
    ''', (survey_id, classroom_id)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['group_number', 'survey_title', 'member_name', 'member_sis_code', 'runs'])
    for row in rows:
        writer.writerow([
            row['group_number'], row['survey_title'],
            row['member_name'], row['member_sis_code'],
            'another platform' if row['external'] else 'this site'
        ])

    return output.getvalue()


def export_single_survey_participation_csv(survey_id, classroom_id):
    """Export participation for a single survey. One row per student who answered."""
    db = get_db()
    rows = db.execute('''
        SELECT DISTINCT
            s.group_number,
            s.title AS survey_title,
            p.name AS participant_name,
            p.student_id AS participant_student_id,
            sa.label AS arm_label
        FROM response r
        JOIN survey s ON r.survey_id = s.id
        JOIN participant p ON r.participant_id = p.id
        JOIN survey_arm sa ON r.arm_id = sa.id
        WHERE r.survey_id = ? AND s.classroom_id = ?
        ORDER BY p.name
    ''', (survey_id, classroom_id)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['group_number', 'survey_title', 'participant_name', 'participant_student_id', 'arm_label'])
    for row in rows:
        writer.writerow([
            row['group_number'], row['survey_title'],
            row['participant_name'], row['participant_student_id'],
            row['arm_label']
        ])

    return output.getvalue()


# --- Peer feedback exports (host only) ---

def _feedback_rows(classroom):
    from models.feedback import student_feedback
    db = get_db()
    students = db.execute('SELECT * FROM roster_student WHERE classroom_id=? ORDER BY full_name COLLATE NOCASE',
                          (classroom['id'],)).fetchall()
    for s in students:
        yield s, student_feedback(classroom, s['id'])


def export_feedback_csv(classroom):
    """One row per comment (sent or draft), plus a row for each required comment not started."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['reviewer_name', 'reviewer_student_id', 'group_number', 'survey_title', 'required',
                     'status', 'sent_at', 'last_edited', 'comment'])
    for s, cards in _feedback_rows(classroom):
        for c in cards:
            if c['sent_at']:
                status = 'sent'
            elif c['body']:
                status = 'draft (not sent)'
            else:
                status = 'not started'
            if not c['required'] and status == 'not started':
                continue
            writer.writerow([s['full_name'], s['sis_id'], c['group_number'], c['title'],
                             'yes' if c['required'] else 'no', status, c['sent_at'] or '',
                             c['updated_at'] or '', c['body'] or ''])
    return '\ufeff' + output.getvalue()


def export_feedback_summary_csv(classroom):
    """One row per student: required comments sent out of required, and extra comments sent."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'student_id', 'required', 'required_sent', 'extra_sent', 'all_required_sent', 'removed'])
    for s, cards in _feedback_rows(classroom):
        required = [c for c in cards if c['required']]
        sent_required = sum(1 for c in required if c['sent_at'])
        extra_sent = sum(1 for c in cards if not c['required'] and c['sent_at'])
        writer.writerow([s['full_name'], s['sis_id'], len(required), sent_required, extra_sent,
                         'yes' if required and sent_required == len(required) else 'no',
                         'yes' if s['hidden'] else ''])
    return '\ufeff' + output.getvalue()
