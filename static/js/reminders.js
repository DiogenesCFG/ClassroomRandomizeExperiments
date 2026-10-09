// The respondent's "add your reminders to your calendar" step (after answering, and from the lobby).
// The server sends the arm's note, the reminders and their links (routes/reminders.py, /panel).
// What we offer depends on the device: iPhones open the .ics file and show "Add All"; the
// Google Calendar app on Android can't open .ics files, so Android gets one Google Calendar
// link per reminder, plus push notifications for phones without Google Calendar; computers
// download the .ics file. "Other ways" shows all of them.
window.RemindersPanel = (function() {
    function device() {
        var ua = navigator.userAgent || '';
        // iPads report themselves as Macs; a touch screen gives them away
        if (/iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)) return 'ios';
        if (/Android/.test(ua)) return 'android';
        return 'desktop';
    }

    function esc(text) {
        var div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    function withDevice(url, d) {
        return url + (url.indexOf('?') === -1 ? '?' : '&') + 'd=' + d;
    }

    function section(kind, data, d) {
        if (kind === 'ios') {
            return '<div class="rem-way" data-way="ios">'
                + '<a class="btn btn-primary w-100" href="' + esc(withDevice(data.ics_url, d) + '&inline=1') + '">&#128197; Add to my calendar</a>'
                + '<div class="small text-muted mt-1">Tap it, then <b>Add All</b>.</div></div>';
        }
        if (kind === 'android') {
            var html = '<div class="rem-way" data-way="android">';
            data.items.forEach(function(item) {
                html += '<a class="btn btn-primary w-100 mb-2 rem-google" target="_blank" rel="noopener" href="'
                    + esc(withDevice(item.google_url, d)) + '">&#128197; Add &ldquo;' + esc(item.summary) + '&rdquo;</a>';
            });
            html += '<div class="small text-muted">' + (data.items.length > 1 ? 'Tap each button: ' : 'Tap it: ')
                + 'Google Calendar opens with the reminder filled in. Tap <b>Save</b>, then come back here.</div></div>';
            return html;
        }
        return '<div class="rem-way" data-way="desktop">'
            + '<a class="btn btn-primary" href="' + esc(withDevice(data.ics_url, d)) + '" download="reminders.ics">&#8681; Download calendar file (.ics)</a>'
            + '<div class="small text-muted mt-1">Open the file to add the reminders to your calendar (Outlook, Apple Calendar). '
            + 'Google Calendar: on calendar.google.com, go to Settings &rarr; Import &amp; export &rarr; Import. '
            + 'Reminders added on a computer reach your phone if it uses the same calendar.</div></div>';
    }

    // Push notifications (service worker /sw.js, models/push.py). iPhones only allow them for
    // sites added to the Home Screen, so they're offered there only in that case.
    function pushSupported(d) {
        return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
            && (d !== 'ios' || navigator.standalone === true);
    }

    function pushSection(data, d) {
        if (data.preview) {
            if (!pushSupported(d)) {
                return '<div class="small text-muted">To try a notification, open this preview in Chrome or Firefox on an Android phone or a computer.</div>';
            }
            return '<div class="rem-push">'
                + '<button type="button" class="btn btn-outline-primary w-100 rem-push-test">&#128276; Send me a test notification</button>'
                + '<div class="small text-muted mt-1">Preview: sends this arm\'s first notification to this device now, so you can see it. Nothing is scheduled.</div>'
                + '<div class="small rem-push-error"></div></div>';
        }
        if (!pushSupported(d)) {
            return d === 'ios' ? '' : '<div class="small text-muted">This browser can\'t show notifications from this site. Use the calendar instead.</div>';
        }
        if (data.push && data.push.on) {
            return '<div class="rem-push small"><span class="text-success">&#128276; Notifications are on'
                + (data.push.pending ? ': ' + data.push.pending + ' reminder' + (data.push.pending > 1 ? 's' : '') + ' will arrive on this device' : '')
                + '.</span> Keep notifications allowed for this site. '
                + '<button type="button" class="btn btn-link btn-sm p-0 rem-push-off">Turn them off</button></div>';
        }
        return '<div class="rem-push">'
            + '<button type="button" class="btn btn-outline-primary w-100 rem-push-on"' + (data.push_url ? '' : ' disabled') + '>'
            + '&#128276; Get notifications on this device instead</button>'
            + '<div class="small text-muted mt-1">' + (data.push_url
                ? 'No Google Calendar? Allow notifications when asked, and the reminders arrive on this device even with the browser closed.'
                : '(Not available in a preview.)') + '</div>'
            + '<div class="small text-danger rem-push-error"></div></div>';
    }

    function urlBase64ToUint8Array(value) {
        var padded = (value + '===='.slice((value.length + 3) % 4 + 1)).replace(/-/g, '+').replace(/_/g, '/');
        var raw = atob(padded);
        var out = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
        return out;
    }

    function postPush(data, d, body) {
        return fetch(withDevice(data.push_url, d), {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).then(function(r) { return r.json(); });
    }

    // Ask permission and get this browser's push subscription (resolves to the subscription)
    function deviceSubscription(data) {
        return navigator.serviceWorker.register('/sw.js')
            .then(function() { return Notification.requestPermission(); })
            .then(function(permission) {
                if (permission !== 'granted') throw new Error('denied');
                return navigator.serviceWorker.ready;
            })
            .then(function(reg) {
                return reg.pushManager.getSubscription().then(function(sub) {
                    return sub || reg.pushManager.subscribe({
                        userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(data.vapid_key),
                    });
                });
            });
    }

    function pushError(err) {
        return err.message === 'denied'
            ? 'Notifications are blocked for this site. Allow them in your browser\'s site settings, or use the calendar instead.'
            : 'Could not turn on notifications in this browser. Use the calendar instead.';
    }

    function sendTest(data, button) {
        var msg = button.parentNode.querySelector('.rem-push-error');
        button.disabled = true;
        deviceSubscription(data)
            .then(function(sub) {
                return fetch(data.push_test_url, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ subscription: sub.toJSON() }),
                }).then(function(r) { return r.json(); });
            })
            .then(function(res) {
                if (!res.ok) throw new Error(res.error || res.reason || 'failed');
                msg.className = 'small text-success rem-push-error';
                msg.textContent = 'Sent. It should appear in a few seconds (check your notifications).';
            })
            .catch(function(err) {
                msg.className = 'small text-danger rem-push-error';
                msg.textContent = err.message === 'denied' ? pushError(err) : 'Could not send it: ' + err.message;
            })
            .finally(function() { button.disabled = false; });
    }

    function turnPushOn(box, data, d, button) {
        var errorEl = button.parentNode.querySelector('.rem-push-error');
        button.disabled = true;
        button.textContent = 'Turning notifications on…';
        deviceSubscription(data)
            .then(function(sub) {
                var tz = '';
                try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (err) {}
                return postPush(data, d, { subscription: sub.toJSON(), tz: tz });
            })
            .then(function(res) {
                if (!res.ok) throw new Error(res.reason || 'failed');
                data.push = res.push;
                render(box, data);
            })
            .catch(function(err) {
                button.disabled = false;
                button.innerHTML = '&#128276; Get notifications on this device instead';
                errorEl.textContent = pushError(err);
            });
    }

    function render(box, data) {
        var d = device();
        var html = '<div class="card text-start border-primary">'
            + '<div class="card-header"><strong>&#128276; Your notifications</strong></div><div class="card-body">';
        if (data.preview) {
            html += '<div class="alert alert-info py-1 small">Preview of what respondents in <b>' + esc(data.arm_label)
                + '</b> get. Nothing is recorded.'
                + (data.approval === 'pending' || data.approval === 'changed'
                    ? ' <b>Not approved yet</b>: respondents get nothing until your instructor approves.' : '')
                + '</div>';
        }
        if (data.note) html += '<p style="white-space: pre-line">' + esc(data.note) + '</p>';
        html += '<ul class="small mb-3">';
        data.items.forEach(function(item) {
            html += '<li><b>' + esc(item.summary) + '</b>: ' + esc(item.when) + '</li>';
        });
        html += '</ul>';
        html += section(d, data, d);
        // Android: notifications right under the Google Calendar buttons; elsewhere under "Other ways"
        if (d === 'android') html += '<div class="mt-3">' + pushSection(data, d) + '</div>';
        var others = ['ios', 'android', 'desktop'].filter(function(k) { return k !== d; });
        html += '<details class="mt-3 small"' + (d !== 'android' && data.push && data.push.on ? ' open' : '') + '>'
            + '<summary class="text-muted">Other ways to add them</summary>';
        others.forEach(function(k) {
            html += '<div class="mt-2"><b>' + { ios: 'iPhone or iPad', android: 'Google Calendar (Android)', desktop: 'Calendar file' }[k]
                + '</b>' + section(k, data, d) + '</div>';
        });
        if (d !== 'android' && pushSection(data, d)) html += '<div class="mt-2"><b>Notifications</b>' + pushSection(data, d) + '</div>';
        html += '</details>';
        html += '<div class="mt-3 rem-done">' + (data.done
            ? '<span class="text-success">&#10003; Thanks! You said they\'re in your calendar.</span>'
            : '<button type="button" class="btn btn-outline-success btn-sm rem-done-btn">Done: they\'re in my calendar</button>')
            + '</div></div></div>';
        box.innerHTML = html;
        box.style.display = '';
        var testBtn = box.querySelector('.rem-push-test');
        if (testBtn) testBtn.addEventListener('click', function() { sendTest(data, testBtn); });
        var onBtn = box.querySelector('.rem-push-on');
        if (onBtn) onBtn.addEventListener('click', function() { turnPushOn(box, data, d, onBtn); });
        var offBtn = box.querySelector('.rem-push-off');
        if (offBtn) {
            offBtn.addEventListener('click', function() {
                postPush(data, d, { off: true }).then(function(res) {
                    if (res.ok) { data.push = res.push; render(box, data); }
                }).catch(function() {});
            });
        }
        var doneBtn = box.querySelector('.rem-done-btn');
        if (doneBtn) {
            doneBtn.addEventListener('click', function() {
                fetch(withDevice(data.done_url, d), { method: 'POST', credentials: 'same-origin' })
                    .then(function() {
                        box.querySelector('.rem-done').innerHTML = '<span class="text-success">&#10003; Thanks!</span>';
                    })
                    .catch(function() {});
            });
        }
    }

    // onEmpty (optional) runs when there is nothing to add
    function load(box, url, onEmpty) {
        box.style.display = 'none';
        fetch(url, { credentials: 'same-origin' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.ok && data.show) render(box, data);
                else if (onEmpty) onEmpty();
            })
            .catch(function() { if (onEmpty) onEmpty(); });
    }

    return { load: load, device: device };
})();
