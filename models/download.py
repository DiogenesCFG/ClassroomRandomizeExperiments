import csv
import io

from models.db import get_db


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
            r.answer_text,
            r.answer_index,
            r.answered_at
        FROM response r
        JOIN survey s ON r.survey_id = s.id
        JOIN survey_arm sa ON r.arm_id = sa.id
        JOIN participant p ON r.participant_id = p.id
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

    return output.getvalue()


def export_participants_csv(classroom_id):
    """Export all participants for a classroom as CSV."""
    db = get_db()
    rows = db.execute(
        'SELECT * FROM participant WHERE classroom_id=? ORDER BY name', (classroom_id,)
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'student_id', 'logged_in_at'])
    for row in rows:
        writer.writerow([row['name'], row['student_id'], row['logged_in_at']])

    return output.getvalue()
