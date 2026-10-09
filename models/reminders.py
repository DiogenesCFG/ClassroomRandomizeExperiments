"""Two-part surveys and notifications (nudges): calendar events and push notifications.

**Parts.** By default a survey has one part, run live in class. It is two-part when
`survey.part2_from` is set: questions from that index on are part 2. Each part has a "when"
(`part1_when` / `part2_when`):
- 'live': in class, in the live session's sequence (default for part 1);
- 'class': in class, but launched separately by the instructor (e.g. at the start of class);
- 'remote': answered from the lobby between the part's dates (`partN_open_date`/`_close_date`,
  and the moments `partN_open_utc`/`_close_utc` in the group's time zone), once approved.
Part 2 is only for students who answered part 1, in the same arm. The host activates one part
at a time (`survey.active_part`); `part1_ran`/`part2_ran` record what already ran, so the live
sequence skips it.

**Notifications.** Independent of parts. Each arm can have its own plan (`survey.reminder_plan`,
JSON by arm position): a note respondents read before turning them on, and notifications (message,
time of day, the chosen dates). `plan['tz']` is '' (floating: 10:00 means 10:00 wherever the phone
is) or an IANA time zone. After answering part 1, respondents add them to their calendar (.ics on
iPhone and computers, Google Calendar links on Android) or get push notifications
(models/push.py). The instructor approves the plan and any remote dates; editing afterwards
needs approval again (`reminders_approved` holds a hash of what was approved). Downloads, link
taps and notification sign-ups are recorded in `reminder_action`.
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from models import rules
from models.db import get_db

MAX_RULES_PER_ARM = 10
MAX_EVENTS_PER_ARM = 60
MESSAGE_LENGTH = 150
NOTE_LENGTH = 1000
DEFAULT_TIME = '09:00'
EVENT_MINUTES = 10
WHENS = ('live', 'class', 'remote')
WHEN_NAMES = {'live': 'in class, during the live session', 'class': 'in class, launched separately by the instructor',
              'remote': 'remote, from the lobby'}
_TIME = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


# --- Parts ---

def part2_start(survey):
    """Index of the first part-2 question, or None for a one-part survey."""
    value = survey.get('part2_from') if survey else None
    return None if value is None or survey.get('external') else int(value)


def question_part(survey, question):
    start = part2_start(survey)
    return 2 if start is not None and question['question_index'] >= start else 1


def is_two_part(survey):
    return part2_start(survey) is not None


def part_when(survey, part):
    """'live', 'class' or 'remote'. A one-part survey always runs live."""
    if not is_two_part(survey):
        return 'live'
    value = survey.get(f'part{part}_when')
    return value if value in WHENS else ('live' if part == 1 else 'remote')


def sequence_part(survey):
    """The part that runs in the live session's sequence, or None (two-part, neither part 'live')."""
    if not is_two_part(survey):
        return 1
    return next((p for p in (1, 2) if part_when(survey, p) == 'live'), None)


def remote_parts(survey):
    return [p for p in (1, 2) if is_two_part(survey) and part_when(survey, p) == 'remote']


def part_ran(survey, part):
    return bool(survey.get(f'part{part}_ran'))


def part_dates(survey, part):
    """(open date, close date) of a remote part, as dates (or None)."""
    return _date(survey.get(f'part{part}_open_date')), _date(survey.get(f'part{part}_close_date'))


def part_problems(survey):
    """"Still to do" items for the split itself: each part needs questions, a part-2 question
    can't depend on a part-1 answer (the parts are answered at different times), and the two
    parts can't both run in the live session (they'd follow each other right away)."""
    start = part2_start(survey)
    if start is None:
        return []
    questions = survey.get('questions', [])
    todo = []
    if not 1 <= start < len(questions):
        return ['Two-part survey: each part needs at least one question. Choose where part 2 starts.']
    for q in questions[start:]:
        cond = q.get('cond_question')
        if cond is not None and cond < start:
            todo.append(f'Question {q["question_index"] + 1} is in part 2, so it can\'t depend on an answer to '
                        f'Question {cond + 1} (part 1). Remove the condition or move the split.')
    for arm in survey.get('arms', []):
        for part, qs in ((1, questions[:start]), (2, questions[start:])):
            if not any(rules.shown_in_arm(q, arm['arm_index']) for q in qs):
                todo.append(f'{arm["label"]} sees no questions in part {part}.')
    if part_when(survey, 1) == 'live' and part_when(survey, 2) == 'live':
        todo.append('Both parts are set to run in the live session, so they would follow each other right away. '
                    'Set one of them to "in class, launched separately" or "remote".')
    return todo


def part_window(survey, part):
    """A remote part's state: 'none' (not remote, or no dates yet), 'waiting' (not approved yet),
    'upcoming', 'open' or 'closed'."""
    if part not in remote_parts(survey):
        return 'none'
    opens, closes = _utc(survey.get(f'part{part}_open_utc')), _utc(survey.get(f'part{part}_close_utc'))
    if not opens or not closes:
        return 'none'
    if approval_state(survey) != 'approved':
        return 'waiting'
    now = datetime.now(timezone.utc)
    if now < opens:
        return 'upcoming'
    return 'open' if now <= closes else 'closed'


def _utc(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def answered_part(db, participant_id, survey, part):
    """Has this participant answered any question of this part?"""
    start = part2_start(survey)
    if start is None:
        cond, args = '', ()
    elif part == 1:
        cond, args = ' AND sq.question_index < ?', (start,)
    else:
        cond, args = ' AND sq.question_index >= ?', (start,)
    return db.execute('SELECT 1 FROM response r JOIN survey_question sq ON r.question_id = sq.id '
                      'WHERE r.participant_id=? AND r.survey_id=?' + cond + ' LIMIT 1',
                      (participant_id, survey['id']) + args).fetchone() is not None


def respondent_arm(db, survey_id, participant_id):
    """The arm position a participant answered in (from their stored answers), or None."""
    row = db.execute('SELECT sa.arm_index FROM response r JOIN survey_arm sa ON r.arm_id = sa.id '
                     'WHERE r.survey_id=? AND r.participant_id=? LIMIT 1', (survey_id, participant_id)).fetchone()
    return row['arm_index'] if row else None


def save_parts(survey_id, parts):
    """The two-part card's settings: each part's "when" and, for remote parts, dates."""
    db = get_db()
    for p in (1, 2):
        data = parts.get(str(p)) or parts.get(p) or {}
        when = data.get('when') if data.get('when') in WHENS else ('live' if p == 1 else 'remote')
        values = [when, _iso(data.get('open_date')), _iso(data.get('close_date')),
                  str(data.get('open_utc') or '')[:40] or None, str(data.get('close_utc') or '')[:40] or None]
        db.execute(f'UPDATE survey SET part{p}_when=?, part{p}_open_date=?, part{p}_close_date=?, '
                   f'part{p}_open_utc=?, part{p}_close_utc=? WHERE id=?', values + [survey_id])
        if p == 2:
            time = str(data.get('time') or DEFAULT_TIME)[:5]
            db.execute('UPDATE survey SET part2_time=? WHERE id=?', (time, survey_id))
    db.commit()


def _iso(value):
    value = str(value or '')[:10]
    return value if _date(value) else None


# --- The notification plan ---

def _date(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def valid_tz(name):
    """An IANA time zone name ('America/Los_Angeles') that this server knows, else ''."""
    if not name or not isinstance(name, str) or len(name) > 64:
        return ''
    try:
        ZoneInfo(name)
    except (ValueError, KeyError, OSError):
        return ''
    return name


def tz_label(name):
    return name.split('/')[-1].replace('_', ' ') + ' time' if name else ''


def _rule_dates(r):
    """A notification's dates: the chosen list, or (older plans) first/last date every N days."""
    if isinstance(r.get('dates'), list):
        found = sorted({d.isoformat() for d in (_date(x) for x in r['dates'][:MAX_EVENTS_PER_ARM * 2]) if d})
        return found
    start, end = _date(r.get('start')), _date(r.get('end'))
    if not start:
        return []
    end = end or start
    try:
        every = max(int(r.get('every') or 1), 1)
    except (TypeError, ValueError):
        every = 1
    return [(start + timedelta(days=d)).isoformat() for d in range(0, max((end - start).days + 1, 0), every)]


def clean_plan(data, arm_count):
    """The plan as posted by the builder, trimmed to known fields and sizes."""
    arms = []
    data = data if isinstance(data, dict) else {}
    raw_arms = data.get('arms') or []
    for ai in range(arm_count):
        raw = raw_arms[ai] if ai < len(raw_arms) and isinstance(raw_arms[ai], dict) else {}
        rules_out = []
        for r in (raw.get('rules') or [])[:MAX_RULES_PER_ARM]:
            if not isinstance(r, dict):
                continue
            rules_out.append({
                'message': ' '.join(str(r.get('message') or '').split())[:MESSAGE_LENGTH],
                'time': str(r.get('time') or DEFAULT_TIME)[:5],
                'dates': _rule_dates(r),
            })
        arms.append({'note': str(raw.get('note') or '').strip()[:NOTE_LENGTH], 'rules': rules_out})
    return {'tz': valid_tz(data.get('tz')), 'arms': arms}


def load_plan(survey):
    """The stored plan with one entry per arm (missing arms get an empty plan)."""
    try:
        data = json.loads(survey.get('reminder_plan') or '{}')
    except (TypeError, ValueError):
        data = {}
    if 'arms' in survey:
        count = len(survey['arms'])
    else:  # a bare survey row: trust the stored plan's arms
        count = len(data.get('arms') or []) if isinstance(data, dict) else 0
    return clean_plan(data, count)


def has_reminders(plan):
    return any(a['rules'] or a['note'] for a in plan['arms'])


def needs_approval(survey):
    return bool(remote_parts(survey)) or has_reminders(load_plan(survey))


def occurrences(rule):
    """The dates a notification is sent on."""
    return [d for d in (_date(x) for x in rule.get('dates') or []) if d]


def runs(dates):
    """Split sorted dates into runs with a constant gap (daily, every 2 days, ...), so each run
    can be one repeating calendar event: [(first, count, every_days)]."""
    out = []
    i = 0
    while i < len(dates):
        if i + 1 < len(dates):
            gap = (dates[i + 1] - dates[i]).days
            j = i + 1
            while j + 1 < len(dates) and (dates[j + 1] - dates[j]).days == gap:
                j += 1
            out.append((dates[i], j - i + 1, gap))
            i = j + 1
        else:
            out.append((dates[i], 1, 1))
            i += 1
    return out


def plan_problems(survey, classroom):
    """"Still to do" items for remote parts' dates and the notifications (block approval and early deployment)."""
    if not survey or survey.get('external'):
        return []
    limit = _date(classroom.get('reminders_until')) if classroom else None
    todo = []
    for p in remote_parts(survey):
        opens, closes = part_dates(survey, p)
        if not opens or not closes:
            todo.append(f'Part {p} is remote: choose when it opens and closes.')
        elif closes < opens:
            todo.append(f'Part {p} closes before it opens. Check its dates.')
        elif limit and closes > limit:
            todo.append(f'Part {p} closes after {nice_date(limit)}, the latest date your instructor allows.')
    if remote_parts(survey) == [1, 2]:
        (o1, _), (o2, _) = part_dates(survey, 1), part_dates(survey, 2)
        if o1 and o2 and o2 < o1:
            todo.append('Part 2 opens before part 1. Check their dates.')
    if 2 in remote_parts(survey) and not _TIME.match(survey.get('part2_time') or DEFAULT_TIME):
        todo.append('Part 2: choose the time of its "part 2 is open" reminder.')
    plan = load_plan(survey)
    for ai, arm_plan in enumerate(plan['arms']):
        label = survey['arms'][ai]['label'] if ai < len(survey.get('arms', [])) else f'Arm {ai + 1}'
        events = 0
        for ri, rule in enumerate(arm_plan['rules']):
            name = f'Notification {ri + 1} in {label}'
            dates = occurrences(rule)
            if not rule['message']:
                todo.append(f'{name}: write its message.')
            if not dates:
                todo.append(f'{name}: pick the days it is sent.')
            elif limit and dates[-1] > limit:
                todo.append(f'{name}: it has days after {nice_date(limit)}, the latest date your instructor allows.')
            if not _TIME.match(rule['time']):
                todo.append(f'{name}: choose a time of day.')
            events += len(dates)
        if events > MAX_EVENTS_PER_ARM:
            todo.append(f'{label}: {events} notifications in total is too many (at most {MAX_EVENTS_PER_ARM}).')
    return todo


def plan_hash(survey):
    """What the instructor approves: the notifications, the time zone, and remote parts' dates."""
    content = {'plan': load_plan(survey),
               'parts': [[p, survey.get(f'part{p}_open_date'), survey.get(f'part{p}_close_date')]
                         for p in remote_parts(survey)],
               'part2_time': survey.get('part2_time') if 2 in remote_parts(survey) else None}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]


def approval_state(survey):
    """'none' (nothing to approve), 'approved', 'pending', or 'changed' (edited after approval)."""
    if not needs_approval(survey):
        return 'none'
    approved = survey.get('reminders_approved')
    if approved and approved == plan_hash(survey):
        return 'approved'
    return 'changed' if approved else 'pending'


def save_plan(survey_id, plan):
    db = get_db()
    db.execute('UPDATE survey SET reminder_plan=? WHERE id=?',
               (json.dumps(plan) if has_reminders(plan) or plan.get('tz') else None, survey_id))
    db.commit()


def set_approval(survey, approve):
    db = get_db()
    db.execute('UPDATE survey SET reminders_approved=? WHERE id=?',
               (plan_hash(survey) if approve else None, survey['id']))
    db.commit()


# --- What a respondent adds to their calendar ---

def nice_date(d):
    return f'{d:%a} {d:%b} {d.day}' if d else ''


def nice_time(hhmm):
    try:
        t = datetime.strptime(hhmm, '%H:%M')
    except (TypeError, ValueError):
        return hhmm or ''
    return t.strftime('%I:%M %p').lstrip('0').replace(':00 ', ' ')


def calendar_items(survey, arm_index, classroom, lobby_url):
    """The events for one arm: each notification (one item per run of evenly spaced days, so a
    run is one repeating event), then "Part 2 is open" when part 2 is remote. Each item: key,
    summary, description, first/last date, count, every (days), time, tz, url."""
    items = []
    plan = load_plan(survey)
    arm_plan = plan['arms'][arm_index] if arm_index is not None and 0 <= arm_index < len(plan['arms']) else {'rules': []}
    footer = f'Reminder from {classroom["name"]}.'
    for ri, rule in enumerate(arm_plan['rules']):
        dates = occurrences(rule)
        if not rule['message'] or not dates or not _TIME.match(rule['time']):
            continue
        for k, (first, count, every) in enumerate(runs(dates)):
            items.append({'key': f'{ri}' if k == 0 else f'{ri}-{k}', 'summary': rule['message'], 'description': footer,
                          'first': first, 'last': first + timedelta(days=every * (count - 1)), 'count': count,
                          'every': every, 'time': rule['time'], 'tz': plan['tz'], 'url': None})
    opens, closes = part_dates(survey, 2)
    # "Part 2 is open" only while that's still ahead (someone adding them later doesn't need it)
    if 2 in remote_parts(survey) and opens and opens >= date.today():
        items.append({'key': 'p2', 'summary': f'Part 2 of the survey "{survey["title"]}" is open',
                      'description': (f'Answer it from your class lobby: {lobby_url}'
                                      + (f' (open until {nice_date(closes)})' if closes else '') + f'\n{footer}'),
                      'first': opens, 'last': opens, 'count': 1, 'every': 1,
                      'time': survey.get('part2_time') or DEFAULT_TIME, 'tz': plan['tz'], 'url': lobby_url})
    for item in items:
        item['when'] = when_text(item)
    return items


def item_label(key):
    """A calendar item's key for exports: 'reminder 2' for '1' or '1-3', 'part 2 is open' for p2."""
    key = str(key or '')
    if key == 'p2':
        return 'part 2 is open'
    head = key.split('-')[0]
    return f'notification {int(head) + 1}' if head.isdigit() else key


def when_text(item):
    at = f'at {nice_time(item["time"])}' + (f' ({tz_label(item["tz"])})' if item.get('tz') else '')
    if item['count'] == 1:
        return f'{nice_date(item["first"])} {at}'
    every = 'daily' if item['every'] == 1 else f'every {item["every"]} days'
    return f'{every} from {nice_date(item["first"])} to {nice_date(item["last"])} {at} ({item["count"]} times)'


def _start(item):
    hh, mm = (int(x) for x in item['time'].split(':'))
    return datetime(item['first'].year, item['first'].month, item['first'].day, hh, mm)


def local_times(item):
    """Each occurrence as a naive local datetime (in the item's time zone, or the phone's)."""
    start = _start(item)
    return [start + timedelta(days=k * item['every']) for k in range(item['count'])]


def utc_times(item, fallback_tz):
    """Each occurrence in UTC: the item's own time zone, else (floating) fallback_tz, e.g. the phone's."""
    zone = ZoneInfo(item.get('tz') or valid_tz(fallback_tz) or 'UTC')
    return [t.replace(tzinfo=zone).astimezone(timezone.utc) for t in local_times(item)]


def _rrule(item):
    if item['count'] == 1:
        return None
    return f'RRULE:FREQ=DAILY;INTERVAL={item["every"]};COUNT={item["count"]}'


def _ics_text(value):
    return (str(value).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\r\n', '\\n').replace('\n', '\\n'))


def _fold(line):
    """iCalendar lines are at most 75 bytes; longer ones continue on lines starting with a space."""
    out, current = [], ''
    for ch in line:
        if len((current + ch).encode('utf-8')) > (75 if not out else 74):
            out.append(current)
            current = ''
        current += ch
    out.append(current)
    return '\r\n '.join(out)


def _offset(delta):
    minutes = int(delta.total_seconds() // 60)
    sign = '+' if minutes >= 0 else '-'
    return f'{sign}{abs(minutes) // 60:02d}{abs(minutes) % 60:02d}'


def _vtimezone(name, first, last):
    """A VTIMEZONE for `name` covering the dates first..last: its offset at the start, then each
    change (daylight saving) in between, found hour by hour."""
    zone = ZoneInfo(name)
    t = datetime(first.year, first.month, first.day, tzinfo=timezone.utc) - timedelta(days=2)
    end = datetime(last.year, last.month, last.day, tzinfo=timezone.utc) + timedelta(days=2)
    current = t.astimezone(zone)
    lines = ['BEGIN:VTIMEZONE', f'TZID:{name}',
             'BEGIN:DAYLIGHT' if current.dst() else 'BEGIN:STANDARD', 'DTSTART:19700101T000000',
             f'TZOFFSETFROM:{_offset(current.utcoffset())}', f'TZOFFSETTO:{_offset(current.utcoffset())}',
             f'TZNAME:{current.tzname()}', 'END:DAYLIGHT' if current.dst() else 'END:STANDARD']
    while t < end:
        t += timedelta(hours=1)
        here = t.astimezone(zone)
        if here.utcoffset() != current.utcoffset():
            kind = 'DAYLIGHT' if here.dst() else 'STANDARD'
            # DTSTART is the moment of the change in the old offset's local time (e.g. 02:00 EDT)
            changed_at = (t + current.utcoffset()).replace(tzinfo=None)
            lines += [f'BEGIN:{kind}', f'DTSTART:{changed_at:%Y%m%dT%H%M%S}',
                      f'TZOFFSETFROM:{_offset(current.utcoffset())}', f'TZOFFSETTO:{_offset(here.utcoffset())}',
                      f'TZNAME:{here.tzname()}', f'END:{kind}']
            current = here
    lines.append('END:VTIMEZONE')
    return lines


def ics(items, survey_id, arm_index, calendar_name):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Classroom Randomize Experiments//Reminders//EN',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', f'X-WR-CALNAME:{_ics_text(calendar_name)}']
    zones = {}
    for item in items:
        if item.get('tz'):
            first, last = zones.get(item['tz'], (item['first'], item['last']))
            zones[item['tz']] = (min(first, item['first']), max(last, item['last']))
    for name, (first, last) in zones.items():
        lines += _vtimezone(name, first, last)
    for item in items:
        start = _start(item)
        tzid = f';TZID={item["tz"]}' if item.get('tz') else ''
        lines += ['BEGIN:VEVENT',
                  f'UID:reminder-{survey_id}-{arm_index}-{item["key"]}@classroom-experiments',
                  f'DTSTAMP:{stamp}',
                  f'DTSTART{tzid}:{start:%Y%m%dT%H%M%S}',
                  f'DTEND{tzid}:{start + timedelta(minutes=EVENT_MINUTES):%Y%m%dT%H%M%S}',
                  f'SUMMARY:{_ics_text(item["summary"])}',
                  f'DESCRIPTION:{_ics_text(item["description"])}']
        if _rrule(item):
            lines.append(_rrule(item))
        if item.get('url'):
            lines.append(f'URL:{item["url"]}')
        lines += ['BEGIN:VALARM', 'ACTION:DISPLAY', f'DESCRIPTION:{_ics_text(item["summary"])}',
                  'TRIGGER:PT0M', 'END:VALARM', 'END:VEVENT']
    lines.append('END:VCALENDAR')
    return '\r\n'.join(_fold(line) for line in lines) + '\r\n'


def google_url(item):
    """A Google Calendar "add event" link for one item (a recurring event for a repeating reminder).
    With a time zone, ctz pins the times to it; without, they're in the calendar's own zone."""
    start = _start(item)
    params = [('action', 'TEMPLATE'), ('text', item['summary']),
              ('dates', f'{start:%Y%m%dT%H%M%S}/{start + timedelta(minutes=EVENT_MINUTES):%Y%m%dT%H%M%S}'),
              ('details', item['description'])]
    if _rrule(item):
        params.append(('recur', _rrule(item)))
    if item.get('tz'):
        params.append(('ctz', item['tz']))
    return 'https://calendar.google.com/calendar/render?' + '&'.join(f'{k}={quote(v, safe="")}' for k, v in params)


# --- Tracking ---

DEVICES = ('ios', 'android', 'desktop')


def log_action(survey_id, participant_id, arm_index, method, item=None, device=None):
    db = get_db()
    db.execute('INSERT INTO reminder_action (survey_id, participant_id, arm_index, method, item, device) '
               'VALUES (?, ?, ?, ?, ?, ?)',
               (survey_id, participant_id, arm_index, method, None if item is None else str(item),
                device if device in DEVICES else None))
    db.commit()


def actions_by_participant(survey_id):
    """{participant_id: {'ics': first time, 'google': set of items, 'done': first time,
    'push': first sign-up time, 'push_sent': n, 'push_opened': n}}."""
    out = {}

    def entry(pid):
        return out.setdefault(pid, {'ics': None, 'google': set(), 'done': None, 'push': None,
                                    'push_sent': 0, 'push_opened': 0})
    db = get_db()
    for r in db.execute('SELECT * FROM reminder_action WHERE survey_id=? ORDER BY created_at, id', (survey_id,)):
        a = entry(r['participant_id'])
        if r['method'] in ('ics', 'done', 'push') and not a[r['method']]:
            a[r['method']] = r['created_at']
        elif r['method'] == 'google':
            a['google'].add(r['item'])
    for r in db.execute('SELECT ps.participant_id, SUM(pm.status = \'sent\') AS sent, '
                        'SUM(pm.clicked_at IS NOT NULL) AS opened FROM push_message pm '
                        'JOIN push_subscription ps ON pm.subscription_id = ps.id WHERE ps.survey_id=? '
                        'GROUP BY ps.participant_id', (survey_id,)):
        a = entry(r['participant_id'])
        a['push_sent'], a['push_opened'] = r['sent'] or 0, r['opened'] or 0
    return out
