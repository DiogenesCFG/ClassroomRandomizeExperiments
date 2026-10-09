import csv
import io
import json

from models.db import get_db

OUTSIDE = '(run on another platform)'
OUTSIDE_ANSWERS = '(group ran this survey on another platform; answers not available here)'


def _seconds(value):
    """Time on a question for a CSV cell ('' when not recorded, e.g. answers from before timing)."""
    return '' if value is None else value


def _yes(value):
    return 'yes' if value else ''


def _with_other(answer_text, other_text):
    """An answer for the anonymized download, with "Other" replaced by "Other: <what they typed>"."""
    if not other_text:
        return answer_text
    if answer_text == 'Other':
        return f'Other: {other_text}'
    try:
        chosen = json.loads(answer_text)
    except (TypeError, ValueError):
        return answer_text
    if isinstance(chosen, list):
        return json.dumps([f'Other: {other_text}' if c == 'Other' else c for c in chosen], ensure_ascii=False)
    return answer_text


def _options_with_other(db, aq):
    """An arm-question's options as dicts, plus an "Other" entry when it allows a typed answer."""
    options = [dict(o) for o in db.execute(
        'SELECT * FROM arm_question_option WHERE arm_question_id=? ORDER BY option_index', (aq['id'],))]
    if aq['allow_other']:
        options.append({'option_index': len(options), 'option_text': 'Other (respondent types their answer)'})
    return options


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
            r.other_text,
            r.seconds,
            r.left_page,
            r.timed_out,
            CASE WHEN s.part2_from IS NOT NULL AND s.external = 0 AND sq.question_index >= s.part2_from THEN 2 ELSE 1 END AS part,
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
        'answer_text', 'answer_index', 'other_text', 'seconds', 'left_page', 'timed_out', 'answered_at', 'part'
    ])
    for row in rows:
        writer.writerow([
            row['group_number'], row['survey_title'],
            row['question_index'], row['question_type'], row['question_label'],
            row['arm_label'], row['arm_question'],
            row['participant_name'], row['participant_student_id'], row['respondent_id'],
            row['answer_text'], row['answer_index'], row['other_text'] or '',
            _seconds(row['seconds']), _yes(row['left_page']), _yes(row['timed_out']), row['answered_at'], row['part']
        ])
    for s in _external_surveys(db, classroom_id):
        writer.writerow([s['group_number'], s['title'], '', OUTSIDE, '', '', s['external_note'] or '',
                         '', '', '', OUTSIDE_ANSWERS, '', '', '', '', '', '', ''])

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

                options = _options_with_other(db, aq)

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
            r.other_text,
            r.seconds,
            r.left_page,
            r.timed_out,
            CASE WHEN s.part2_from IS NOT NULL AND s.external = 0 AND sq.question_index >= s.part2_from THEN 2 ELSE 1 END AS part,
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
        'answer_text', 'answer_index', 'other_text', 'seconds', 'left_page', 'timed_out', 'answered_at', 'part'
    ])
    for row in rows:
        writer.writerow([
            row['group_number'], row['survey_title'],
            row['question_index'], row['question_type'], row['question_label'],
            row['arm_label'], row['arm_question'],
            row['participant_name'], row['participant_student_id'],
            row['answer_text'], row['answer_index'], row['other_text'] or '',
            _seconds(row['seconds']), _yes(row['left_page']), _yes(row['timed_out']), row['answered_at'], row['part']
        ])

    return output.getvalue()


def export_survey_responses_anon_csv(survey_id, classroom_id, long=False):
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
        SELECT r.participant_id, r.question_id, r.answer_text, r.other_text, r.seconds, r.left_page, r.timed_out,
               r.answered_at, sa.label AS arm_label, sa.arm_index, rs.anon_id
        FROM response r
        JOIN survey s ON r.survey_id = s.id
        JOIN survey_arm sa ON r.arm_id = sa.id
        JOIN participant p ON r.participant_id = p.id
        LEFT JOIN roster_student rs ON rs.classroom_id = s.classroom_id AND rs.sis_id = p.student_id
        WHERE r.survey_id = ? AND s.classroom_id = ?
    ''', (survey_id, classroom_id)).fetchall()

    survey = db.execute('SELECT * FROM survey WHERE id=?', (survey_id,)).fetchone()
    if long:
        return anon_responses_long_csv(questions, rows, part2_from=survey['part2_from'] if survey else None)
    actions = None
    if survey and (survey['reminder_plan'] or survey['part2_from'] is not None):
        from models.reminders import actions_by_participant
        actions = actions_by_participant(survey_id)
    return anon_responses_csv(questions, rows, part2_from=survey['part2_from'] if survey else None,
                              reminder_actions=actions)


def anon_responses_csv(questions, rows, part2_from=None, reminder_actions=None):
    """Write the anonymized wide CSV. questions: dicts/rows with id, question_index, question_type,
    label. rows: one per answer with participant_id, question_id, answer_text, other_text, seconds,
    left_page, timed_out, arm_label, arm_index, anon_id. Also used for the dashboard preview's
    example file, so students see exactly the format of their real data.

    part2_from marks part-2 questions in the headers; reminder_actions ({participant_id: ...} from
    models.reminders.actions_by_participant) adds what each respondent did with their calendar reminders."""
    respondents = {}
    for r in rows:
        resp = respondents.setdefault(r['participant_id'], {
            'id': r['anon_id'] or f'P-{r["participant_id"]}',
            'arm': r['arm_label'], 'arm_index': r['arm_index'], 'answers': {}, 'seconds': {}, 'left': {}, 'timed_out': {}})
        resp['answers'][r['question_id']] = _with_other(r['answer_text'], r['other_text'])
        resp['seconds'][r['question_id']] = _seconds(r['seconds'])
        resp['left'][r['question_id']] = _yes(r['left_page'])
        resp['timed_out'][r['question_id']] = _yes(r['timed_out'])

    output = io.StringIO()
    writer = csv.writer(output)
    headers = ['respondent_id', 'arm']
    for q in questions:
        name = f'Q{q["question_index"] + 1}'
        if q['label']:
            name += f' {q["label"]}'
        part = ', part 2' if part2_from is not None and q['question_index'] >= part2_from else ''
        headers.append(f'{name} ({q["question_type"]}{part})')
    # Time on each question, whether they switched to another app/tab while on it,
    # and whether its timer ran out (the group's default answer was recorded)
    for q in questions:
        n = q['question_index'] + 1
        headers += [f'Q{n} seconds', f'Q{n} left page', f'Q{n} timed out']
    if reminder_actions is not None:
        # The calendar step after answering: when they downloaded the .ics file, how many
        # Google Calendar links they opened, and whether they said "Done" (self-reported)
        headers += ['reminders file downloaded', 'reminders Google links opened', 'reminders said added',
                    'reminders notifications on', 'reminders notifications delivered', 'reminders notifications opened']
    writer.writerow(headers)
    for pid, resp in sorted(respondents.items(), key=lambda x: (x[1]['arm_index'], x[1]['id'])):
        row = [resp['id'], resp['arm']] + [resp['answers'].get(q['id'], '') for q in questions]
        for q in questions:
            row += [resp['seconds'].get(q['id'], ''), resp['left'].get(q['id'], ''), resp['timed_out'].get(q['id'], '')]
        if reminder_actions is not None:
            a = reminder_actions.get(pid) or {'ics': None, 'google': set(), 'done': None, 'push': None,
                                              'push_sent': 0, 'push_opened': 0}
            row += [a['ics'] or '', len(a['google']), a['done'] or '', a['push'] or '', a['push_sent'], a['push_opened']]
        writer.writerow(row)

    return '﻿' + output.getvalue()


def anon_responses_long_csv(questions, rows, part2_from=None):
    """The same answers as anon_responses_csv, in long format: one row per respondent and question
    (handy for regressions with question or part fixed effects, or for pivoting yourself)."""
    by_id = {q['id']: q for q in questions}
    order = {q['id']: q['question_index'] for q in questions}
    out_rows = []
    for r in rows:
        q = by_id.get(r['question_id'])
        if not q:
            continue
        keys = r.keys() if hasattr(r, 'keys') else r
        out_rows.append([r['anon_id'] or f'P-{r["participant_id"]}', r['arm_label'],
                         2 if part2_from is not None and q['question_index'] >= part2_from else 1,
                         q['question_index'] + 1, q['label'] or '', q['question_type'],
                         _with_other(r['answer_text'], r['other_text']),
                         _seconds(r['seconds']), _yes(r['left_page']), _yes(r['timed_out']),
                         r['answered_at'] if 'answered_at' in keys and r['answered_at'] else '',
                         (r['arm_index'], order[r['question_id']])])
    out_rows.sort(key=lambda x: (x[-1][0], x[0], x[-1][1]))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['respondent_id', 'arm', 'part', 'question', 'question_label', 'question_type', 'answer',
                     'seconds', 'left_page', 'timed_out', 'answered_at'])
    for row in out_rows:
        writer.writerow(row[:-1])
    return '\ufeff' + output.getvalue()


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

            options = _options_with_other(db, aq)

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

def export_reminder_actions_csv(classroom_id):
    """Every calendar-reminder action: .ics downloads, Google Calendar links opened, and "Done"."""
    db = get_db()
    rows = db.execute('''
        SELECT s.group_number, s.title AS survey_title, sa.label AS arm_label, p.name AS participant_name,
               p.student_id AS participant_student_id, rs.anon_id AS respondent_id,
               ra.method, ra.item, ra.device, ra.created_at
        FROM reminder_action ra
        JOIN survey s ON ra.survey_id = s.id
        JOIN participant p ON ra.participant_id = p.id
        LEFT JOIN survey_arm sa ON sa.survey_id = s.id AND sa.arm_index = ra.arm_index
        LEFT JOIN roster_student rs ON rs.classroom_id = s.classroom_id AND rs.sis_id = p.student_id
        WHERE s.classroom_id = ?
        ORDER BY s.group_number, ra.created_at, ra.id
    ''', (classroom_id,)).fetchall()
    names = {'ics': 'downloaded calendar file', 'google': 'opened Google Calendar link', 'done': 'said added',
             'push': 'turned notifications on', 'push_off': 'turned notifications off'}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['group_number', 'survey_title', 'arm_label', 'participant_name', 'participant_student_id',
                     'respondent_id', 'action', 'reminder', 'device', 'time_utc'])
    for r in rows:
        from models.reminders import item_label
        item = item_label(r['item']) if r['item'] else ''
        writer.writerow([r['group_number'], r['survey_title'], r['arm_label'] or '', r['participant_name'],
                         r['participant_student_id'], r['respondent_id'] or '', names.get(r['method'], r['method']),
                         item, r['device'] or '', r['created_at']])
    return output.getvalue()


def export_push_messages_csv(classroom_id):
    """Every reminder notification: when it was due, whether it was delivered, and if it was tapped."""
    rows = get_db().execute('''
        SELECT s.group_number, s.title AS survey_title, sa.label AS arm_label, p.name AS participant_name,
               p.student_id AS participant_student_id, rs.anon_id AS respondent_id,
               pm.item, pm.title, pm.send_at, pm.status, pm.sent_at, pm.clicked_at, ps.tz
        FROM push_message pm
        JOIN push_subscription ps ON pm.subscription_id = ps.id
        JOIN survey s ON ps.survey_id = s.id
        JOIN participant p ON ps.participant_id = p.id
        LEFT JOIN survey_arm sa ON sa.survey_id = s.id AND sa.arm_index = ps.arm_index
        LEFT JOIN roster_student rs ON rs.classroom_id = s.classroom_id AND rs.sis_id = p.student_id
        WHERE s.classroom_id = ?
        ORDER BY s.group_number, pm.send_at, pm.id
    ''', (classroom_id,)).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['group_number', 'survey_title', 'arm_label', 'participant_name', 'participant_student_id',
                     'respondent_id', 'reminder', 'message', 'due_utc', 'status', 'sent_utc', 'tapped_utc', 'phone_time_zone'])
    for r in rows:
        from models.reminders import item_label
        item = item_label(r['item'])
        writer.writerow([r['group_number'], r['survey_title'], r['arm_label'] or '', r['participant_name'],
                         r['participant_student_id'], r['respondent_id'] or '', item, r['title'], r['send_at'],
                         r['status'], r['sent_at'] or '', r['clicked_at'] or '', r['tz'] or ''])
    return output.getvalue()


def export_reminder_plans_csv(classroom_id):
    """Each group's notifications per arm, and how its parts run, as approved or not."""
    from models import reminders
    from models.survey import get_survey
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['group_number', 'survey_title', 'arm_label', 'note', 'notification', 'message', 'time', 'days',
                     'count', 'time_zone', 'part1', 'part2', 'approval'])
    for s in get_db().execute('SELECT id FROM survey WHERE classroom_id=? AND external=0 AND '
                              '(reminder_plan IS NOT NULL OR part2_from IS NOT NULL) ORDER BY group_number',
                              (classroom_id,)).fetchall():
        survey = get_survey(s['id'])
        plan = reminders.load_plan(survey)
        state = reminders.approval_state(survey)
        from routes.reminders import parts_text
        parts = parts_text(survey) if reminders.is_two_part(survey) else {1: 'one-part survey', 2: ''}
        tail = [plan['tz'] or 'none (phone time)', parts[1], parts[2], state]
        for ai, arm in enumerate(survey['arms']):
            arm_plan = plan['arms'][ai] if ai < len(plan['arms']) else {'note': '', 'rules': []}
            for ri, rule in enumerate(arm_plan['rules'] or [None]):
                if rule:
                    days = rule['dates']
                    cells = [ri + 1, rule['message'], rule['time'], ' '.join(days), len(days)]
                else:
                    cells = ['', '', '', '', 0]
                writer.writerow([survey['group_number'], survey['title'], arm['label'], arm_plan['note']] + cells + tail)
    return output.getvalue()


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
