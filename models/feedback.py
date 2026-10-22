"""Peer feedback: balanced review assignments, comments (drafts and sent), and early-open surveys."""
import random
import time
from datetime import datetime, timezone

from models.db import get_db


# --- Comment rounds ---
# 'sketch': comments on each group's presentation (its experiment sketch), before the surveys run;
# any group can be commented on, without seeing its survey. 'survey': comments on each group's
# survey, once it has run. Each round is on/off (classroom.fb_<round>_on; on = required for the
# student's assigned groups) and open between fb_<round>_open_at and fb_<round>_close_at (ISO UTC).
# A round's comments are shown to the groups once it closes. Both rounds use the same assignments.

ROUNDS = ('sketch', 'survey')
ROUND_NAMES = {'sketch': 'presentation', 'survey': 'survey'}


def _utc(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def round_on(classroom, rnd):
    return bool(classroom[f'fb_{rnd}_on'])


def round_state(classroom, rnd, now=None):
    """'off', 'unscheduled' (on, no opening time), 'upcoming', 'open' or 'closed'."""
    if not round_on(classroom, rnd):
        return 'off'
    opens, closes = _utc(classroom[f'fb_{rnd}_open_at']), _utc(classroom[f'fb_{rnd}_close_at'])
    now = now or datetime.now(timezone.utc)
    if closes and now > closes:
        return 'closed'
    if not opens:
        return 'unscheduled'
    return 'open' if now >= opens else 'upcoming'


def rounds_info(classroom):
    """Both rounds for the pages: key, name, on, state, open_at, close_at, instructions (the instructor's, or '')."""
    return [{'key': r, 'name': ROUND_NAMES[r], 'on': round_on(classroom, r), 'state': round_state(classroom, r),
             'open_at': classroom[f'fb_{r}_open_at'], 'close_at': classroom[f'fb_{r}_close_at'],
             'instructions': (classroom[f'fb_{r}_instructions'] or '').strip()} for r in ROUNDS]


def active_rounds(classroom):
    return [r for r in ROUNDS if round_on(classroom, r)]


def released(classroom, rnd):
    """Groups read a round's comments once it has closed."""
    return round_state(classroom, rnd) == 'closed'


def any_round_started(classroom):
    return any(round_state(classroom, r) in ('open', 'closed') for r in ROUNDS)


def feedback_started(classroom):
    """Review assignments are shown once they exist: made when surveys are locked, when a round
    opens, or when the host assigns them (e.g. for presentations, while groups are still building)."""
    return bool(classroom['surveys_locked'] or any_round_started(classroom) or assignments_exist(classroom['id']))


def survey_viewable(classroom, survey):
    """Classmates can look at a survey (View survey, previews) once it has gone live: run in a
    live session at least once (it stays open after the host moves on) or opened early, so
    nobody sees the arms before answering. Other-platform surveys can't go live here, so they
    open when surveys are locked or a comment round has started."""
    if survey['went_live'] or survey['early_open']:
        return True
    return bool(survey['external'] and (classroom['surveys_locked'] or any_round_started(classroom)))


def can_draft(classroom, survey, rnd):
    """A comment in this round can be written (draft) now: the round is on and not closed, and
    for the survey round, the survey has run (presentations can be commented on any time)."""
    if round_state(classroom, rnd) in ('off', 'closed'):
        return False
    return rnd == 'sketch' or survey_viewable(classroom, survey)


def survey_commentable(classroom, survey):
    """Some comment on this group is possible now (in either round)."""
    return any(can_draft(classroom, survey, r) for r in ROUNDS)


def commentable_ids(classroom):
    return {r['id'] for r in get_db().execute('SELECT * FROM survey WHERE classroom_id=?', (classroom['id'],))
            if survey_commentable(classroom, r)}


# --- Review assignments ---

ATTEMPTS = 40  # randomized tries per assignment run; the best one is kept
TIME_BUDGET = 1.5  # seconds; stop retrying after this (the host is waiting on the click)

def _group_members(db, classroom_id):
    """survey_id -> set of roster_student_ids in that group."""
    members = {}
    for r in db.execute('SELECT gm.survey_id, gm.roster_student_id FROM group_member gm '
                        'JOIN survey s ON gm.survey_id = s.id WHERE s.classroom_id=? '
                        'AND gm.roster_student_id IS NOT NULL', (classroom_id,)):
        members.setdefault(r['survey_id'], set()).add(r['roster_student_id'])
    return members


def ensure_assignments(classroom, only_student_id=None):
    """Make sure every active student has `reviews_required` groups to comment on.

    Existing assignments are never reshuffled. Invalid ones (the student has since
    joined that group) are dropped. Missing ones are filled at random so every group
    gets about the same number of reviewers and, whenever possible, no two members of
    a group review the same other group. Pass only_student_id to top up a single student (e.g. a
    late addition).
    """
    db = get_db()
    cid = classroom['id']
    needed = classroom['reviews_required'] or 0
    surveys = [r['id'] for r in db.execute('SELECT id FROM survey WHERE classroom_id=?', (cid,))]
    members = _group_members(db, cid)

    # Drop assignments to a student's own group
    db.execute('''DELETE FROM review_assignment WHERE survey_id IN (SELECT id FROM survey WHERE classroom_id=?)
                  AND EXISTS (SELECT 1 FROM group_member gm WHERE gm.survey_id = review_assignment.survey_id
                              AND gm.roster_student_id = review_assignment.roster_student_id)''', (cid,))

    load0 = {sid: 0 for sid in surveys}
    assigned0 = {}
    for r in db.execute('SELECT ra.roster_student_id, ra.survey_id FROM review_assignment ra '
                        'JOIN survey s ON ra.survey_id = s.id WHERE s.classroom_id=?', (cid,)):
        load0[r['survey_id']] = load0.get(r['survey_id'], 0) + 1
        assigned0.setdefault(r['roster_student_id'], set()).add(r['survey_id'])

    if only_student_id:
        students = [only_student_id]
    else:
        students = [r['id'] for r in db.execute(
            'SELECT id FROM roster_student WHERE classroom_id=? AND hidden=0', (cid,))]
    teammates = {}
    for group in members.values():
        for rid in group:
            teammates.setdefault(rid, set()).update(group - {rid})

    def attempt(rng):
        """One randomized pass. Returns (new pairs, group loads, everyone's groups)."""
        load = dict(load0)
        assigned = {rid: set(sids) for rid, sids in assigned0.items()}
        new = []  # [roster_student_id, survey_id] pairs created in this run

        def eligible_for(rid):
            mine = assigned.setdefault(rid, set())
            return [sid for sid in surveys if sid not in mine and rid not in members.get(sid, set())]

        def overlap(rid, sid):
            """How many of rid's teammates already review group sid."""
            return sum(1 for t in teammates.get(rid, ()) if sid in assigned.get(t, ()))

        # Hand out one assignment per round. Within a round, students with the fewest
        # choices go first (random among equals), so flexible students fill the gaps
        # and every group ends up with about the same number of reviewers.
        while True:
            needy = [rid for rid in students if len(assigned.setdefault(rid, set())) < needed and eligible_for(rid)]
            if not needy:
                break
            rng.shuffle(needy)
            needy.sort(key=lambda rid: len(eligible_for(rid)))
            for rid in needy:
                eligible = eligible_for(rid)
                if len(assigned[rid]) >= needed or not eligible:
                    continue
                low = min(load[sid] for sid in eligible)
                lightest = [sid for sid in eligible if load[sid] == low]
                fewest = min(overlap(rid, sid) for sid in lightest)
                pick = rng.choice([sid for sid in lightest if overlap(rid, sid) == fewest])
                new.append([rid, pick])
                assigned[rid].add(pick)
                load[pick] += 1

        # Greedy can leave groups uneven (e.g. 5/6/7 when 6/6/6 is possible). Move
        # assignments made in this run (never older ones) from the busiest group to
        # the least-reviewed one while some student can switch.
        improved = True
        while improved:
            improved = False
            for pair in sorted(new, key=lambda p: -load[p[1]]):
                rid, sid = pair
                options = [o for o in eligible_for(rid) if load[o] <= load[sid] - 2]
                if options:
                    target = min(options, key=lambda o: (load[o], overlap(rid, o)))
                    assigned[rid].discard(sid)
                    assigned[rid].add(target)
                    load[sid] -= 1
                    load[target] += 1
                    pair[1] = target
                    improved = True
                    break

        # Remove teammate overlaps by swapping targets between two students' new
        # assignments (loads stay exactly the same).
        def clash(rid, sid):
            return any(sid in assigned.get(t, ()) for t in teammates.get(rid, ()))

        for _ in range(20):
            conflicts = [p for p in new if clash(*p)]
            if not conflicts:
                break
            rng.shuffle(conflicts)
            swapped = False
            for pair in conflicts:
                rid, sid = pair
                if not clash(rid, sid):  # fixed by an earlier swap in this pass
                    continue
                others = new[:]
                rng.shuffle(others)
                for other in others:
                    cid_, tid = other
                    if cid_ == rid or tid == sid or tid in assigned[rid] or sid in assigned[cid_] \
                            or rid in members.get(tid, ()) or cid_ in members.get(sid, ()):
                        continue
                    assigned[rid].discard(sid); assigned[cid_].discard(tid)
                    if clash(rid, tid) or clash(cid_, sid):
                        assigned[rid].add(sid); assigned[cid_].add(tid)
                        continue
                    assigned[rid].add(tid); assigned[cid_].add(sid)
                    pair[1], other[1] = tid, sid
                    swapped = True
                    break
            if not swapped:
                break
        return new, load, assigned

    def score(load, assigned):
        """Lower is better: even loads first, then teammates sharing a group to review."""
        spread = (max(load.values()) - min(load.values())) if load else 0
        shared = sum(len(assigned.get(a, set()) & assigned.get(b, set()))
                     for rid, mates in teammates.items() for a, b in [(rid, m) for m in mates if m > rid])
        return (spread > 1, shared, spread)

    # The greedy pass usually finds an assignment where no two teammates review the
    # same group; a few random retries catch the cases it misses. When that's
    # impossible (small classes, many required comments) the best try is kept.
    rng = random.Random()
    deadline = time.monotonic() + TIME_BUDGET
    best = None
    for _ in range(ATTEMPTS):
        new, load, assigned = attempt(rng)
        sc = score(load, assigned)
        if best is None or sc < best[0]:
            best = (sc, new)
        if sc[:2] == (False, 0) or time.monotonic() > deadline:
            break
    new = best[1]

    for rid, sid in new:
        db.execute('INSERT INTO review_assignment (roster_student_id, survey_id) VALUES (?, ?)', (rid, sid))
    db.commit()


def assignments_exist(classroom_id):
    return get_db().execute('SELECT 1 FROM review_assignment ra JOIN survey s ON ra.survey_id = s.id '
                            'WHERE s.classroom_id=? LIMIT 1', (classroom_id,)).fetchone() is not None


def student_feedback(classroom, roster_student_id):
    """The student's feedback cards: required groups first (oldest assignments up to
    reviews_required), then other assigned or extra groups they've written about. Each card has
    'rounds': {round: {feedback_id, body, sent_at, updated_at}} for the comments written so far."""
    db = get_db()
    rows = db.execute('''
        SELECT s.id AS survey_id, s.group_number, s.title, s.went_live, s.early_open, s.external,
               ra.id AS assignment_id, ra.created_at AS assigned_at
        FROM survey s
        LEFT JOIN review_assignment ra ON ra.survey_id = s.id AND ra.roster_student_id = ?
        WHERE s.classroom_id = ? AND (ra.id IS NOT NULL OR EXISTS (
            SELECT 1 FROM feedback f WHERE f.survey_id = s.id AND f.roster_student_id = ?))
        ORDER BY ra.id IS NULL, ra.id, s.group_number
    ''', (roster_student_id, classroom['id'], roster_student_id)).fetchall()
    comments = {}
    for f in db.execute('SELECT f.* FROM feedback f JOIN survey s ON f.survey_id = s.id '
                        'WHERE f.roster_student_id = ? AND s.classroom_id = ?', (roster_student_id, classroom['id'])):
        comments.setdefault(f['survey_id'], {})[f['round']] = {
            'feedback_id': f['id'], 'body': f['body'], 'sent_at': f['sent_at'], 'updated_at': f['updated_at']}
    cards, required_left = [], classroom['reviews_required'] or 0
    for r in rows:
        card = dict(r)
        card['required'] = r['assignment_id'] is not None and required_left > 0
        if card['required']:
            required_left -= 1
        card['rounds'] = comments.get(r['survey_id'], {})
        card['has_comment'] = bool(card['rounds'])
        cards.append(card)
    return cards


def commentable_surveys(classroom_id, roster_student_id):
    """Surveys a student may comment on: any in the classroom except their own groups'."""
    return [dict(r) for r in get_db().execute('''
        SELECT s.id, s.group_number, s.title FROM survey s
        WHERE s.classroom_id = ? AND NOT EXISTS (
            SELECT 1 FROM group_member gm WHERE gm.survey_id = s.id AND gm.roster_student_id = ?)
        ORDER BY s.group_number''', (classroom_id, roster_student_id))]


def is_own_survey(survey_id, roster_student_id):
    return get_db().execute('SELECT 1 FROM group_member WHERE survey_id=? AND roster_student_id=?',
                            (survey_id, roster_student_id)).fetchone() is not None


def save_feedback(survey_id, roster_student_id, body, send, rnd='survey'):
    """Save a draft (send=False) or send/update a comment (send=True) in a round."""
    db = get_db()
    existing = db.execute('SELECT id, sent_at FROM feedback WHERE survey_id=? AND roster_student_id=? AND round=?',
                          (survey_id, roster_student_id, rnd)).fetchone()
    if existing:
        if send:
            db.execute("UPDATE feedback SET body=?, sent_at=COALESCE(sent_at, datetime('now')), "
                       "updated_at=datetime('now') WHERE id=?", (body, existing['id']))
        else:
            db.execute("UPDATE feedback SET body=?, updated_at=datetime('now') WHERE id=?", (body, existing['id']))
    else:
        db.execute("INSERT INTO feedback (survey_id, roster_student_id, body, sent_at, round) "
                   "VALUES (?, ?, ?, CASE WHEN ? THEN datetime('now') END, ?)",
                   (survey_id, roster_student_id, body, 1 if send else 0, rnd))
    db.commit()


def get_feedback(survey_id, roster_student_id, rnd='survey'):
    row = get_db().execute('SELECT * FROM feedback WHERE survey_id=? AND roster_student_id=? AND round=?',
                           (survey_id, roster_student_id, rnd)).fetchone()
    return dict(row) if row else None


def delete_feedback(survey_id, roster_student_id):
    """Remove a student's (extra) comments on a group, in every round."""
    db = get_db()
    db.execute('DELETE FROM feedback WHERE survey_id=? AND roster_student_id=?', (survey_id, roster_student_id))
    db.commit()


def is_required(classroom, survey_id, roster_student_id):
    return any(c['survey_id'] == survey_id and c['required']
               for c in student_feedback(classroom, roster_student_id))


def received_feedback(classroom, survey_id):
    """Sent comments on a group from the rounds that have closed, anonymized as Reviewer 1, 2, ...
    (the same reviewer keeps their number across rounds): [{'round', 'name', 'comments': [...]}]."""
    rows = get_db().execute('SELECT roster_student_id, body, round FROM feedback WHERE survey_id=? AND sent_at IS NOT NULL '
                            "AND TRIM(body) != '' ORDER BY id", (survey_id,)).fetchall()
    numbers = {}
    for r in rows:
        numbers.setdefault(r['roster_student_id'], len(numbers) + 1)
    out = []
    for rnd in ROUNDS:
        if not released(classroom, rnd):
            continue
        out.append({'round': rnd, 'name': ROUND_NAMES[rnd],
                    'comments': [{'reviewer': f'Reviewer {numbers[r["roster_student_id"]]}', 'body': r['body']}
                                 for r in rows if r['round'] == rnd]})
    return out


def feedback_progress(classroom, rnd):
    """(students who sent all their required comments in this round, active students)."""
    db = get_db()
    students = [r['id'] for r in db.execute(
        'SELECT id FROM roster_student WHERE classroom_id=? AND hidden=0', (classroom['id'],))]
    done = 0
    for rid in students:
        cards = [c for c in student_feedback(classroom, rid) if c['required']]
        if cards and all((c['rounds'].get(rnd) or {}).get('sent_at') for c in cards):
            done += 1
    return done, len(students)


# --- Early-open surveys ---

def parse_utc(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None


def early_survey_is_open(survey):
    """An early survey takes answers until its deadline."""
    if not survey.get('early_open'):
        return False
    deadline = parse_utc(survey.get('early_deadline_utc'))
    return deadline is None or datetime.now(timezone.utc) <= deadline


def open_surveys_for_student(classroom, roster_student_id, participant_id):
    """Early-open surveys a student can answer from the lobby, with whether they already did."""
    db = get_db()
    rows = db.execute('SELECT * FROM survey WHERE classroom_id=? AND early_open=1 AND external=0 ORDER BY group_number',
                      (classroom['id'],)).fetchall()
    out = []
    for r in rows:
        s = dict(r)
        if is_own_survey(s['id'], roster_student_id):
            continue
        s['open_now'] = early_survey_is_open(s)
        s['answered'] = participant_id is not None and db.execute(
            'SELECT 1 FROM response WHERE survey_id=? AND participant_id=?', (s['id'], participant_id)).fetchone() is not None
        out.append(s)
    return out


def rebalance_assignments(classroom):
    """Give groups formed after reviewers were assigned (e.g. solo groups) their share of reviewers.

    ensure_assignments() never reshuffles, so a new group would get none. This moves assignments from
    the most-reviewed groups to the least-reviewed ones, but only assignments the student hasn't written
    anything on yet (no draft or comment in any round), and never to the student's own group or a group
    they already review. Each moved assignment keeps its id, so it stays required (or optional).
    Returns the number of assignments moved."""
    db = get_db()
    cid = classroom['id']
    members = _group_members(db, cid)
    surveys = [r['id'] for r in db.execute('SELECT id FROM survey WHERE classroom_id=?', (cid,))]
    rows = [dict(r) for r in db.execute('SELECT ra.id, ra.roster_student_id, ra.survey_id FROM review_assignment ra '
                                        'JOIN survey s ON ra.survey_id = s.id WHERE s.classroom_id=?', (cid,))]
    if not rows or len(surveys) < 2:
        return 0
    written = {(r['roster_student_id'], r['survey_id']) for r in db.execute(
        "SELECT f.roster_student_id, f.survey_id FROM feedback f JOIN survey s ON f.survey_id = s.id "
        "WHERE s.classroom_id=? AND TRIM(f.body) != ''", (cid,))}
    load = {sid: 0 for sid in surveys}
    assigned = {}
    for r in rows:
        load[r['survey_id']] = load.get(r['survey_id'], 0) + 1
        assigned.setdefault(r['roster_student_id'], set()).add(r['survey_id'])
    teammates = {}
    for group in members.values():
        for rid in group:
            teammates.setdefault(rid, set()).update(group - {rid})
    moved = 0
    stuck = set()
    while True:
        open_targets = [s for s in surveys if s not in stuck]
        if not open_targets:
            break
        low = min(open_targets, key=lambda s: load[s])
        best = None
        for src in sorted(surveys, key=lambda s: -load[s]):
            if load[src] - load[low] < 2:
                break
            for r in rows:
                rid = r['roster_student_id']
                if r['survey_id'] != src or (rid, src) in written or rid in members.get(low, set()) \
                        or low in assigned.get(rid, set()):
                    continue
                overlap = sum(1 for t in teammates.get(rid, ()) if low in assigned.get(t, ()))
                if best is None or overlap < best[1]:
                    best = (r, overlap)
                if overlap == 0:
                    break
            if best:
                break
        if not best:
            stuck.add(low)
            continue
        r = best[0]
        db.execute('UPDATE review_assignment SET survey_id=? WHERE id=?', (low, r['id']))
        assigned[r['roster_student_id']].discard(r['survey_id'])
        assigned[r['roster_student_id']].add(low)
        load[r['survey_id']] -= 1
        load[low] += 1
        r['survey_id'] = low
        moved += 1
    db.commit()
    return moved
