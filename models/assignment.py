"""Which arm a respondent gets.

Survey options (survey.settings, models/survey.py survey_options):
  split    the target share of each arm, in whole percent by arm position (adds up to 100; default: equal)
  balance  "Enforce split" (default on): permuted-block randomization (next_in_block): respondents fill blocks with
           exactly the split's counts (20/40/40 -> blocks of 5: 1, 2, 2), each block in random order, so the arms are
           exactly on target after every complete block (60/60 of 120 at 50/50, 61/60 of 121) and every arrival
           position gets a random arm, independently for each survey. Off: each respondent is drawn independently
           with those probabilities, so arms can end up uneven.

A respondent's arm never changes once given: balanced assignments are stored (arm_assignment); independent draws
are a stable hash of the student and survey (the original method, sockets/assignment.py, when the split is equal).
Surveys that already had answers before arm_assignment existed keep the original method, so nobody's arm moves.
"""
import hashlib
import random
import sqlite3

from models.db import get_db, is_read_only
from sockets.assignment import assign_arm


def equal_split(n):
    """Whole percents adding up to 100, e.g. 3 arms -> [33, 33, 34]."""
    if n <= 0:
        return []
    base = 100 // n
    out = [base] * n
    for i in range(100 - base * n):
        out[n - 1 - i] += 1
    return out


def split_of(options, n):
    """The survey's split for n arms (equal when unset or no longer matching the arms)."""
    split = options.get('split')
    if isinstance(split, list) and len(split) == n and all(isinstance(x, int) and 0 <= x <= 100 for x in split) \
            and sum(split) == 100:
        return split
    return equal_split(n)


def split_problem(split, n):
    """Why a split typed in the builder can't be saved, or None."""
    if split is None:
        return None
    if len(split) != n:
        return 'The arm percentages don\'t match the arms. Open Survey options and check them.'
    if any(x < 0 or x > 100 for x in split):
        return 'Each arm\'s percentage must be between 0 and 100.'
    if sum(split) != 100:
        return f'The arm percentages must add up to 100% (now {sum(split)}%). Fix them in Survey options.'
    return None


def method(survey, n):
    """'legacy' (the original hash: equal split, independent), 'weighted' (independent, unequal split) or 'balanced'."""
    from models.survey import survey_options
    db = get_db()
    if db.execute('SELECT 1 FROM response WHERE survey_id=?', (survey['id'],)).fetchone() and \
            not db.execute('SELECT 1 FROM arm_assignment WHERE survey_id=?', (survey['id'],)).fetchone():
        return 'legacy'  # answered before balanced assignment existed: keep everyone's arm as it was
    options = survey_options(survey)
    if options['balance']:
        return 'balanced'
    return 'legacy' if split_of(options, n) == equal_split(n) else 'weighted'


def block_of(split):
    """The smallest block of respondents that matches the split within 1 percentage point, as whole counts per arm:
    50/50 -> [1, 1], 20/40/40 -> [1, 2, 2], 33/33/34 -> [1, 1, 1], 35/65 -> [5, 9]."""
    for size in range(1, 101):
        counts = [round(w * size / 100) for w in split]
        if sum(counts) == size and all(abs(c / size - w / 100) <= 0.01 + 1e-9 for c, w in zip(counts, split)):
            return counts
    return list(split)


def next_in_block(split, done, rng):
    """Permuted-block randomization: respondents fill blocks with exactly the split's counts, in random order.
    done: the arms given so far, in order. The next arm is drawn at random among the current block's open slots,
    so every arrival position gets a random arm (no student is tied to an arm by when they arrive), and the arms
    are exactly on target after every complete block."""
    block = block_of(split)
    size = sum(block)
    current = done[len(done) - len(done) % size:] if len(done) % size else []
    open_slots = [c - current.count(i) for i, c in enumerate(block)]
    return rng.choices(range(len(block)), weights=open_slots)[0]


def _fraction(student_id, survey_id):
    """A stable number in [0, 1) for this student and survey."""
    digest = hashlib.sha256(f'weighted:{student_id}:{survey_id}'.encode('utf-8')).digest()
    return int.from_bytes(digest[:6], 'big') / float(1 << 48)


def _pick_weighted(u, split):
    total = 0
    for i, w in enumerate(split):
        total += w
        if u * 100 < total:
            return i
    return max(i for i, w in enumerate(split) if w > 0)


def arm_for(survey, arms, student_id):
    """The arm position for this student in this survey (assigning it the first time)."""
    n = len(arms)
    if n <= 1:
        return 0
    db = get_db()
    row = db.execute('SELECT arm_index FROM arm_assignment WHERE survey_id=? AND student_key=?',
                     (survey['id'], str(student_id))).fetchone()
    if row and row['arm_index'] < n:
        return row['arm_index']
    answered = db.execute('SELECT sa.arm_index FROM response r JOIN participant p ON r.participant_id = p.id '
                          'JOIN survey_arm sa ON r.arm_id = sa.id WHERE r.survey_id=? AND p.student_id=? LIMIT 1',
                          (survey['id'], str(student_id))).fetchone()
    if answered:
        return answered['arm_index']
    how = method(survey, n)
    if how == 'legacy':
        return assign_arm(student_id, survey['id'], n)
    from models.survey import survey_options
    split = split_of(survey_options(survey), n)
    if how == 'weighted':
        return _pick_weighted(_fraction(student_id, survey['id']), split)
    # Balanced: permuted blocks (a random open slot in the current block), stored so it never changes
    began = False
    if not is_read_only():
        try:
            db.execute('BEGIN IMMEDIATE')  # nobody else is assigned between counting and saving
            began = True
        except sqlite3.OperationalError:
            pass  # already inside a transaction
    done = [r['arm_index'] for r in db.execute('SELECT arm_index FROM arm_assignment WHERE survey_id=? ORDER BY id',
                                               (survey['id'],))]
    arm = next_in_block(split, done, random)
    if is_read_only():
        return arm  # the instructor's student view: show an arm, store nothing
    try:
        db.execute('INSERT INTO arm_assignment (survey_id, student_key, arm_index) VALUES (?, ?, ?)',
                   (survey['id'], str(student_id), arm))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        arm = db.execute('SELECT arm_index FROM arm_assignment WHERE survey_id=? AND student_key=?',
                         (survey['id'], str(student_id))).fetchone()['arm_index']
    finally:
        if began and db.in_transaction:
            db.commit()
    return arm


def describe(survey, n):
    """A short description for View survey and the builder: e.g. 'Balanced: 50% / 50%'."""
    from models.survey import survey_options
    how = method(survey, n)
    split = split_of(survey_options(survey), n) if how != 'legacy' else equal_split(n)
    shares = ' / '.join(f'{w}%' for w in split)
    return ('Enforced split' if how == 'balanced' else 'Independent random draws') + f': {shares}'
