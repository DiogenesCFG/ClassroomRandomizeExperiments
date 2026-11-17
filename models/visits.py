"""Who was shown each survey, whether or not they answered (table survey_visit).

One row per respondent, survey and part, written when the survey is first shown on their page (the three
state endpoints call shown()). That makes it possible to check attrition by arm: students who were assigned
an arm but never answered, or declined at the consent screen, appear in the data with their arm.

  - mode: how it was answered: live (the live session's sequence), class (a part launched separately in
    class), early (opened early from the lobby), remote (a remote part from the lobby)
  - first_shown_at / submitted_at (UTC): together, the total time a respondent took
  - device: phone | tablet | computer, as reported by the page (the instructor also gets the full browser
    string and how many times the page was opened, loads)
  - intro_seconds: time on the intro / consent screen; declined_at: chose "I don't want to take part"
    (their answers are never recorded; the decline is, so dropouts can be compared across arms)

Answers also carry two columns filled by the phone (response and response_draft):
  - changes: how many times they replaced an answer they had given. One-answer questions (multiple
    choice, pictures, rating, number, slider, short answer) count every switch; questions with several
    parts (multiple answers, ranking, grid, budget, price list, lottery) count a change made after
    leaving the question with a finished answer and coming back.
  - first_value: sliders only, the first value they moved it to.
"""
from datetime import datetime

from models.db import is_read_only

MODES = ('live', 'class', 'early', 'remote')
DEVICES = ('phone', 'tablet', 'computer')
EVENTS = ('open', 'start', 'decline')


def shown(db, payload, participant_id, part, mode):
    """Record that this assignment is showing on the respondent's page (first time only) and add
    payload['declined'] (they declined at the consent screen earlier, so the page says so again)."""
    payload['declined'] = False
    if not participant_id or is_read_only():
        return payload
    row = db.execute('SELECT declined_at FROM survey_visit WHERE participant_id=? AND survey_id=? AND part=?',
                     (participant_id, payload['survey_id'], part)).fetchone()
    if row is None:
        db.execute("INSERT OR IGNORE INTO survey_visit (participant_id, survey_id, part, arm_id, mode, first_shown_at) "
                   "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                   (participant_id, payload['survey_id'], part, payload['arm_id'], mode if mode in MODES else None))
        db.commit()
    else:
        payload['declined'] = bool(row['declined_at'])
    return payload


def event(db, participant_id, survey_id, part, arm_id, name, device=None, user_agent=None, intro_seconds=None):
    """Something the page reports: open (the page loaded with this survey), start (pressed Start on the
    intro screen) or decline. Only for a survey already shown to them. Returns True if recorded."""
    where = ' WHERE participant_id=? AND survey_id=? AND part=? AND arm_id=?'
    key = (participant_id, survey_id, part, arm_id)
    if name == 'open':
        cur = db.execute('UPDATE survey_visit SET loads = loads + 1, device = COALESCE(?, device), '
                         'user_agent = COALESCE(?, user_agent)' + where,
                         (device if device in DEVICES else None, (user_agent or '')[:400] or None, *key))
    elif name == 'start':
        cur = db.execute('UPDATE survey_visit SET intro_seconds = COALESCE(?, intro_seconds), declined_at = NULL' + where,
                         (intro_seconds, *key))
    elif name == 'decline':
        cur = db.execute("UPDATE survey_visit SET intro_seconds = COALESCE(?, intro_seconds), declined_at = datetime('now')"
                         + where + ' AND submitted_at IS NULL', (intro_seconds, *key))
    else:
        return False
    return cur.rowcount > 0


def submitted(db, participant_id, survey_id, part, arm_id, mode):
    """Mark a part as submitted (a row is made if the page was opened before visits were recorded)."""
    db.execute("INSERT INTO survey_visit (participant_id, survey_id, part, arm_id, mode, submitted_at) "
               "VALUES (?, ?, ?, ?, ?, datetime('now')) ON CONFLICT(participant_id, survey_id, part) DO UPDATE SET "
               "submitted_at = COALESCE(survey_visit.submitted_at, excluded.submitted_at), declined_at = NULL, "
               "mode = COALESCE(survey_visit.mode, excluded.mode)",
               (participant_id, survey_id, part, arm_id, mode if mode in MODES else None))


def by_participant(db, survey_id):
    """{participant_id: {part: visit dict with arm_label, arm_index, anon_id}} for one survey."""
    out = {}
    for r in db.execute('''
        SELECT v.*, sa.label AS arm_label, sa.arm_index, rs.anon_id
        FROM survey_visit v
        JOIN survey s ON s.id = v.survey_id
        JOIN participant p ON p.id = v.participant_id
        LEFT JOIN survey_arm sa ON sa.id = v.arm_id
        LEFT JOIN roster_student rs ON rs.classroom_id = s.classroom_id AND rs.sis_id = p.student_id
        WHERE v.survey_id = ?''', (survey_id,)):
        out.setdefault(r['participant_id'], {})[r['part']] = dict(r)
    return out


def minutes(first_shown_at, submitted_at):
    """Minutes from first shown to submitted, to 0.1 ('' if either is missing)."""
    try:
        a = datetime.strptime(first_shown_at, '%Y-%m-%d %H:%M:%S')
        b = datetime.strptime(submitted_at, '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return ''
    return round(max(0.0, (b - a).total_seconds()) / 60, 1)


def device_from(user_agent):
    """A fallback when the page doesn't say: phone, tablet or computer from the browser string."""
    ua = user_agent or ''
    if 'iPad' in ua or ('Android' in ua and 'Mobile' not in ua):
        return 'tablet'
    if any(k in ua for k in ('iPhone', 'iPod', 'Android', 'Mobile')):
        return 'phone'
    return 'computer' if ua else None
