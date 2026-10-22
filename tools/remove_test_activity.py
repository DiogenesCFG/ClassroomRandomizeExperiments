"""Undo what a test sign-in as a student did (e.g. the instructor checking the site as a student).

Usage (on Render: Shell tab, from the project folder):
    PUSH_SENDER=0 python tools/remove_test_activity.py CLASSCODE SIS_ID            # preview only
    PUSH_SENDER=0 python tools/remove_test_activity.py CLASSCODE SIS_ID --apply    # do it

What it does (preview first, nothing changes without --apply):
  - deletes groups where this student is the ONLY member and the survey is still blank (no responses, no
    comments from classmates, no question text...); a group with other members just loses this student;
    a solo group with work in it is left alone and reported
  - deletes this student's comments/drafts, join requests and invites they sent
  - deletes their answers, notification sign-ups and live-session record (only test activity: they never really signed up)
  - resets the sign-up: password, sign-up time, tours seen and group-finder listing, so they show as "Not signed up"
  - keeps the student on the roster with their own comment assignments (every roster student has those), and gives
    classmates who were assigned to a deleted group another group (assignments with written comments never move)
"""
import os
import sys

os.environ.setdefault('PUSH_SENDER', '0')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)
code, sis_id, apply = sys.argv[1].upper(), sys.argv[2].strip(), '--apply' in sys.argv

from app import app  # noqa: E402
from models.db import get_db  # noqa: E402

with app.app_context():
    from models import feedback as fb
    from models.roster import survey_is_blank
    from models.survey import delete_survey
    db = get_db()
    classroom = db.execute('SELECT * FROM classroom WHERE code=?', (code,)).fetchone()
    if not classroom:
        sys.exit(f'No classroom with code {code}.')
    classroom = dict(classroom)
    st = db.execute('SELECT * FROM roster_student WHERE classroom_id=? AND sis_id=?', (classroom['id'], sis_id)).fetchone()
    if not st:
        sys.exit(f'No student with ID {sis_id} in {code}.')
    sid = st['id']
    print(f'Student: {st["full_name"]} ({sis_id}), signed up: {st["registered_at"] or "no"}')

    to_delete, leave = [], []
    for g in db.execute('SELECT s.id, s.group_number, s.title, (SELECT COUNT(*) FROM group_member m WHERE m.survey_id = s.id) AS n '
                        'FROM group_member gm JOIN survey s ON gm.survey_id = s.id WHERE gm.roster_student_id=? AND s.classroom_id=?',
                        (sid, classroom['id'])).fetchall():
        reviewers = db.execute('SELECT COUNT(*) FROM review_assignment WHERE survey_id=?', (g['id'],)).fetchone()[0]
        if g['n'] > 1:
            leave.append(g)
            print(f'  Group {g["group_number"]} ({g["title"]}): {g["n"]} members, this student will be removed from it')
        elif survey_is_blank(g['id']):
            to_delete.append(g)
            print(f'  Group {g["group_number"]} ({g["title"]}): only member, blank survey: will be DELETED '
                  f'({reviewers} classmate(s) assigned to comment on it will get another group)')
        else:
            print(f'  Group {g["group_number"]} ({g["title"]}): only member, but it has survey work, responses or comments: LEFT ALONE')

    fb_rows = db.execute('SELECT COUNT(*) FROM feedback WHERE roster_student_id=?', (sid,)).fetchone()[0]
    requests = db.execute('SELECT COUNT(*) FROM join_request WHERE roster_student_id=?', (sid,)).fetchone()[0]
    sent = db.execute('SELECT COUNT(*) FROM team_invite WHERE invited_by=?', (sid,)).fetchone()[0]
    part = db.execute('SELECT id FROM participant WHERE classroom_id=? AND student_id=?', (classroom['id'], sis_id)).fetchone()
    answers = db.execute('SELECT COUNT(*) FROM response WHERE participant_id=?', (part['id'],)).fetchone()[0] if part else 0
    print(f'  Their comments/drafts: {fb_rows}; join requests: {requests}; invites they sent: {sent}; '
          f'answers: {answers}; live-session record: {"yes" if part else "no"}')

    if not apply:
        print('\nPreview only. Run again with --apply to do it.')
        sys.exit(0)

    before = {(r[0], r[1]) for r in db.execute('SELECT roster_student_id, survey_id FROM review_assignment')}
    for g in to_delete:
        delete_survey(g['id'])  # blank: no images; its assignments and any drafts on it go with it
    for g in leave:
        db.execute('DELETE FROM group_member WHERE survey_id=? AND roster_student_id=?', (g['id'], sid))
    db.execute('DELETE FROM feedback WHERE roster_student_id=?', (sid,))
    db.execute('DELETE FROM join_request WHERE roster_student_id=?', (sid,))
    db.execute('DELETE FROM team_invite WHERE invited_by=?', (sid,))
    if part:
        for table in ('response', 'reminder_action', 'push_subscription'):
            db.execute(f'DELETE FROM {table} WHERE participant_id=?', (part['id'],))
        db.execute('DELETE FROM participant WHERE id=?', (part['id'],))
    db.execute("UPDATE roster_student SET password_hash=NULL, registered_at=NULL, tours_seen='', seeking_group=0, "
               "seeking_note=NULL WHERE id=?", (sid,))
    db.commit()
    if fb.assignments_exist(classroom['id']):
        fb.ensure_assignments(classroom)
        fb.rebalance_assignments(classroom)
    after = {(r[0], r[1]) for r in db.execute('SELECT roster_student_id, survey_id FROM review_assignment')}
    changed = {r for r, _ in after ^ before} - {sid}
    names = {r['id']: r['full_name'] for r in db.execute('SELECT id, full_name FROM roster_student WHERE classroom_id=?', (classroom['id'],))}
    print(f'\nDone. {st["full_name"]} now shows as not signed up and in no group.')
    if changed:
        print(f'Classmates whose assigned groups changed ({len(changed)}): ' + '; '.join(sorted(names.get(r, str(r)) for r in changed)))
