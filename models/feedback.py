"""Peer feedback: balanced review assignments, comments (drafts and sent), and early-open surveys."""
import random
import time
from datetime import datetime, timezone

from models.db import get_db


def feedback_started(classroom):
    """Review assignments are made (and shown) once surveys are locked; while groups
    are still building, the list of groups isn't settled."""
    return bool(classroom['surveys_locked'] or classroom['feedback_open'] or classroom['feedback_released'])


def survey_commentable(classroom, survey):
    """Classmates can look at a survey and comment on it once it has gone live: run in a
    live session at least once (it stays open after the host moves on) or opened early.
    Other-platform surveys can't go live here, so they open when surveys are locked."""
    if survey['went_live'] or survey['early_open']:
        return True
    return bool(survey['external'] and feedback_started(classroom))


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
    reviews_required), then other assigned or extra groups they've written about."""
    db = get_db()
    rows = db.execute('''
        SELECT s.id AS survey_id, s.group_number, s.title,
               ra.id AS assignment_id, ra.created_at AS assigned_at,
               f.id AS feedback_id, f.body, f.sent_at, f.updated_at
        FROM survey s
        LEFT JOIN review_assignment ra ON ra.survey_id = s.id AND ra.roster_student_id = ?
        LEFT JOIN feedback f ON f.survey_id = s.id AND f.roster_student_id = ?
        WHERE s.classroom_id = ? AND (ra.id IS NOT NULL OR f.id IS NOT NULL)
        ORDER BY ra.id IS NULL, ra.id, s.group_number
    ''', (roster_student_id, roster_student_id, classroom['id'])).fetchall()
    cards, required_left = [], classroom['reviews_required'] or 0
    for r in rows:
        card = dict(r)
        card['required'] = r['assignment_id'] is not None and required_left > 0
        if card['required']:
            required_left -= 1
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


def save_feedback(survey_id, roster_student_id, body, send):
    """Save a draft (send=False) or send/update a comment (send=True)."""
    db = get_db()
    existing = db.execute('SELECT id, sent_at FROM feedback WHERE survey_id=? AND roster_student_id=?',
                          (survey_id, roster_student_id)).fetchone()
    if existing:
        if send:
            db.execute("UPDATE feedback SET body=?, sent_at=COALESCE(sent_at, datetime('now')), "
                       "updated_at=datetime('now') WHERE id=?", (body, existing['id']))
        else:
            db.execute("UPDATE feedback SET body=?, updated_at=datetime('now') WHERE id=?", (body, existing['id']))
    else:
        db.execute("INSERT INTO feedback (survey_id, roster_student_id, body, sent_at) "
                   "VALUES (?, ?, ?, CASE WHEN ? THEN datetime('now') END)",
                   (survey_id, roster_student_id, body, 1 if send else 0))
    db.commit()


def get_feedback(survey_id, roster_student_id):
    row = get_db().execute('SELECT * FROM feedback WHERE survey_id=? AND roster_student_id=?',
                           (survey_id, roster_student_id)).fetchone()
    return dict(row) if row else None


def delete_feedback(survey_id, roster_student_id):
    db = get_db()
    db.execute('DELETE FROM feedback WHERE survey_id=? AND roster_student_id=?', (survey_id, roster_student_id))
    db.commit()


def is_required(classroom, survey_id, roster_student_id):
    return any(c['survey_id'] == survey_id and c['required']
               for c in student_feedback(classroom, roster_student_id))


def received_feedback(survey_id):
    """Sent comments on a survey, anonymized as Reviewer 1, 2, ... (stable order)."""
    rows = get_db().execute('SELECT body, sent_at FROM feedback WHERE survey_id=? AND sent_at IS NOT NULL '
                            "AND TRIM(body) != '' ORDER BY id", (survey_id,)).fetchall()
    return [{'reviewer': f'Reviewer {i}', 'body': r['body']} for i, r in enumerate(rows, start=1)]


def feedback_progress(classroom):
    """(students who sent all required comments, active students)."""
    db = get_db()
    students = [r['id'] for r in db.execute(
        'SELECT id FROM roster_student WHERE classroom_id=? AND hidden=0', (classroom['id'],))]
    done = 0
    for rid in students:
        cards = [c for c in student_feedback(classroom, rid) if c['required']]
        if cards and all(c['sent_at'] for c in cards):
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
