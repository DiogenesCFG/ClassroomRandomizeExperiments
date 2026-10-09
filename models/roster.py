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
    return {'groups': groups, 'member_of': member_of, 'invited_to': invited_to}


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


def classmates(classroom_id, exclude_id=None):
    """Visible roster students (id + name only) for the invite picker."""
    rows = get_db().execute(
        'SELECT id, full_name FROM roster_student WHERE classroom_id=? AND hidden=0 AND id != ? '
        'ORDER BY full_name COLLATE NOCASE',
        (classroom_id, exclude_id or 0)).fetchall()
    return [dict(r) for r in rows]
