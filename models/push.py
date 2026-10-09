"""Web push notifications for reminders (the alternative to the calendar, mainly for Android).

A respondent who turns notifications on gets a browser push subscription (static/js/sw.js is the
service worker). At that moment every reminder of their arm is scheduled as a `push_message`
row with its UTC send time: reminders without a time zone use the phone's own zone. A
background loop (start_sender, in the app process) sends the due ones with pywebpush; tapping
a notification goes through /c/<code>/reminders/push/<id>/<token>, which records the tap.

The VAPID key pair that identifies this server to the push services is created on first use
and kept in `app_setting`, so nothing needs configuring on Render.
"""
import base64
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from models import reminders
from models.db import get_db

logger = logging.getLogger(__name__)

LATE_LIMIT = timedelta(hours=3)   # a reminder more than this late (server was down) is dropped
MAX_ATTEMPTS = 3
SEND_EVERY_SECONDS = 60


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _setting(db, key):
    row = db.execute('SELECT value FROM app_setting WHERE key=?', (key,)).fetchone()
    return row['value'] if row else None


def vapid_keys(db=None):
    """(private key, public key) as base64url strings, created the first time."""
    db = db or get_db()
    private, public = _setting(db, 'vapid_private'), _setting(db, 'vapid_public')
    if private and public:
        return private, public
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    private = _b64(key.private_numbers().private_value.to_bytes(32, 'big'))
    public = _b64(key.public_key().public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint))
    db.execute('INSERT OR IGNORE INTO app_setting (key, value) VALUES (?, ?)', ('vapid_private', private))
    db.execute('INSERT OR IGNORE INTO app_setting (key, value) VALUES (?, ?)', ('vapid_public', public))
    db.commit()
    # Another process may have won the race: use whatever is stored
    return _setting(db, 'vapid_private'), _setting(db, 'vapid_public')


def remember_site(host_url):
    """The site's address, for the VAPID contact claim (push services want a URL or e-mail)."""
    db = get_db()
    db.execute('INSERT OR REPLACE INTO app_setting (key, value) VALUES (?, ?)', ('site_url', host_url.rstrip('/')))
    db.commit()


def subscribe(survey, participant_id, arm_index, sub, phone_tz, items):
    """Store (or refresh) a subscription and schedule its reminders (reminder times without a
    time zone use the phone's, phone_tz). Returns the number of reminders scheduled."""
    endpoint = str(sub.get('endpoint') or '')
    keys = sub.get('keys') or {}
    if not endpoint.startswith('https://') or not keys.get('p256dh') or not keys.get('auth'):
        raise ValueError('bad subscription')
    db = get_db()
    db.execute('INSERT INTO push_subscription (survey_id, participant_id, arm_index, endpoint, p256dh, auth, tz, active) '
               'VALUES (?, ?, ?, ?, ?, ?, ?, 1) ON CONFLICT(survey_id, participant_id, endpoint) DO UPDATE SET '
               'p256dh=excluded.p256dh, auth=excluded.auth, tz=excluded.tz, arm_index=excluded.arm_index, active=1',
               (survey['id'], participant_id, arm_index, endpoint, keys['p256dh'], keys['auth'],
                reminders.valid_tz(phone_tz)))
    sub_id = db.execute('SELECT id FROM push_subscription WHERE survey_id=? AND participant_id=? AND endpoint=?',
                        (survey['id'], participant_id, endpoint)).fetchone()['id']
    # Re-subscribing replaces what was still waiting to be sent
    db.execute("DELETE FROM push_message WHERE subscription_id=? AND status='pending'", (sub_id,))
    now = datetime.now(timezone.utc)
    count = 0
    for item in items:
        body = 'Tap to answer it.' if item['key'] == 'p2' else item['description']
        for when in reminders.utc_times(item, phone_tz):
            if when < now:
                continue
            token = secrets.token_urlsafe(12)
            db.execute('INSERT INTO push_message (subscription_id, item, title, body, send_at, token) '
                       'VALUES (?, ?, ?, ?, ?, ?)',
                       (sub_id, str(item['key']), item['summary'], body, when.isoformat(), token))
            count += 1
    db.commit()
    return count


def _contact(db):
    """(site, VAPID contact): the site behind Render's proxy may look like http://, but push only
    works over https anyway."""
    site = 'https://' + (urlparse(_setting(db, 'site_url') or '').netloc or 'localhost')
    return site, os.environ.get('VAPID_SUBJECT') or site


def send_test(sub, title, body, url, sender=None):
    """Send one notification right away (the builder's preview). Raises on failure."""
    if not str(sub.get('endpoint') or '').startswith('https://') or not (sub.get('keys') or {}).get('auth'):
        raise ValueError('bad subscription')
    if sender is None:
        from pywebpush import webpush as sender
    db = get_db()
    private, _ = vapid_keys(db)
    _, contact = _contact(db)
    sender({'endpoint': sub['endpoint'], 'keys': {'p256dh': sub['keys'].get('p256dh'), 'auth': sub['keys']['auth']}},
           json.dumps({'title': title, 'body': body + ' (test)', 'tag': 'reminder-test', 'url': url}),
           private, {'sub': contact})


def unsubscribe(survey_id, participant_id):
    db = get_db()
    ids = [r['id'] for r in db.execute('SELECT id FROM push_subscription WHERE survey_id=? AND participant_id=?',
                                       (survey_id, participant_id))]
    for sid in ids:
        db.execute('UPDATE push_subscription SET active=0 WHERE id=?', (sid,))
        db.execute("UPDATE push_message SET status='cancelled' WHERE subscription_id=? AND status='pending'", (sid,))
    db.commit()


def status_for(survey_id, participant_id):
    """{'on': bool, 'pending': n waiting to be sent} for the panel."""
    row = get_db().execute(
        "SELECT COUNT(DISTINCT ps.id) AS subs, SUM(pm.status = 'pending') AS pending FROM push_subscription ps "
        "LEFT JOIN push_message pm ON pm.subscription_id = ps.id "
        "WHERE ps.survey_id=? AND ps.participant_id=? AND ps.active=1", (survey_id, participant_id)).fetchone()
    return {'on': bool(row['subs']), 'pending': row['pending'] or 0}


def record_click(message_id, token):
    """A notification was tapped. Returns the survey's classroom code, or None."""
    db = get_db()
    row = db.execute('SELECT pm.id, pm.clicked_at, c.code FROM push_message pm '
                     'JOIN push_subscription ps ON pm.subscription_id = ps.id JOIN survey s ON ps.survey_id = s.id '
                     'JOIN classroom c ON s.classroom_id = c.id WHERE pm.id=? AND pm.token=?',
                     (message_id, token)).fetchone()
    if not row:
        return None
    if not row['clicked_at']:
        db.execute("UPDATE push_message SET clicked_at=datetime('now') WHERE id=?", (message_id,))
        db.commit()
    return row['code']


def send_due(db, now=None, sender=None):
    """Send every message that is due. `sender(subscription_info, payload, private_key, claims)`
    defaults to pywebpush.webpush (tests pass a fake). Returns the number sent."""
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    if sender is None:
        from pywebpush import webpush as sender
    private, _ = vapid_keys(db)
    site, contact = _contact(db)
    due = db.execute("SELECT pm.*, ps.endpoint, ps.p256dh, ps.auth, ps.active, ps.survey_id, s.reminders_approved, "
                     "c.code FROM push_message pm JOIN push_subscription ps ON pm.subscription_id = ps.id "
                     "JOIN survey s ON ps.survey_id = s.id JOIN classroom c ON s.classroom_id = c.id "
                     "WHERE pm.status='pending' AND pm.send_at <= ? ORDER BY pm.send_at LIMIT 200",
                     (now.isoformat(),)).fetchall()
    sent = 0
    approved = {}
    for m in due:
        # Claim it, so a second process (dev reloader, restart overlap) can't send it too
        if db.execute("UPDATE push_message SET status='sending', attempts=attempts+1 WHERE id=? AND status='pending'",
                      (m['id'],)).rowcount != 1:
            db.commit()
            continue
        db.commit()
        if m['survey_id'] not in approved:
            from models.survey import get_survey
            approved[m['survey_id']] = reminders.approval_state(get_survey(m['survey_id'])) == 'approved'
        status, error = 'sent', None
        if not m['active'] or not approved[m['survey_id']]:
            status = 'cancelled'
        elif now - datetime.fromisoformat(m['send_at']) > LATE_LIMIT:
            status = 'missed'
        else:
            payload = json.dumps({'title': m['title'], 'body': m['body'], 'tag': f'reminder-{m["id"]}',
                                  'url': f'{site}/c/{m["code"]}/reminders/push/{m["id"]}/{m["token"]}'})
            try:
                sender({'endpoint': m['endpoint'], 'keys': {'p256dh': m['p256dh'], 'auth': m['auth']}},
                       payload, private, {'sub': contact})
            except Exception as e:  # pywebpush.WebPushException and network errors
                code = getattr(getattr(e, 'response', None), 'status_code', None)
                error = f'{code or ""} {e}'.strip()[:300]
                if code in (404, 410):
                    # The phone unsubscribed or the browser data was cleared: stop for good
                    db.execute('UPDATE push_subscription SET active=0 WHERE id=?', (m['subscription_id'],))
                    status = 'failed'
                else:
                    status = 'pending' if m['attempts'] + 1 < MAX_ATTEMPTS else 'failed'
        db.execute('UPDATE push_message SET status=?, error=?, sent_at=? WHERE id=?',
                   (status, error, now.isoformat() if status == 'sent' else None, m['id']))
        db.commit()
        sent += status == 'sent'
    return sent


def start_sender(app, socketio):
    """Check for due notifications every minute, in the background of the app process."""
    if os.environ.get('PUSH_SENDER', '1') == '0':
        return

    def loop():
        from models.db import get_socket_db
        while True:
            socketio.sleep(SEND_EVERY_SECONDS)
            try:
                with app.app_context():
                    db = get_socket_db()
                    try:
                        n = send_due(db)
                        if n:
                            logger.info('push: sent %d reminder(s)', n)
                    finally:
                        db.close()
            except Exception:
                logger.exception('push: sending failed')

    socketio.start_background_task(loop)
