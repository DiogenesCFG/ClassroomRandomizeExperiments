"""The student mock-up: a hidden practice copy of a class, for the instructor to explore (and show) what students see.

It's its own classroom (classroom.sandbox_of = the real class), so nothing done in it can touch the real class:
separate roster, groups, surveys, comments and data. It holds made-up students, groups (one of them the instructor's,
as "Demo Student (you)"), a one-question survey to build on, classmates in the group finder, assigned comments with
lorem-ipsum comments received, and a pending invite. Nobody can join it (random passwords; the join pages refuse it).
It stays as the instructor leaves it; "Reset" rebuilds it from scratch.
"""
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

from models.db import get_db

DEMO_SIS = 'MOCK-YOU'
FAKE_NAMES = ['Chen, Avery', 'Patel, Jordan', 'Garcia, Sofia', 'Nguyen, Liam', 'Johnson, Maya', 'Kim, Ethan', 'Lopez, Ana',
              'Brown, Noah', 'Singh, Priya', 'Davis, Lucas', 'Martinez, Elena', 'Wilson, Mateo', 'Taylor, Zoe', 'Ali, Omar']
LOREM = ['Lorem ipsum dolor sit amet, consectetur adipiscing elit. The treatment is clear, but how will you tell it apart from a simple wording effect?',
         'Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Consider adding a question that checks whether people noticed the anchor.',
         'Ut enim ad minim veniam, quis nostrud exercitation. A larger difference between the arms might make the effect easier to see.',
         'Duis aute irure dolor in reprehenderit in voluptate velit esse. Nice idea; the hypothesis could be stated more precisely.']


def sandbox_of(classroom):
    """The real class's mock-up classroom, or None."""
    row = get_db().execute('SELECT * FROM classroom WHERE sandbox_of=?', (classroom['id'],)).fetchone()
    return dict(row) if row else None


def is_sandbox(classroom):
    return bool(classroom and classroom.get('sandbox_of'))


def demo_student(sandbox):
    row = get_db().execute('SELECT * FROM roster_student WHERE classroom_id=? AND sis_id=?', (sandbox['id'], DEMO_SIS)).fetchone()
    return dict(row) if row else None


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _design(arm_labels, qtype, label, texts, options=None, config=None):
    arms = [{'label': a} for a in arm_labels]
    q = {'question_type': qtype, 'label': label,
         'arms': {i: {'question_text': t, 'options': list(options or []), 'config': dict(config or {})} for i, t in enumerate(texts)}}
    return arms, [q]


def build(real):
    """Create the mock-up for this class (call delete() first to rebuild). Returns the mock-up classroom."""
    from models.classroom import create_classroom
    from models.survey import create_survey
    from models import feedback as fb
    db = get_db()
    code = f'{real["code"]}-MOCKUP'
    n = 2
    while db.execute('SELECT 1 FROM classroom WHERE code=?', (code.upper(),)).fetchone():
        code = f'{real["code"]}-MOCKUP{n}'
        n += 1
    mock = create_classroom(code, f'{real["name"]} (student mock-up)', secrets.token_urlsafe(24), secrets.token_urlsafe(24),
                            real['max_groups_per_student'])
    now = datetime.now(timezone.utc)
    # The class's own settings, so the mock-up looks like what students see; both comment rounds on: presentations
    # closed (comments received are shown), surveys open (comments can be written)
    db.execute('''UPDATE classroom SET sandbox_of=?, max_group_size=?, max_questions_per_survey=?, reviews_required=?,
                  fb_sketch_instructions=?, fb_survey_instructions=?, show_order=?,
                  fb_sketch_on=1, fb_sketch_open_at=?, fb_sketch_close_at=?,
                  fb_survey_on=1, fb_survey_open_at=?, fb_survey_close_at=? WHERE id=?''',
               (real['id'], real['max_group_size'], real['max_questions_per_survey'], real['reviews_required'] or 2,
                real['fb_sketch_instructions'], real['fb_survey_instructions'], real['show_order'],
                _iso(now - timedelta(days=3)), _iso(now - timedelta(days=1)), _iso(now - timedelta(hours=1)),
                _iso(now + timedelta(days=7)), mock['id']))
    from models.roster import new_anon_id
    hashed = generate_password_hash(secrets.token_urlsafe(16))
    ids = {}
    for i, name in enumerate(['Student, Demo (you)'] + FAKE_NAMES):
        sis = DEMO_SIS if i == 0 else f'MOCK-{i:03d}'
        last, first = [p.strip() for p in name.split(',', 1)]
        cur = db.execute("INSERT INTO roster_student (classroom_id, sis_id, full_name, first_name, last_name, anon_id, "
                         "password_hash, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                         (mock['id'], sis, name, first, last, new_anon_id(db), hashed))
        ids[sis] = (cur.lastrowid, name, sis)
    db.commit()

    def member(sis):
        rid, name, code_ = ids[sis]
        return {'name': name, 'sis_code': code_, 'roster_student_id': rid}

    groups = [
        # (members, title, design)
        ([DEMO_SIS, 'MOCK-001', 'MOCK-002'], 'Price anchors and a coffee mug',
         _design(['Control', 'High anchor'], 'multiple_choice', 'Buy the mug',
                 ['Would you buy this coffee mug for $8?', 'Most people pay $25 for this mug. Would you buy it for $8?'], ['Yes', 'No'])),
        (['MOCK-003', 'MOCK-004', 'MOCK-005'], 'Default options and savings',
         _design(['Opt in', 'Opt out'], 'numeric', 'Savings', ['How much of a $1,000 bonus would you save?'] * 2)),
        (['MOCK-006', 'MOCK-007'], 'Framing a medical choice',
         _design(['Lives saved', 'Lives lost'], 'multiple_choice', 'Program',
                 ['Program A saves 200 of 600 people. Choose A or B.', 'With program A, 400 of 600 people die. Choose A or B.'],
                 ['Program A', 'Program B'])),
        (['MOCK-008', 'MOCK-009'], 'Social norms and recycling',
         _design(['Control', 'Norm'], 'rating', 'Recycling', ['How likely are you to recycle this week?',
                                                               'Most students in this class recycle. How likely are you to recycle this week?'],
                 config={'labels': ['Very unlikely', '', '', '', 'Very likely']})),
    ]
    survey_ids = []
    for number, (members, title, (arms, questions)) in enumerate(groups, start=1):
        sid = create_survey(mock['id'], title, number, arms, questions, [member(s) for s in members])
        survey_ids.append(sid)
    # Groups 2 and 3 already ran in class (classmates can view them and comment on them)
    db.execute(f"UPDATE survey SET went_live=1, part1_ran=datetime('now') WHERE id IN ({survey_ids[1]}, {survey_ids[2]})")
    # Group 4 has room and is looking for members; three classmates are looking for a group
    db.execute("UPDATE survey SET seeking_members=1, seeking_note='Looking for one more: we like environmental topics.' WHERE id=?",
               (survey_ids[3],))
    for sis, note in (('MOCK-010', 'Interested in loss aversion.'), ('MOCK-011', 'Happy to join any group.'), ('MOCK-012', '')):
        db.execute('UPDATE roster_student SET seeking_group=1, seeking_note=? WHERE id=?', (note or None, ids[sis][0]))
    # A pending invite to the demo student
    db.execute('INSERT INTO team_invite (survey_id, roster_student_id, invited_by) VALUES (?, ?, ?)',
               (survey_ids[3], ids[DEMO_SIS][0], ids['MOCK-008'][0]))
    db.commit()

    fresh = dict(db.execute('SELECT * FROM classroom WHERE id=?', (mock['id'],)).fetchone())
    fb.ensure_assignments(fresh)
    # Comments received on the demo group's presentation (that round is closed, so the group reads them), and the
    # demo student's own sent comment on one of their groups
    k = 0
    for r in db.execute('SELECT roster_student_id FROM review_assignment WHERE survey_id=?', (survey_ids[0],)).fetchall():
        db.execute("INSERT INTO feedback (survey_id, roster_student_id, body, sent_at, round) VALUES (?, ?, ?, datetime('now', '-2 days'), 'sketch')",
                   (survey_ids[0], r['roster_student_id'], LOREM[k % len(LOREM)]))
        k += 1
    first = db.execute('SELECT survey_id FROM review_assignment WHERE roster_student_id=? ORDER BY id LIMIT 1',
                       (ids[DEMO_SIS][0],)).fetchone()
    if first:
        db.execute("INSERT INTO feedback (survey_id, roster_student_id, body, sent_at, round) VALUES (?, ?, ?, datetime('now', '-2 days'), 'sketch')",
                   (first['survey_id'], ids[DEMO_SIS][0], LOREM[1]))
    db.commit()
    return fresh


def delete(mock):
    """Delete a mock-up classroom and its uploaded pictures."""
    from models.classroom import delete_classroom
    from models.survey import survey_images
    db = get_db()
    files = []
    for s in db.execute('SELECT id FROM survey WHERE classroom_id=?', (mock['id'],)).fetchall():
        files += survey_images(db, s['id'])
    files += delete_classroom(mock['id'])
    return sorted(set(files))
