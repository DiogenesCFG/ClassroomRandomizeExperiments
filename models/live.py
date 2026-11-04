"""The live session's order, and its mock-up.

By default surveys run in class by group number (the presentation order). The instructor can set a
custom order instead (classroom.live_order: JSON list of survey ids), e.g. shuffled, or changed on the day
because a group leaves early. Surveys missing from the list (created later) come after it, by group number.
"""
import json
import random

from models.db import get_db


def custom_order(classroom):
    """The custom order's survey ids, or None when surveys run by group number."""
    raw = classroom['live_order'] if 'live_order' in classroom.keys() else None
    if not raw:
        return None
    try:
        ids = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return [int(i) for i in ids if str(i).isdigit()] if isinstance(ids, list) else None


def live_sequence(classroom, surveys):
    """surveys (dicts with id, group_number) in the order the live session runs them."""
    by_number = sorted(surveys, key=lambda s: s['group_number'])
    order = custom_order(classroom)
    if order is None:
        return by_number
    pos = {sid: i for i, sid in enumerate(order)}
    return sorted(by_number, key=lambda s: (0, pos[s['id']]) if s['id'] in pos else (1, s['group_number']))


def save_order(classroom_id, ids):
    """A custom order (list of survey ids), or None to go back to group-number order."""
    db = get_db()
    if ids is None:
        db.execute('UPDATE classroom SET live_order=NULL WHERE id=?', (classroom_id,))
    else:
        valid = {r[0] for r in db.execute('SELECT id FROM survey WHERE classroom_id=?', (classroom_id,))}
        clean = []
        for i in ids:
            if i in valid and i not in clean:
                clean.append(i)
        db.execute('UPDATE classroom SET live_order=? WHERE id=?', (json.dumps(clean), classroom_id))
    db.commit()


def shuffled_ids(classroom_id):
    ids = [r[0] for r in get_db().execute('SELECT id FROM survey WHERE classroom_id=? ORDER BY group_number', (classroom_id,))]
    random.shuffle(ids)
    return ids


def next_in_sequence(sequence, current_id, is_due):
    """The next survey to run: the first one after the current one (wrapping to the start) for which
    is_due(survey) is true, i.e. its live part hasn't run yet. A group moved earlier than the current
    survey still runs once the end of the list is reached."""
    ids = [s['id'] for s in sequence]
    start = ids.index(current_id) + 1 if current_id in ids else 0
    for s in sequence[start:] + sequence[:start]:
        if s['id'] != current_id and is_due(s):
            return s
    return None
