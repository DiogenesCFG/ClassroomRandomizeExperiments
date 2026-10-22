"""Class roster, student accounts, and team (group) membership."""
import csv
import io
import re
import secrets

from werkzeug.security import generate_password_hash, check_password_hash

from models.db import get_db


# --- Anonymized respondent IDs ---

# No 0/O, 1/I/L so IDs are easy to read aloud or copy by hand
ANON_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'


def new_anon_id(db):
    """A random respondent ID like 'R-7KQ2PX' that isn't used by any roster student yet."""
    while True:
        candidate = 'R-' + ''.join(secrets.choice(ANON_ALPHABET) for _ in range(6))
        if not db.execute('SELECT 1 FROM roster_student WHERE anon_id=?', (candidate,)).fetchone():
            return candidate


def backfill_anon_ids(db):
    """Give every roster student without one an anonymized ID (runs at startup)."""
    rows = db.execute('SELECT id FROM roster_student WHERE anon_id IS NULL').fetchall()
    for row in rows:
        db.execute('UPDATE roster_student SET anon_id=? WHERE id=?', (new_anon_id(db), row['id']))
    if rows:
        db.commit()


# --- CSV parsing ---

# Normalized header names (lowercase, letters/digits only), in priority order.
ID_HEADERS = ['sisuserid', 'sisid', 'studentid', 'studentnumber', 'sid', 'sisloginid', 'id', 'userid']
FULL_NAME_HEADERS = ['student', 'name', 'studentname', 'fullname', 'sortablename']
FIRST_NAME_HEADERS = ['firstname', 'first', 'givenname', 'preferredname', 'nombre']
LAST_NAME_HEADERS = ['lastname', 'last', 'surname', 'familyname', 'apellido', 'apellidos']


def _norm(header):
    return re.sub(r'[^a-z0-9]', '', (header or '').lower())


def _find_col(headers, candidates):
    normed = [_norm(h) for h in headers]
    for cand in candidates:
        if cand in normed:
            return normed.index(cand)
    return None


def decode_csv_bytes(data):
    """Decode uploaded CSV bytes, tolerating Excel's BOM and Latin-1 exports."""
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace')


def read_csv_rows(text):
    """Parse CSV text into a list of rows. Detects comma, semicolon, or tab delimiters."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    return rows


def guess_mapping(headers):
    """Guess which columns hold the ID and the name(s). Returns a mapping dict."""
    id_col = _find_col(headers, ID_HEADERS)
    first_col = _find_col(headers, FIRST_NAME_HEADERS)
    last_col = _find_col(headers, LAST_NAME_HEADERS)
    full_col = _find_col(headers, FULL_NAME_HEADERS)
    if first_col is not None and last_col is not None:
        return {'id_col': id_col, 'name_mode': 'split', 'full_col': full_col,
                'first_col': first_col, 'last_col': last_col}
    return {'id_col': id_col, 'name_mode': 'full', 'full_col': full_col,
            'first_col': first_col, 'last_col': last_col}


def split_full_name(full):
    """Split a combined name into (first, last).

    "Cruz Fernández, María José" -> ("María José", "Cruz Fernández")
    "María José Cruz"            -> ("María", "José Cruz")   (no comma: first word is the first name)
    """
    full = ' '.join(full.split())
    if ',' in full:
        last, first = full.split(',', 1)
        return first.strip(), last.strip()
    parts = full.split(' ', 1)
    return parts[0], (parts[1] if len(parts) > 1 else '')


def _cell(row, idx):
    if idx is None or idx >= len(row):
        return ''
    return ' '.join(row[idx].split())


def parse_roster(rows, mapping):
    """Apply a column mapping to data rows (header excluded).

    Returns (students, skipped) where students is a list of dicts with
    sis_id, full_name, first_name, last_name and skipped is a list of
    (row_number, reason) tuples.
    """
    students, skipped, seen = [], [], set()
    for n, row in enumerate(rows, start=2):  # row 1 is the header
        sis_id = _cell(row, mapping['id_col'])
        if mapping['name_mode'] == 'split':
            first = _cell(row, mapping['first_col'])
            last = _cell(row, mapping['last_col'])
            full = f'{last}, {first}' if last and first else (first or last)
        else:
            full = _cell(row, mapping['full_col'])
            first, last = split_full_name(full)

        # Canvas gradebook exports include these non-student rows
        if 'points possible' in full.lower() or full.lower() in ('student, test', 'test student'):
            skipped.append((n, 'Canvas placeholder row'))
            continue
        if not sis_id:
            skipped.append((n, 'missing ID'))
            continue
        if not full:
            skipped.append((n, 'missing name'))
            continue
        if sis_id in seen:
            skipped.append((n, f'duplicate ID {sis_id}'))
            continue
        seen.add(sis_id)
        students.append({'sis_id': sis_id, 'full_name': full,
                         'first_name': first or full, 'last_name': last})
    return students, skipped


# --- Roster CRUD ---

def import_students(classroom_id, students, hide_missing=False):
    """Add new students and update names of existing ones (matched by SIS ID).

    Existing passwords and group memberships are kept. Previously hidden students
    who appear in the file are unhidden. If hide_missing is True, active students
    whose ID is not in the file are hidden. Returns a dict of counts.
    """
    db = get_db()
    added = updated = hidden = 0
    added_ids = []
    for s in students:
        row = db.execute('SELECT id FROM roster_student WHERE classroom_id=? AND sis_id=?',
                         (classroom_id, s['sis_id'])).fetchone()
        if row:
            db.execute('UPDATE roster_student SET full_name=?, first_name=?, last_name=?, hidden=0 WHERE id=?',
                       (s['full_name'], s['first_name'], s['last_name'], row['id']))
            updated += 1
        else:
            cur = db.execute('INSERT INTO roster_student (classroom_id, sis_id, full_name, first_name, last_name, anon_id) '
                             'VALUES (?, ?, ?, ?, ?, ?)',
                             (classroom_id, s['sis_id'], s['full_name'], s['first_name'], s['last_name'],
                              new_anon_id(db)))
            added_ids.append(cur.lastrowid)
            added += 1
    if hide_missing and students:
        ids = [s['sis_id'] for s in students]
        placeholders = ','.join('?' * len(ids))
        cur = db.execute(f'UPDATE roster_student SET hidden=1 WHERE classroom_id=? AND hidden=0 '
                         f'AND sis_id NOT IN ({placeholders})', (classroom_id, *ids))
        hidden = cur.rowcount
    db.commit()
    return {'added': added, 'updated': updated, 'hidden': hidden, 'added_ids': added_ids}


def undo_added_students(classroom_id, roster_student_ids):
    """Delete students added by an import, unless they've already signed up or joined a group."""
    db = get_db()
    removed = 0
    for rid in roster_student_ids:
        cur = db.execute(
            'DELETE FROM roster_student WHERE id=? AND classroom_id=? AND password_hash IS NULL '
            'AND NOT EXISTS (SELECT 1 FROM group_member WHERE roster_student_id=roster_student.id)',
            (rid, classroom_id))
        removed += cur.rowcount
    db.commit()
    return removed


def list_roster(classroom_id):
    """All roster students with their group count, the size of their (largest) group and their
    pending invites, ordered by name."""
    db = get_db()
    rows = db.execute('''
        SELECT rs.*,
            (SELECT COUNT(*) FROM group_member gm WHERE gm.roster_student_id = rs.id) AS group_count,
            (SELECT GROUP_CONCAT(s.group_number, ', ') FROM group_member gm
             JOIN survey s ON gm.survey_id = s.id WHERE gm.roster_student_id = rs.id) AS group_numbers,
            (SELECT MAX((SELECT COUNT(*) FROM group_member g2 WHERE g2.survey_id = gm.survey_id))
             FROM group_member gm WHERE gm.roster_student_id = rs.id) AS group_size,
            (SELECT COUNT(*) FROM team_invite ti WHERE ti.roster_student_id = rs.id) AS invite_count
        FROM roster_student rs
        WHERE rs.classroom_id = ?
        ORDER BY rs.hidden, rs.full_name COLLATE NOCASE
    ''', (classroom_id,)).fetchall()
    return [dict(r) for r in rows]


def teams_overview(classroom_id):
    """For the roster's hover boxes: each group's members and pending invites, which groups each
    student is in, and which groups invited them (with who sent the invite)."""
    db = get_db()
    groups, member_of, invited_to = {}, {}, {}
    for r in db.execute('SELECT id, group_number, title FROM survey WHERE classroom_id=? ORDER BY group_number', (classroom_id,)):
        groups[r['id']] = {'number': r['group_number'], 'title': r['title'], 'members': [], 'invited': []}
    for r in db.execute('SELECT gm.survey_id, gm.roster_student_id, gm.name FROM group_member gm JOIN survey s '
                        'ON gm.survey_id = s.id WHERE s.classroom_id=? ORDER BY gm.name COLLATE NOCASE', (classroom_id,)):
        groups[r['survey_id']]['members'].append(r['name'])
        if r['roster_student_id']:
            member_of.setdefault(r['roster_student_id'], []).append(r['survey_id'])
    for r in db.execute('SELECT ti.survey_id, ti.roster_student_id, rs.full_name, inv.full_name AS inviter FROM team_invite ti '
                        'JOIN survey s ON ti.survey_id = s.id JOIN roster_student rs ON ti.roster_student_id = rs.id '
                        'LEFT JOIN roster_student inv ON ti.invited_by = inv.id WHERE s.classroom_id=? '
                        'ORDER BY rs.full_name COLLATE NOCASE', (classroom_id,)):
        groups[r['survey_id']]['invited'].append(r['full_name'])
        invited_to.setdefault(r['roster_student_id'], []).append({'survey_id': r['survey_id'], 'inviter': r['inviter']})
    requested = {}
    for r in db.execute('SELECT jr.survey_id, jr.roster_student_id FROM join_request jr JOIN survey s ON jr.survey_id = s.id '
                        'WHERE s.classroom_id=?', (classroom_id,)):
        requested[r['roster_student_id']] = r['survey_id']
    return {'groups': groups, 'member_of': member_of, 'invited_to': invited_to, 'requested': requested}


def get_student(classroom_id, roster_student_id):
    row = get_db().execute('SELECT * FROM roster_student WHERE id=? AND classroom_id=?',
                           (roster_student_id, classroom_id)).fetchone()
    return dict(row) if row else None


def get_student_by_sis(classroom_id, sis_id):
    row = get_db().execute('SELECT * FROM roster_student WHERE classroom_id=? AND sis_id=?',
                           (classroom_id, sis_id.strip())).fetchone()
    return dict(row) if row else None


def add_student(classroom_id, sis_id, full_name):
    """Add a single student. Returns an error message or None."""
    sis_id, full_name = sis_id.strip(), ' '.join(full_name.split())
    if not sis_id or not full_name:
        return 'Both SIS ID and name are required.'
    existing = get_student_by_sis(classroom_id, sis_id)
    if existing and not existing['hidden']:
        return f'A student with ID {sis_id} is already on the roster.'
    first, last = split_full_name(full_name)
    import_students(classroom_id, [{'sis_id': sis_id, 'full_name': full_name,
                                    'first_name': first, 'last_name': last}])
    return None


def set_hidden(classroom_id, roster_student_id, hidden):
    db = get_db()
    db.execute('UPDATE roster_student SET hidden=? WHERE id=? AND classroom_id=?',
               (1 if hidden else 0, roster_student_id, classroom_id))
    db.commit()


def reset_password(classroom_id, roster_student_id):
    """Clear a student's password so their next sign-in sets a new one."""
    db = get_db()
    db.execute('UPDATE roster_student SET password_hash=NULL, registered_at=NULL WHERE id=? AND classroom_id=?',
               (roster_student_id, classroom_id))
    db.commit()


def register_student(roster_student_id, password):
    db = get_db()
    db.execute("UPDATE roster_student SET password_hash=?, registered_at=datetime('now') "
               "WHERE id=? AND password_hash IS NULL",
               (generate_password_hash(password), roster_student_id))
    db.commit()


def check_student_password(student, password):
    return bool(student.get('password_hash')) and check_password_hash(student['password_hash'], password)


# --- Teams ---

def group_count(roster_student_id):
    return get_db().execute('SELECT COUNT(*) FROM group_member WHERE roster_student_id=?',
                            (roster_student_id,)).fetchone()[0]


def at_group_limit(classroom, roster_student_id):
    limit = classroom.get('max_groups_per_student')
    return limit is not None and group_count(roster_student_id) >= limit


def member_count(survey_id):
    return get_db().execute('SELECT COUNT(*) FROM group_member WHERE survey_id=?', (survey_id,)).fetchone()[0]


def group_full(classroom, survey_id):
    """True when the group already has classroom.max_group_size members (None = no limit)."""
    limit = classroom.get('max_group_size')
    return limit is not None and member_count(survey_id) >= limit


def is_member(survey_id, roster_student_id):
    return get_db().execute('SELECT 1 FROM group_member WHERE survey_id=? AND roster_student_id=?',
                            (survey_id, roster_student_id)).fetchone() is not None


def add_member(survey_id, student):
    """Add a roster student to a survey's group (no-op if already a member)."""
    db = get_db()
    if not is_member(survey_id, student['id']):
        db.execute('INSERT INTO group_member (survey_id, name, sis_code, roster_student_id) VALUES (?, ?, ?, ?)',
                   (survey_id, student['full_name'], student['sis_id'], student['id']))
    db.execute('DELETE FROM team_invite WHERE survey_id=? AND roster_student_id=?', (survey_id, student['id']))
    db.commit()


def my_groups(classroom_id, roster_student_id):
    rows = get_db().execute('''
        SELECT s.*,
            (SELECT COUNT(*) FROM group_member g2 WHERE g2.survey_id = s.id) AS member_count,
            (SELECT GROUP_CONCAT(g3.name, '; ') FROM group_member g3 WHERE g3.survey_id = s.id) AS member_names
        FROM group_member gm JOIN survey s ON gm.survey_id = s.id
        WHERE gm.roster_student_id = ? AND s.classroom_id = ?
        ORDER BY s.group_number
    ''', (roster_student_id, classroom_id)).fetchall()
    return [dict(r) for r in rows]


def leave_group(survey_id, roster_student_id):
    """Remove a student from a group. Returns an error message or None."""
    db = get_db()
    if not is_member(survey_id, roster_student_id):
        return 'You are not a member of this group.'
    count = db.execute('SELECT COUNT(*) FROM group_member WHERE survey_id=?', (survey_id,)).fetchone()[0]
    if count <= 1:
        return ("You're the only member of this group, so you can't leave it. "
                "Invite someone first, or delete the survey.")
    db.execute('DELETE FROM group_member WHERE survey_id=? AND roster_student_id=?', (survey_id, roster_student_id))
    db.commit()
    return None


def invite(classroom_id, survey_id, inviter_id, invitee_id):
    """Invite a classmate to a group. Returns an error message or None."""
    db = get_db()
    invitee = get_student(classroom_id, invitee_id)
    if not invitee or invitee['hidden']:
        return 'That student is not on the roster.'
    if is_member(survey_id, invitee_id):
        return f'{invitee["full_name"]} is already in this group.'
    try:
        db.execute('INSERT INTO team_invite (survey_id, roster_student_id, invited_by) VALUES (?, ?, ?)',
                   (survey_id, invitee_id, inviter_id))
        db.commit()
    except Exception:
        db.rollback()
        return f'{invitee["full_name"]} has already been invited.'
    return None


def pending_invites_for_student(roster_student_id):
    rows = get_db().execute('''
        SELECT ti.id, ti.survey_id, s.group_number, s.title, inv.full_name AS invited_by_name,
               (SELECT COUNT(*) FROM group_member gm WHERE gm.survey_id = ti.survey_id) AS member_count
        FROM team_invite ti
        JOIN survey s ON ti.survey_id = s.id
        LEFT JOIN roster_student inv ON ti.invited_by = inv.id
        WHERE ti.roster_student_id = ?
        ORDER BY ti.created_at
    ''', (roster_student_id,)).fetchall()
    return [dict(r) for r in rows]


def pending_invites_for_survey(survey_id):
    rows = get_db().execute('''
        SELECT ti.id, rs.full_name FROM team_invite ti
        JOIN roster_student rs ON ti.roster_student_id = rs.id
        WHERE ti.survey_id = ? ORDER BY rs.full_name
    ''', (survey_id,)).fetchall()
    return [dict(r) for r in rows]


def get_invite(invite_id):
    row = get_db().execute('SELECT * FROM team_invite WHERE id=?', (invite_id,)).fetchone()
    return dict(row) if row else None


def delete_invite(invite_id):
    db = get_db()
    db.execute('DELETE FROM team_invite WHERE id=?', (invite_id,))
    db.commit()


def set_seeking(roster_student_id, seeking, note):
    """Group finder: list (or unlist) a student, with an optional short note."""
    db = get_db()
    db.execute('UPDATE roster_student SET seeking_group=?, seeking_note=? WHERE id=?',
               (1 if seeking else 0, (note or '').strip()[:200] or None, roster_student_id))
    db.commit()


def group_finder(classroom_id, exclude_id=None):
    """Students who opted in to the group finder and still have no group, no pending invite and no
    pending request to join a group."""
    rows = get_db().execute('''
        SELECT rs.id, rs.full_name, rs.seeking_note FROM roster_student rs
        WHERE rs.classroom_id = ? AND rs.hidden = 0 AND rs.seeking_group = 1 AND rs.id != ?
          AND rs.password_hash IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM group_member gm WHERE gm.roster_student_id = rs.id)
          AND NOT EXISTS (SELECT 1 FROM team_invite ti WHERE ti.roster_student_id = rs.id)
          AND NOT EXISTS (SELECT 1 FROM join_request jr WHERE jr.roster_student_id = rs.id)
        ORDER BY rs.full_name COLLATE NOCASE
    ''', (classroom_id, exclude_id or 0)).fetchall()
    return [dict(r) for r in rows]


# --- Groups looking for members, and requests to join them ---

def set_group_seeking(survey_id, seeking, note):
    db = get_db()
    db.execute('UPDATE survey SET seeking_members=?, seeking_note=? WHERE id=?',
               (1 if seeking else 0, (note or '').strip()[:200] or None, survey_id))
    db.commit()


def groups_seeking(classroom):
    """Listed groups that still have room: number, title, note, member names, open spots."""
    db = get_db()
    limit = classroom.get('max_group_size')
    out = []
    for s in db.execute('SELECT id, group_number, title, seeking_note FROM survey WHERE classroom_id=? AND seeking_members=1 '
                        'ORDER BY group_number', (classroom['id'],)).fetchall():
        members = [r['name'] for r in db.execute('SELECT name FROM group_member WHERE survey_id=? ORDER BY name COLLATE NOCASE',
                                                  (s['id'],))]
        if limit and len(members) >= limit:
            continue
        out.append({'id': s['id'], 'group_number': s['group_number'], 'title': s['title'], 'note': s['seeking_note'],
                    'members': members, 'spots': (limit - len(members)) if limit else None})
    return out


def request_join(classroom, survey_id, student, note=''):
    """A student without a group asks to join a listed group. Returns an error message or None."""
    db = get_db()
    survey = db.execute('SELECT * FROM survey WHERE id=? AND classroom_id=?', (survey_id, classroom['id'])).fetchone()
    if not survey or not survey['seeking_members']:
        return 'That group is not looking for members right now.'
    if at_group_limit(classroom, student['id']):
        return "You're already in a group. Leave it first if you want to join another one."
    if group_full(classroom, survey_id):
        return 'That group is already full.'
    if db.execute('SELECT 1 FROM join_request WHERE roster_student_id=? AND from_survey_id IS NULL', (student['id'],)).fetchone():
        return 'You already asked to join a group. Withdraw that request first.'
    db.execute('INSERT INTO join_request (survey_id, roster_student_id, note) VALUES (?, ?, ?)',
               (survey_id, student['id'], (note or '').strip()[:200] or None))
    db.commit()
    return None


def get_join_request(request_id):
    row = get_db().execute('SELECT * FROM join_request WHERE id=?', (request_id,)).fetchone()
    return dict(row) if row else None


def delete_join_request(request_id):
    db = get_db()
    db.execute('DELETE FROM join_request WHERE id=?', (request_id,))
    db.commit()


def my_join_request(roster_student_id):
    row = get_db().execute('SELECT jr.*, s.group_number, s.title FROM join_request jr JOIN survey s ON jr.survey_id = s.id '
                           'WHERE jr.roster_student_id=? AND jr.from_survey_id IS NULL', (roster_student_id,)).fetchone()
    return dict(row) if row else None


def join_requests_for_survey(survey_id):
    """Requests to join this group: single students, and whole groups proposing to merge in
    (from_survey_id set; with that group's number, title and members)."""
    db = get_db()
    out = []
    for r in db.execute('SELECT jr.id, jr.note, jr.created_at, jr.from_survey_id, rs.full_name FROM join_request jr '
                        'JOIN roster_student rs ON jr.roster_student_id = rs.id WHERE jr.survey_id=? '
                        'ORDER BY jr.created_at', (survey_id,)).fetchall():
        req = dict(r)
        if req['from_survey_id']:
            g = db.execute('SELECT group_number, title FROM survey WHERE id=?', (req['from_survey_id'],)).fetchone()
            req['from_group'] = {'number': g['group_number'], 'title': g['title'],
                                 'members': [m['name'] for m in db.execute(
                                     'SELECT name FROM group_member WHERE survey_id=? ORDER BY name COLLATE NOCASE',
                                     (req['from_survey_id'],))]}
        out.append(req)
    return out


# --- Merging two small groups ---

def propose_merge(classroom, from_survey_id, to_survey_id, proposer, note=''):
    """A member of a group asks for their whole group to join another listed group. Returns an error or None."""
    db = get_db()
    target = db.execute('SELECT * FROM survey WHERE id=? AND classroom_id=?', (to_survey_id, classroom['id'])).fetchone()
    if not target or not target['seeking_members'] or to_survey_id == from_survey_id:
        return 'That group is not looking for members right now.'
    limit = classroom.get('max_group_size')
    together = member_count(from_survey_id) + member_count(to_survey_id)
    if limit and together > limit:
        return f'Together you would be {together} members, more than the {limit} allowed.'
    if db.execute('SELECT 1 FROM response WHERE survey_id=?', (from_survey_id,)).fetchone():
        return 'Your survey already has responses, so your group can\'t merge into another one. Ask your instructor.'
    if db.execute('SELECT 1 FROM join_request WHERE from_survey_id=?', (from_survey_id,)).fetchone():
        return 'Your group already proposed a merge. Withdraw it first.'
    db.execute('INSERT INTO join_request (survey_id, roster_student_id, note, from_survey_id) VALUES (?, ?, ?, ?)',
               (to_survey_id, proposer['id'], (note or '').strip()[:200] or None, from_survey_id))
    db.commit()
    return None


def outgoing_merge(from_survey_id):
    row = get_db().execute('SELECT jr.*, s.group_number, s.title FROM join_request jr JOIN survey s ON jr.survey_id = s.id '
                           'WHERE jr.from_survey_id=?', (from_survey_id,)).fetchone()
    return dict(row) if row else None


def after_join(classroom, survey_id, roster_student_id):
    """Someone joined a group: their own join requests are void, and a group that is now full stops
    being listed and drops its remaining requests (so those students can ask elsewhere)."""
    db = get_db()
    db.execute('DELETE FROM join_request WHERE roster_student_id=?', (roster_student_id,))
    if group_full(classroom, survey_id):
        db.execute('DELETE FROM join_request WHERE survey_id=?', (survey_id,))
        db.execute('UPDATE survey SET seeking_members=0 WHERE id=?', (survey_id,))
    db.commit()


def classmates(classroom_id, exclude_id=None):
    """Visible roster students (id + name only) for the invite picker."""
    rows = get_db().execute(
        'SELECT id, full_name FROM roster_student WHERE classroom_id=? AND hidden=0 AND id != ? '
        'ORDER BY full_name COLLATE NOCASE',
        (classroom_id, exclude_id or 0)).fetchall()
    return [dict(r) for r in rows]


# --- Frozen groups: the instructor places students ---

def groups_closed(classroom):
    """Students can't change groups themselves: groups are frozen (survey editing goes on) or surveys are locked."""
    return bool(classroom['groups_frozen'] or classroom['surveys_locked'])


def survey_is_blank(survey_id):
    """Nothing would be lost by deleting this survey: no responses, no comments from classmates, and its
    design is still the empty starting point (no question text, options or images; one part; no notifications)."""
    db = get_db()
    s = db.execute('SELECT * FROM survey WHERE id=?', (survey_id,)).fetchone()
    if not s or s['external'] or s['reminder_plan'] or s['part2_from'] is not None or s['early_open']:
        return False
    if db.execute('SELECT 1 FROM response WHERE survey_id=?', (survey_id,)).fetchone():
        return False
    if db.execute("SELECT 1 FROM feedback WHERE survey_id=? AND TRIM(body) != ''", (survey_id,)).fetchone():
        return False
    if db.execute('SELECT COUNT(*) FROM survey_question WHERE survey_id=?', (survey_id,)).fetchone()[0] > 1:
        return False
    filled = db.execute('''SELECT 1 FROM arm_question aq JOIN survey_arm sa ON aq.arm_id = sa.id
                           WHERE sa.survey_id=? AND (TRIM(aq.question_text) != '' OR aq.image_filename IS NOT NULL
                                 OR aq.config IS NOT NULL
                                 OR EXISTS (SELECT 1 FROM arm_question_option o WHERE o.arm_question_id = aq.id))''',
                        (survey_id,)).fetchone()
    intro = db.execute("SELECT 1 FROM survey_arm WHERE survey_id=? AND TRIM(COALESCE(intro_text, '')) != ''",
                       (survey_id,)).fetchone()
    return not filled and not intro


def new_solo_group(classroom, student):
    """A new group (blank survey, next group number) whose only member is this student."""
    from models.survey import create_survey, next_group_number
    from routes.builder import blank_design
    number = next_group_number(classroom['id'])
    arms, questions = blank_design()
    survey_id = create_survey(classroom['id'], f'Group {number} survey', number, arms, questions,
                              [{'name': student['full_name'], 'sis_code': student['sis_id'], 'roster_student_id': student['id']}])
    return survey_id, number


def place_student(classroom, student, target_id=None, no_group=False):
    """The instructor puts a student in a group (target_id) or in a new group of their own (None), taking
    them out of any other group. Works while groups are frozen and may go over the size limit.
    no_group=True only takes them out of their groups (e.g. a student who won't present): their sign-up,
    drafts and own comment assignments stay.

    A group the student leaves keeps its other members. If they were its only member, its survey is
    deleted only when nothing would be lost (survey_is_blank); otherwise nothing changes and an error
    explains why. Returns (message, error)."""
    from models.survey import delete_survey, get_survey
    db = get_db()
    current = [r['survey_id'] for r in db.execute(
        'SELECT gm.survey_id FROM group_member gm JOIN survey s ON gm.survey_id = s.id '
        'WHERE gm.roster_student_id=? AND s.classroom_id=?', (student['id'], classroom['id']))]
    number = lambda sid: db.execute('SELECT group_number FROM survey WHERE id=?', (sid,)).fetchone()[0]
    if no_group:
        target_id = None
        if not current:
            return None, f'{student["full_name"]} is not in any group.'
    elif target_id is not None:
        target = get_survey(target_id)
        if not target or target['classroom_id'] != classroom['id']:
            return None, 'That group does not exist.'
        if current == [target_id]:
            return None, f'{student["full_name"]} is already in Group {target["group_number"]}.'
    to_delete = []
    for sid in current:
        if sid != target_id and member_count(sid) <= 1:
            if not survey_is_blank(sid):
                n = number(sid)
                return None, (f'{student["full_name"]} is the only member of Group {n}, which already has survey work, '
                              f'responses or comments from classmates, so nothing was changed. To move them anyway, '
                              f'download what you need, delete Group {n} in Manage Surveys, then place them again.')
            to_delete.append(sid)
    if no_group:
        target_number = None
    elif target_id is None:
        target_id, target_number = new_solo_group(classroom, student)
    else:
        add_member(target_id, student)
        target_number = target['group_number']
    left = []
    for sid in current:
        if sid != target_id:
            left.append(number(sid))
            db.execute('DELETE FROM group_member WHERE survey_id=? AND roster_student_id=?', (sid, student['id']))
    if not no_group:
        db.execute('DELETE FROM team_invite WHERE roster_student_id=?', (student['id'],))
        db.execute('UPDATE roster_student SET seeking_group=0 WHERE id=?', (student['id'],))
    db.commit()
    deleted = []
    for sid in to_delete:
        deleted.append(number(sid))
        delete_survey(sid)  # blank: no images to clean up
    if no_group:
        return (f'{student["full_name"]} is now in no group (taken out of Group {", ".join(map(str, left))}'
                + ('; that empty group was deleted, so nobody is assigned to comment on it' if deleted else '') + ').'), None
    after_join(classroom, target_id, student['id'])
    msg = f'{student["full_name"]} is now in Group {target_number}'
    if left:
        msg += f' (moved out of Group {", ".join(map(str, left))}'
        msg += f'; that empty group was deleted)' if deleted else ')'
    limit = classroom['max_group_size']
    size = member_count(target_id)
    if limit and size > limit:
        msg += f'. Group {target_number} now has {size} members, more than the limit of {limit}'
    return msg + '.', None


def students_without_group(classroom_id):
    """Visible students in no group, split into (signed up with no pending invite, signed up with an invite,
    not signed up)."""
    db = get_db()
    rows = db.execute('''SELECT rs.*, (SELECT COUNT(*) FROM team_invite ti WHERE ti.roster_student_id = rs.id) AS invites
                         FROM roster_student rs WHERE rs.classroom_id=? AND rs.hidden=0
                         AND NOT EXISTS (SELECT 1 FROM group_member gm WHERE gm.roster_student_id = rs.id)
                         ORDER BY rs.full_name COLLATE NOCASE''', (classroom_id,)).fetchall()
    ready = [dict(r) for r in rows if r['registered_at'] and not r['invites']]
    invited = [dict(r) for r in rows if r['registered_at'] and r['invites']]
    absent = [dict(r) for r in rows if not r['registered_at']]
    return ready, invited, absent


# --- Removing students who dropped, with cleanup ---

def _group_outcomes(classroom_id, student_id):
    """What removing this student would do to each of their groups: [(survey_id, group_number, 'leave' | 'delete' | 'keep')].
    leave: others stay in it; delete: they're its only member and its survey is blank; keep: only member, but it has work."""
    db = get_db()
    out = []
    for g in db.execute('SELECT s.id, s.group_number FROM group_member gm JOIN survey s ON gm.survey_id = s.id '
                        'WHERE gm.roster_student_id=? AND s.classroom_id=? ORDER BY s.group_number', (student_id, classroom_id)):
        if member_count(g['id']) > 1:
            out.append((g['id'], g['group_number'], 'leave'))
        else:
            out.append((g['id'], g['group_number'], 'delete' if survey_is_blank(g['id']) else 'keep'))
    return out


def describe_removal(classroom_id, student):
    """For the confirmation list: the student plus what removing them would do."""
    db = get_db()
    words = {'leave': 'taken out of Group {n} (the others stay)', 'delete': 'Group {n}, their solo group, is deleted (blank)',
             'keep': 'Group {n} is kept (they are its only member but it has work; delete it in Manage Surveys if needed)'}
    written = db.execute("SELECT COUNT(*) FROM feedback WHERE roster_student_id=? AND sent_at IS NOT NULL", (student['id'],)).fetchone()[0]
    return dict(student, effects=[words[o].format(n=n) for _, n, o in _group_outcomes(classroom_id, student['id'])],
                comments_sent=written)


def missing_from_file(classroom_id, students):
    """Active roster students whose ID isn't in an uploaded roster (they may have dropped), with what removing them would do."""
    ids = {s['sis_id'] for s in students}
    rows = get_db().execute('SELECT * FROM roster_student WHERE classroom_id=? AND hidden=0 ORDER BY full_name COLLATE NOCASE',
                            (classroom_id,)).fetchall()
    return [describe_removal(classroom_id, dict(r)) for r in rows if r['sis_id'] not in ids]


def remove_student(classroom, student):
    """A student dropped: hide them (they can't sign in; their past answers and sent comments stay in the data), and
    clean up so they don't hold places: out of their groups (a blank solo group is deleted, so nobody comments on it;
    a solo group with work is kept and reported), no comment assignments of their own, no pending invites or requests.
    Call refill_assignments() afterwards so classmates and groups get replacements. Returns {'deleted', 'left', 'kept'}
    as lists of group numbers."""
    from models.survey import delete_survey
    db = get_db()
    result = {'deleted': [], 'left': [], 'kept': []}
    for sid, number, outcome in _group_outcomes(classroom['id'], student['id']):
        if outcome == 'leave':
            db.execute('DELETE FROM group_member WHERE survey_id=? AND roster_student_id=?', (sid, student['id']))
            db.commit()
            result['left'].append(number)
        elif outcome == 'delete':
            delete_survey(sid)
            result['deleted'].append(number)
        else:
            result['kept'].append(number)
    db.execute('DELETE FROM review_assignment WHERE roster_student_id=?', (student['id'],))
    db.execute('DELETE FROM join_request WHERE roster_student_id=?', (student['id'],))
    db.execute('DELETE FROM team_invite WHERE roster_student_id=?', (student['id'],))
    db.execute('UPDATE roster_student SET hidden=1, seeking_group=0 WHERE id=?', (student['id'],))
    db.commit()
    return result


def refill_assignments(classroom):
    """After students leave or come back: if reviewers exist, top everyone up and even out group loads
    (only assignments nobody has written on move)."""
    from models import feedback as fb
    if fb.assignments_exist(classroom['id']):
        fb.ensure_assignments(classroom)
        fb.rebalance_assignments(classroom)


def removal_message(names_results):
    """One flash message for [(name, result)] from remove_student."""
    msg = f'Removed {len(names_results)} student(s): {"; ".join(n for n, _ in names_results)}.'
    deleted = sorted(g for _, r in names_results for g in r['deleted'])
    kept = sorted(g for _, r in names_results for g in r['kept'])
    if deleted:
        msg += f' Blank solo group(s) deleted: {", ".join(map(str, deleted))}.'
    if kept:
        msg += (f' Kept because they have work: Group {", ".join(map(str, kept))} (no active members now; '
                f'delete them in Manage Surveys if they won\'t present).')
    return msg + ' Their past answers and sent comments stay in your downloads; Restore brings them back (without a group).'


def required_targets(classroom):
    """{roster_student_id: [survey_id, ...]}: the groups each student must comment on (their first `reviews_required`
    assignments, the ones the lobby marks "required"), sorted by group number."""
    db = get_db()
    needed = classroom['reviews_required'] or 0
    out = {}
    for st in db.execute('SELECT id FROM roster_student WHERE classroom_id=?', (classroom['id'],)).fetchall():
        rows = db.execute('SELECT ra.survey_id, s.group_number FROM review_assignment ra JOIN survey s ON ra.survey_id = s.id '
                          'WHERE ra.roster_student_id=? ORDER BY ra.id LIMIT ?', (st['id'], needed)).fetchall()
        if rows:
            out[st['id']] = [r['survey_id'] for r in sorted(rows, key=lambda r: r['group_number'])]
    return out
