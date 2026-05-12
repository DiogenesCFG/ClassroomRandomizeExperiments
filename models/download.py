import csv
import io

from models.db import get_db


def export_all_responses_csv():
    """Export all responses as a flat CSV. Returns a string."""
    db = get_db()
    rows = db.execute('''
        SELECT
            s.group_number,
            s.title AS survey_title,
            s.question_type,
            sa.label AS arm_label,
            sa.question_text AS arm_question,
            p.name AS participant_name,
            p.student_id AS participant_student_id,
            r.answer_text,
            r.answer_index,
            r.answered_at
        FROM response r
        JOIN survey s ON r.survey_id = s.id
        JOIN survey_arm sa ON r.arm_id = sa.id
        JOIN participant p ON r.participant_id = p.id
        ORDER BY s.group_number, sa.arm_index, r.answered_at
    ''').fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'group_number', 'survey_title', 'question_type',
        'arm_label', 'arm_question',
        'participant_name', 'participant_student_id',
        'answer_text', 'answer_index', 'answered_at'
    ])
    for row in rows:
        writer.writerow([
            row['group_number'], row['survey_title'], row['question_type'],
            row['arm_label'], row['arm_question'],
            row['participant_name'], row['participant_student_id'],
            row['answer_text'], row['answer_index'], row['answered_at']
        ])

    return output.getvalue()


def export_surveys_config_csv():
    """Export survey configurations (groups, members, arms, options) as CSV."""
    db = get_db()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'group_number', 'survey_title', 'question_type',
        'member_name', 'member_sis_code',
        'arm_index', 'arm_label', 'arm_question_text',
        'option_index', 'option_text'
    ])

    surveys = db.execute('SELECT * FROM survey ORDER BY group_number').fetchall()
    for survey in surveys:
        members = db.execute(
            'SELECT * FROM group_member WHERE survey_id=?', (survey['id'],)
        ).fetchall()
        arms = db.execute(
            'SELECT * FROM survey_arm WHERE survey_id=? ORDER BY arm_index', (survey['id'],)
        ).fetchall()

        # Write one row per (member x arm x option) combination
        # If no options (numeric), just write arm info
        for arm in arms:
            options = db.execute(
                'SELECT * FROM arm_option WHERE arm_id=? ORDER BY option_index', (arm['id'],)
            ).fetchall()

            if options:
                for opt in options:
                    for member in members:
                        writer.writerow([
                            survey['group_number'], survey['title'], survey['question_type'],
                            member['name'], member['sis_code'],
                            arm['arm_index'], arm['label'], arm['question_text'],
                            opt['option_index'], opt['option_text']
                        ])
            else:
                for member in members:
                    writer.writerow([
                        survey['group_number'], survey['title'], survey['question_type'],
                        member['name'], member['sis_code'],
                        arm['arm_index'], arm['label'], arm['question_text'],
                        '', ''
                    ])

    return output.getvalue()


def export_participants_csv():
    """Export all participants as CSV."""
    db = get_db()
    rows = db.execute('SELECT * FROM participant ORDER BY name').fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'student_id', 'logged_in_at'])
    for row in rows:
        writer.writerow([row['name'], row['student_id'], row['logged_in_at']])

    return output.getvalue()
