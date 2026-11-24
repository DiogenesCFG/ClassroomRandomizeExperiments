"""Make-up access: a student who missed class (sick, an accident) answers the surveys that ran in class, later.

The instructor gives a roster student access until a date (roster page, "Make-up access" card;
roster_student.makeup_until = ISO UTC end of that day in the instructor's browser, makeup_label = the date as chosen).
While it lasts, the student's lobby lists every part that ran in class (live or launched in class) and that they
haven't submitted, except their own group's surveys and other-platform ones; each opens on its own page
(/c/<code>/student/makeup/<id>/<part>, the student page with POLL_ONCE). Only that student can answer, nothing is
reopened for the class, and their visit is recorded with mode 'makeup', so exports tell these answers apart.
Part 2 still needs part 1 first (in the same arm).
"""
from datetime import datetime, timezone

from models import reminders
from models.db import get_db
from models.feedback import parse_utc


def is_active(student):
    """Does this roster student (dict / row) have make-up access now?"""
    if not student:
        return False
    keys = student.keys() if hasattr(student, 'keys') else []
    until = parse_utc(student['makeup_until']) if 'makeup_until' in keys and student['makeup_until'] else None
    return until is not None and datetime.now(timezone.utc) <= until


def _own_survey_ids(db, roster_student_id):
    return {r[0] for r in db.execute('SELECT gm.survey_id FROM group_member gm JOIN roster_student rs ON rs.id = ? '
                                     'WHERE gm.roster_student_id = rs.id OR gm.sis_code = rs.sis_id', (roster_student_id,))}


def eligible(db, survey, part, roster_student_id):
    """Can this student make up this part: it ran in class, it's not their group's, not another platform."""
    if not survey or survey['external'] or survey['id'] in _own_survey_ids(db, roster_student_id):
        return False
    if part not in ((1, 2) if reminders.is_two_part(survey) else (1,)):
        return False
    return reminders.part_when(survey, part) in ('live', 'class') and reminders.part_ran(survey, part)


def allows(db, classroom_id, sis_id, survey, part):
    """For the submit / draft checks: the signed-in student (by SIS ID) may answer this part as a make-up."""
    student = db.execute('SELECT * FROM roster_student WHERE classroom_id=? AND sis_id=? AND hidden=0',
                         (classroom_id, sis_id)).fetchone()
    return bool(student) and is_active(student) and eligible(db, dict(survey), part, student['id'])


def to_make_up(classroom, student, participant_id):
    """The lobby's list for a student with make-up access: [{survey, part, done, needs_part1}], by group number."""
    if not is_active(student):
        return []
    from sockets.events import _is_fully_answered
    db = get_db()
    out = []
    for row in db.execute('SELECT * FROM survey WHERE classroom_id=? AND external=0 ORDER BY group_number',
                          (classroom['id'],)):
        s = dict(row)
        for part in ((1, 2) if reminders.is_two_part(s) else (1,)):
            if not eligible(db, s, part, student['id']):
                continue
            done = bool(participant_id) and _is_fully_answered(db, participant_id, s['id'], part)
            needs_part1 = part == 2 and not (participant_id and reminders.answered_part(db, participant_id, s, 1))
            out.append({'id': s['id'], 'group_number': s['group_number'], 'title': s['title'], 'part': part,
                        'two_part': reminders.is_two_part(s), 'done': done, 'needs_part1': needs_part1})
    return out


def give(classroom_id, roster_student_id, until_utc, label):
    db = get_db()
    db.execute('UPDATE roster_student SET makeup_until=?, makeup_label=? WHERE id=? AND classroom_id=?',
               (until_utc, label, roster_student_id, classroom_id))
    db.commit()


def remove(classroom_id, roster_student_id):
    db = get_db()
    db.execute('UPDATE roster_student SET makeup_until=NULL, makeup_label=NULL WHERE id=? AND classroom_id=?',
               (roster_student_id, classroom_id))
    db.commit()


def granted(classroom_id):
    """Everyone given make-up access (current or expired), for the roster page."""
    rows = get_db().execute('SELECT id, full_name, sis_id, makeup_until, makeup_label FROM roster_student '
                            'WHERE classroom_id=? AND makeup_until IS NOT NULL ORDER BY full_name COLLATE NOCASE',
                            (classroom_id,)).fetchall()
    return [dict(r, active=is_active(r)) for r in rows]
