"""A realistic demo classroom for the guide screenshots (fresh database)."""
import io
from datetime import date, datetime, timedelta, timezone
from app import create_app
app = create_app()
app.config['TESTING'] = True

NAMES = ['Martinez, Sofia', 'Chen, Liam', 'Johnson, Ava', 'Patel, Noah', 'Kim, Emma', 'Garcia, Mateo', 'Nguyen, Olivia',
         'Brown, Lucas', 'Lopez, Isabella', 'Wilson, Ethan', 'Singh, Mia', 'Anderson, James', 'Thomas, Amelia',
         'Hernandez, Benjamin', 'Moore, Harper', 'Jackson, Elijah', 'Lee, Evelyn', 'Walker, Henry', 'Hall, Abigail',
         'Young, Daniel', 'Allen, Ella', 'King, Jack', 'Wright, Scarlett', 'Scott, Leo']
host = app.test_client()
roster = 'Student,SIS User ID\n' + ''.join(f'"{n}",91200{i:04d}\n' for i, n in enumerate(NAMES, 1))
host.post('/c/create', data={'code': 'ECON101', 'name': 'Behavioral Economics', 'host_password': 'host', 'host_password_confirm': 'host',
                             'classroom_password': 'nudge', 'classroom_password_confirm': 'nudge', 'max_groups': '1',
                             'roster_file': (io.BytesIO(roster.encode()), 'r.csv')}, content_type='multipart/form-data')
host.post('/c/host-join', data={'code': 'ECON101', 'password': 'host'})


def student(i):
    c = app.test_client()
    c.post('/c/join', data={'code': 'ECON101', 'password': 'nudge'})
    c.post('/c/ECON101/signin', data={'step': 'id', 'sis_id': f'91200{i:04d}'})
    c.post('/c/ECON101/signin', data={'step': 'confirm', 'answer': 'yes'})
    c.post('/c/ECON101/signin', data={'step': 'create', 'password': 'secret1', 'password_confirm': 'secret1'})
    return c


S = {i: student(i) for i in range(1, 21)}  # 21-24 never sign up
with app.app_context():
    from models.db import get_db
    rid = {r['sis_id']: r['id'] for r in get_db().execute('SELECT id, sis_id FROM roster_student')}
sis = lambda i: rid[f'91200{i:04d}']


def group(creator, title, members, invited=()):
    S[creator].post('/c/ECON101/builder/new', data={'title': title})
    with app.app_context():
        sid = get_db().execute('SELECT MAX(id) FROM survey').fetchone()[0]
    for m in list(members) + list(invited):
        S[creator].post(f'/c/ECON101/team/{sid}/invite', data={'invitee_id': sis(m)})
    for m in members:
        with app.app_context():
            inv = get_db().execute('SELECT id FROM team_invite WHERE roster_student_id=? AND survey_id=?', (sis(m), sid)).fetchone()[0]
        S[m].post(f'/c/ECON101/team/invite/{inv}/accept')
    return sid


def q(i, qtype, label, texts, options=None, **extra):
    d = {f'questions[{i}][question_type]': qtype, f'questions[{i}][label]': label, f'questions[{i}][rules_present]': '1',
         f'questions[{i}][show_arms]': extra.pop('show', ['0', '1'])}
    for ai, t in enumerate(texts):
        d[f'questions[{i}][arms][{ai}][question_text]'] = t
        for oi, o in enumerate(options or []):
            d[f'questions[{i}][arms][{ai}][options][{oi}]'] = o
    d.update({f'questions[{i}]{k}': v for k, v in extra.items()})
    return d


# Group 1: anchoring, with a follow-up question, "Other", a timer and piping
g1 = group(1, 'Anchoring and willingness to pay', [2], invited=[3])
d = {'title': 'Anchoring and willingness to pay', 'arms[0][label]': 'Control', 'arms[1][label]': 'High anchor'}
d.update(q(0, 'numeric', 'Willingness to pay', ['How much would you pay for this mug (in $)?',
                                               'Most students pay $25 for this mug. How much would you pay (in $)?']))
d.update(q(1, 'multiple_choice', 'Would buy', ['You said ${{Q1}}. Would you buy the mug at that price today?'] * 2, ['Yes', 'No', 'Not sure']))
d['questions[1][arms][1][timer_on]'] = '1'; d['questions[1][arms][1][timer_seconds]'] = '15'; d['questions[1][arms][1][timer_display]'] = 'bar'
d.update(q(2, 'multiple_choice', 'Reason', ['What made you hesitate?'] * 2, ['Price', 'Already have one'],
           **{'[cond_question]': '1', '[cond_values]': ['No', 'Not sure']}))
d['questions[2][arms][0][allow_other]'] = '1'; d['questions[2][arms][1][allow_other]'] = '1'
print('g1', S[1].post(f'/c/ECON101/builder/{g1}/autosave', data=d).get_json()['ok'])

# Group 2: hydration, two parts with notifications
g2 = group(4, 'Hydration nudges', [5, 6])
today = date.today()
dd = lambda n: (today + timedelta(days=n)).isoformat()
d = {'title': 'Hydration nudges', 'arms[0][label]': 'Control', 'arms[1][label]': 'Nudge', 'part2_from': '2'}
d.update(q(0, 'numeric', 'Glasses yesterday', ['How many glasses of water did you drink yesterday?'] * 2))
d.update(q(1, 'multiple_choice', 'Bottle', ['Do you carry a water bottle?'] * 2, ['Always', 'Sometimes', 'Never']))
d.update(q(2, 'numeric', 'Glasses per day', ['Over the past week, how many glasses of water did you drink per day?'] * 2))
print('g2', S[4].post(f'/c/ECON101/builder/{g2}/autosave', data=d).get_json()['ok'])
now = datetime.now(timezone.utc)
plan = {'tz': '', 'arms': [
    {'note': "You'll get a short reminder to stretch every morning this week.",
     'rules': [{'message': 'Time for a quick stretch!', 'time': '09:00', 'dates': [dd(i) for i in range(1, 8)]}]},
    {'note': "You'll get a notification about drinking water every day at noon this week, and two evening tips.",
     'rules': [{'message': 'Time for a glass of water!', 'time': '12:00', 'dates': [dd(i) for i in range(1, 8)]},
               {'message': 'Two liters a day keeps you sharp.', 'time': '21:00', 'dates': [dd(3), dd(6)]}]}]}
parts = {'1': {'when': 'live'}, '2': {'when': 'remote', 'open_date': dd(-1), 'close_date': dd(9),
                                      'open_utc': (now - timedelta(days=1)).isoformat(), 'close_utc': (now + timedelta(days=9)).isoformat(),
                                      'time': '10:00'}}
print('g2 plan', S[4].post(f'/c/ECON101/builder/{g2}/reminders', json={'plan': plan, 'parts': parts}).get_json()['ok'])
host.post(f'/c/ECON101/host/survey/{g2}/reminders', data={'action': 'approve'})

# More groups of different sizes and states
for creator, title, members, invited, qs in [
    (7, 'Loss framing and donations', [8, 9], [], True),
    (10, 'Default effects in savings', [11], [12], True),
    (13, 'Social norms and recycling', [], [], False),
    (14, 'Decoy pricing for coffee', [15, 16, 17], [], True),
]:
    sid = group(creator, title, members, invited)
    if qs:
        d = {'title': title, 'arms[0][label]': 'Control', 'arms[1][label]': 'Treatment'}
        d.update(q(0, 'multiple_choice', 'Choice', ['Which would you choose?', 'Which would you choose? (most people chose B)'], ['A', 'B']))
        S[creator].post(f'/c/ECON101/builder/{sid}/autosave', data=d)

# Noah's answers to group 2, part 1 (live), so his lobby shows the notifications and part 2
host.post('/c/ECON101/host/activate', json={'survey_id': g2, 'part': 1})
for i in (3, 7, 8, 10, 12):
    S[i].get('/c/ECON101/student/session')
    st = S[i].get('/c/ECON101/student/state').get_json()
    a = st['assignment']
    S[i].post('/c/ECON101/student/submit', json={'survey_id': g2, 'arm_id': a['arm_id'], 'answers': [
        {'question_id': a['questions'][0]['question_id'], 'answer_text': str(3 + i % 4), 'seconds': 6.2},
        {'question_id': a['questions'][1]['question_id'], 'answer_text': 'Sometimes', 'answer_index': 1, 'seconds': 3.1}]})
    print('student', i, 'arm', a['arm_label'])
host.post('/c/ECON101/host/reset')

# Three students without a group list themselves in the group finder
for i, note in ((18, 'Happy to do the data analysis'), (19, 'Interested in pricing or framing experiments'), (20, '')):
    S[i].post('/c/ECON101/group-finder', data={'listed': '1', 'note': note})
# ... and Group 4 (2 members) is looking for more
S[10].post('/c/ECON101/team/4/seeking', data={'listed': '1', 'note': 'Testing default options in retirement savings; looking for 1-3 more'})
print('done')
