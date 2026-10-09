// The survey page's "Two-part survey" timing (each part's when and dates) and "Notifications" card
// (templates/builder/_reminders_card.html). Both are saved together as JSON to reminders.save_plan,
// separately from the survey form, so they can change after the survey has responses.
// The notification plan is a JS object (one entry per arm: a note and notifications, each with a
// message, a time and the chosen days), rendered into the card. Arm names and the number of arms
// follow the survey form (builder.js fires 'arms-changed').
document.addEventListener('DOMContentLoaded', function() {
    var card = document.getElementById('reminders-card');
    if (!card) return;
    var state = JSON.parse(card.dataset.state);
    var plan = state.plan;
    var locked = card.dataset.locked === '1';
    var limit = card.dataset.limit || '';
    var today = state.today;
    var armsBox = document.getElementById('reminder-arms');
    var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    var open = {};   // which arm / notification sections are expanded ('a0', 'a0-r1')
    var views = {};  // the month each notification's calendar shows ('a0-r1' -> 'yyyy-mm')

    function esc(text) {
        var div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML.replace(/"/g, '&quot;');
    }

    function armLabels() {
        var labels = [];
        document.querySelectorAll('#arms-container .arm-label-block input').forEach(function(input, i) {
            labels.push(input.value || 'Arm ' + (i + 1));
        });
        return labels;
    }

    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function iso(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
    function parseIso(s) { var p = s.split('-').map(Number); return new Date(p[0], p[1] - 1, p[2]); }
    function niceDate(s) {
        return parseIso(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
    function niceTime(t) {
        if (!t) return '';
        var p = t.split(':').map(Number);
        return new Date(2000, 0, 1, p[0], p[1]).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    }

    // --- One notification: message, time, days (a month calendar where days are tapped on and off) ---
    function calendarHtml(rule, key) {
        var view = views[key] || (rule.dates[0] || today).slice(0, 7);
        views[key] = view;
        var y = parseInt(view.slice(0, 4), 10), m = parseInt(view.slice(5, 7), 10) - 1;
        var first = new Date(y, m, 1);
        var html = '<div class="rem-cal border rounded p-2" data-key="' + key + '">'
            + '<div class="d-flex justify-content-between align-items-center mb-1">'
            + '<button type="button" class="btn btn-sm btn-light rem-cal-nav" data-step="-1" aria-label="Previous month">&lsaquo;</button>'
            + '<strong class="small">' + MONTHS[m] + ' ' + y + '</strong>'
            + '<button type="button" class="btn btn-sm btn-light rem-cal-nav" data-step="1" aria-label="Next month">&rsaquo;</button></div>'
            + '<div class="rem-cal-grid">';
        ['S', 'M', 'T', 'W', 'T', 'F', 'S'].forEach(function(d) { html += '<span class="rem-cal-head">' + d + '</span>'; });
        for (var i = 0; i < first.getDay(); i++) html += '<span></span>';
        for (var day = 1; day <= new Date(y, m + 1, 0).getDate(); day++) {
            var value = iso(new Date(y, m, day));
            var off = value < today || (limit && value > limit);
            var on = rule.dates.indexOf(value) !== -1;
            html += '<button type="button" class="rem-day' + (on ? ' on' : '') + '" data-date="' + value + '"'
                + (off ? ' disabled' : '') + '>' + day + '</button>';
        }
        html += '</div>'
            + '<div class="d-flex flex-wrap align-items-center gap-1 mt-2 small">'
            + '<span>Quick fill: from</span><input type="date" class="form-control form-control-sm w-auto rem-fill-from">'
            + '<span>to</span><input type="date" class="form-control form-control-sm w-auto rem-fill-to">'
            + '<select class="form-select form-select-sm w-auto rem-fill-every">'
            + '<option value="1">every day</option><option value="2">every 2 days</option><option value="3">every 3 days</option>'
            + '<option value="7">every week</option><option value="weekdays">weekdays only</option></select>'
            + '<button type="button" class="btn btn-sm btn-outline-primary rem-fill">Add days</button>'
            + (rule.dates.length ? '<button type="button" class="btn btn-sm btn-link text-danger rem-clear">Clear all days</button>' : '')
            + '</div></div>';
        return html;
    }

    function ruleSummary(rule) {
        var n = rule.dates.length;
        return (rule.message ? '&ldquo;' + esc(rule.message.length > 40 ? rule.message.slice(0, 39) + '…' : rule.message) + '&rdquo;' : '<em>no message yet</em>')
            + ' &middot; ' + esc(niceTime(rule.time))
            + ' &middot; ' + (n ? n + ' day' + (n > 1 ? 's' : '') + ' (' + esc(niceDate(rule.dates[0]))
                + (n > 1 ? ' to ' + esc(niceDate(rule.dates[n - 1])) : '') + ')' : '<em>no days yet</em>');
    }

    function ruleHtml(rule, ai, ri) {
        var key = 'a' + ai + '-r' + ri;
        var isOpen = open[key] !== undefined ? open[key] : !rule.message;
        return '<div class="rem-rule border rounded mb-2" data-rule="' + ri + '">'
            + '<div class="d-flex align-items-center gap-2 px-2 py-1 rem-head">'
            + '<span class="rem-toggle d-inline-flex align-items-center gap-1 text-nowrap" role="button" tabindex="0" data-key="' + key + '">'
            + '<span class="collapse-chevron">' + (isOpen ? '&#9662;' : '&#9656;') + '</span><span class="fw-semibold small">Notification ' + (ri + 1) + '</span></span>'
            + '<span class="small text-muted text-truncate rem-summary">' + ruleSummary(rule) + '</span>'
            + '<button type="button" class="btn btn-sm btn-outline-danger ms-auto rem-remove py-0" title="Remove this notification">x</button></div>'
            + '<div class="px-2 pb-2 rem-body"' + (isOpen ? '' : ' style="display:none"') + '>'
            + '<div class="row g-2 mb-2">'
            + '<div class="col-12 col-md-8"><label class="form-label small mb-0">Message (what they receive)</label>'
            + '<input type="text" class="form-control form-control-sm rem-field" data-field="message" maxlength="150" value="' + esc(rule.message) + '" placeholder="e.g. Time for a glass of water!"></div>'
            + '<div class="col-6 col-md-4"><label class="form-label small mb-0">Time of day</label>'
            + '<input type="time" class="form-control form-control-sm rem-field" data-field="time" value="' + esc(rule.time) + '"></div>'
            + '</div>'
            + '<label class="form-label small mb-1">Days it is sent: tap days to select them</label>'
            + calendarHtml(rule, key)
            + '</div></div>';
    }

    function armSummary(arm) {
        var days = 0;
        arm.rules.forEach(function(r) { days += r.dates.length; });
        if (!arm.rules.length) return 'no notifications';
        return arm.rules.length + ' notification' + (arm.rules.length > 1 ? 's' : '') + ', ' + days + ' sends in total';
    }

    function render() {
        var labels = armLabels();
        while (plan.arms.length < labels.length) plan.arms.push({ note: '', rules: [] });
        plan.arms.length = labels.length;
        var html = '';
        plan.arms.forEach(function(arm, ai) {
            var key = 'a' + ai;
            var isOpen = open[key] !== undefined ? open[key] : true;
            html += '<div class="reminder-arm border-start border-3 ps-3 mb-3" data-arm="' + ai + '">'
                + '<div class="d-flex align-items-center gap-2 flex-wrap rem-arm-head">'
                + '<span class="rem-toggle d-inline-flex align-items-center gap-1" role="button" tabindex="0" data-key="' + key + '">'
                + '<span class="collapse-chevron">' + (isOpen ? '&#9662;' : '&#9656;') + '</span><strong>' + esc(labels[ai]) + '</strong></span>'
                + '<span class="small text-muted">' + armSummary(arm) + '</span>'
                + (ai > 0 ? '<button type="button" class="btn btn-link btn-sm p-0 ms-auto rem-copy">Copy from ' + esc(labels[0]) + '</button>' : '')
                + '</div>'
                + '<div class="mt-2 rem-arm-body"' + (isOpen ? '' : ' style="display:none"') + '>'
                + '<label class="form-label small mb-0">What respondents in this arm read before turning them on</label>'
                + '<textarea class="form-control form-control-sm rem-note mb-2" rows="2" maxlength="1000" placeholder="e.g. You\'ll get a notification about drinking water every day at noon for the next week.">'
                + esc(arm.note) + '</textarea>'
                + '<div class="rem-rules">' + arm.rules.map(function(r, ri) { return ruleHtml(r, ai, ri); }).join('') + '</div>'
                + (arm.rules.length < state.max_rules
                    ? '<button type="button" class="btn btn-sm btn-outline-success rem-add">+ Add notification</button>' : '')
                + '</div></div>';
        });
        armsBox.innerHTML = html;
        if (locked) {
            armsBox.querySelectorAll('input, textarea, select, button:not(.rem-cal-nav)').forEach(function(el) { el.disabled = true; });
        }
    }

    // --- Two-part timing (in the survey form's "Two-part survey" card) ---
    var partsCard = document.getElementById('two-part-card');
    function partField(p, name) { return document.getElementById('p' + p + '-' + name); }
    function showPartDates() {
        if (!partsCard) return;
        partsCard.querySelectorAll('.part-when-row').forEach(function(row) {
            row.querySelector('.part-dates').style.display = partField(row.dataset.part, 'when').value === 'remote' ? '' : 'none';
        });
    }
    if (partsCard) {
        [1, 2].forEach(function(p) {
            var saved = state.parts[p];
            partField(p, 'when').value = saved.when;
            partField(p, 'open').value = saved.open_date;
            partField(p, 'close').value = saved.close_date;
            if (limit) { partField(p, 'open').max = limit; partField(p, 'close').max = limit; }
        });
        partField(2, 'time').value = state.part2_time;
        showPartDates();
        partsCard.querySelectorAll('.part-when, .part-dates input').forEach(function(el) {
            el.addEventListener('change', function() { showPartDates(); scheduleSave(); });
            el.addEventListener('input', scheduleSave);
        });
    }

    function localMoment(value, endOfDay) {
        if (!value) return '';
        var p = value.split('-').map(Number);
        return new Date(p[0], p[1] - 1, p[2], endOfDay ? 23 : 0, endOfDay ? 59 : 0, endOfDay ? 59 : 0).toISOString();
    }

    function partsPayload() {
        var out = {};
        [1, 2].forEach(function(p) {
            var opens = partField(p, 'open').value, closes = partField(p, 'close').value;
            out[p] = { when: partField(p, 'when').value, open_date: opens, close_date: closes,
                       open_utc: localMoment(opens, false), close_utc: localMoment(closes, true) };
        });
        out[2].time = partField(2, 'time').value || '09:00';
        return out;
    }

    // --- Saving, approval and problems (shown on both cards) ---
    function setStatus(text, cls) {
        document.querySelectorAll('.extras-status').forEach(function(el) {
            el.textContent = text;
            el.className = 'small extras-status ' + (cls || 'text-muted');
        });
    }
    function showApproval(approval) {
        var looks = {
            approved: ['text-bg-success', '✓ Approved by your instructor'],
            pending: ['text-bg-warning', 'Waiting for your instructor\'s approval'],
            changed: ['text-bg-warning', 'Changed since approval: needs approval again'],
        }[approval];
        document.querySelectorAll('.approval-badge').forEach(function(badge) {
            badge.style.display = looks ? '' : 'none';
            if (looks) { badge.className = 'badge approval-badge ' + looks[0]; badge.textContent = looks[1]; }
        });
    }
    function showProblems(problems) {
        // Problems about the parts' dates go on the two-part card; the rest on this one
        var partsProblems = problems.filter(function(p) { return /^Part \d/.test(p); });
        var others = problems.filter(function(p) { return !/^Part \d/.test(p); });
        [[card.querySelector('.reminders-problems'), others],
         [partsCard && partsCard.querySelector('.parts-problems'), partsProblems]].forEach(function(pair) {
            if (!pair[0]) return;
            pair[0].style.display = pair[1].length ? '' : 'none';
            pair[0].textContent = pair[1].length ? 'Still to do: ' + pair[1].join(' ') : '';
        });
    }

    var saveTimer = null, saving = false, pending = false, stopped = locked;
    function saveNow() {
        if (stopped) return;
        if (saving) { pending = true; return; }
        saving = true;
        setStatus('Saving…');
        var body = { plan: plan };
        if (partsCard) body.parts = partsPayload();
        fetch(card.dataset.saveUrl, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        })
            .then(function(r) { return r.json(); })
            .then(function(res) {
                if (res.ok) {
                    setStatus('Saved at ' + new Date().toLocaleTimeString() + '.', 'text-success');
                    showApproval(res.approval);
                    showProblems(res.problems || []);
                    // The survey's overall "Not finished yet" box includes these too
                    var todoBox = document.getElementById('survey-todo');
                    if (todoBox && res.todo) {
                        todoBox.style.display = res.todo.length ? '' : 'none';
                        document.getElementById('survey-todo-list').textContent = res.todo.join(' ');
                    }
                } else if (res.reason === 'locked') {
                    stopped = true;
                    setStatus('Locked by your instructor. Changes are no longer saved.', 'text-danger');
                } else {
                    setStatus('Could not save.', 'text-danger');
                }
            })
            .catch(function() { setStatus('Could not save. Check your connection; we will retry on your next change.', 'text-danger'); })
            .finally(function() {
                saving = false;
                if (pending) { pending = false; scheduleSave(); }
            });
    }
    function scheduleSave() {
        if (stopped) return;
        clearTimeout(saveTimer);
        setStatus('Unsaved changes…');
        saveTimer = setTimeout(saveNow, 1000);
    }

    // --- Time zone: none (each phone's own time) or one from the list ---
    var tzSelect = document.getElementById('rem-tz');
    (function() {
        var common = ['America/Los_Angeles', 'America/Denver', 'America/Phoenix', 'America/Chicago', 'America/New_York',
                      'America/Anchorage', 'Pacific/Honolulu'];
        var all = [];
        try { all = Intl.supportedValuesOf('timeZone'); } catch (err) {}
        if (!all.length) all = common.concat(['UTC', 'Europe/London', 'Europe/Madrid', 'Asia/Tokyo']);
        if (plan.tz && all.indexOf(plan.tz) === -1 && common.indexOf(plan.tz) === -1) all = all.concat([plan.tz]);
        var html = '<option value="">each phone\'s own time (no time zone)</option><optgroup label="United States">';
        common.forEach(function(z) { html += '<option value="' + z + '">' + z.replace(/_/g, ' ') + '</option>'; });
        html += '</optgroup><optgroup label="All time zones">';
        all.forEach(function(z) { if (common.indexOf(z) === -1) html += '<option value="' + esc(z) + '">' + esc(z.replace(/_/g, ' ')) + '</option>'; });
        tzSelect.innerHTML = html + '</optgroup>';
        tzSelect.value = plan.tz || '';
        tzSelect.disabled = locked;
        tzSelect.addEventListener('change', function() { plan.tz = tzSelect.value; scheduleSave(); });
    })();

    // --- Editing ---
    function where(el) {
        var armEl = el.closest('.reminder-arm');
        var ruleEl = el.closest('.rem-rule');
        var ai = parseInt(armEl.dataset.arm, 10);
        var ri = ruleEl ? parseInt(ruleEl.dataset.rule, 10) : null;
        return { arm: plan.arms[ai], ai: ai, rule: ruleEl ? plan.arms[ai].rules[ri] : null, ri: ri, ruleEl: ruleEl };
    }

    // Typing updates the plan in place (no re-render, so the cursor stays put)
    armsBox.addEventListener('input', function(e) {
        if (!e.target.closest('.reminder-arm')) return;
        var t = where(e.target);
        if (e.target.classList.contains('rem-note')) {
            t.arm.note = e.target.value;
            scheduleSave();
        } else if (t.rule && e.target.dataset.field) {
            t.rule[e.target.dataset.field] = e.target.value;
            t.ruleEl.querySelector('.rem-summary').innerHTML = ruleSummary(t.rule);
            scheduleSave();
        }
    });

    function toggleSection(toggle) {
        var body = toggle.closest('.rem-head, .rem-arm-head').nextElementSibling;
        var nowOpen = body.style.display === 'none';
        open[toggle.dataset.key] = nowOpen;
        body.style.display = nowOpen ? '' : 'none';
        toggle.querySelector('.collapse-chevron').innerHTML = nowOpen ? '&#9662;' : '&#9656;';
    }
    armsBox.addEventListener('keydown', function(e) {
        var toggle = e.target.closest('.rem-toggle');
        if (toggle && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggleSection(toggle); }
    });

    armsBox.addEventListener('click', function(e) {
        var toggle = e.target.closest('.rem-toggle');
        if (toggle) { toggleSection(toggle); return; }
        var target = e.target.closest('button');
        if (!target || !target.closest('.reminder-arm')) return;
        var t = where(target);
        var key = 'a' + t.ai + '-r' + t.ri;
        if (target.classList.contains('rem-cal-nav')) {
            // Browsing months works on a locked page too; it changes nothing
            var p = views[key].split('-').map(Number);
            var d = new Date(p[0], p[1] - 1 + parseInt(target.dataset.step, 10), 1);
            views[key] = d.getFullYear() + '-' + pad(d.getMonth() + 1);
            render();
            return;
        }
        if (locked) return;
        if (target.classList.contains('rem-add')) {
            // A new notification starts at the previous one's time
            var last = t.arm.rules[t.arm.rules.length - 1];
            t.arm.rules.push({ message: '', time: last ? last.time : '12:00', dates: [] });
            open['a' + t.ai + '-r' + (t.arm.rules.length - 1)] = true;
        } else if (target.classList.contains('rem-remove')) {
            if (t.rule.message && !confirm('Remove this notification?')) return;
            t.arm.rules.splice(t.ri, 1);
        } else if (target.classList.contains('rem-copy')) {
            if ((t.arm.note || t.arm.rules.length) && !confirm('Replace this arm\'s notifications with a copy of the first arm\'s?')) return;
            plan.arms[t.ai] = JSON.parse(JSON.stringify(plan.arms[0]));
        } else if (target.classList.contains('rem-day')) {
            var i = t.rule.dates.indexOf(target.dataset.date);
            if (i === -1) t.rule.dates.push(target.dataset.date); else t.rule.dates.splice(i, 1);
            t.rule.dates.sort();
        } else if (target.classList.contains('rem-fill')) {
            var cal = target.closest('.rem-cal');
            var from = cal.querySelector('.rem-fill-from').value, to = cal.querySelector('.rem-fill-to').value;
            var every = cal.querySelector('.rem-fill-every').value;
            if (!from || !to || to < from) { alert('Choose the first and last day.'); return; }
            var day = parseIso(from), end = parseIso(to);
            while (day <= end && t.rule.dates.length < 60) {
                var v = iso(day);
                var ok = every !== 'weekdays' || (day.getDay() > 0 && day.getDay() < 6);
                if (ok && v >= today && (!limit || v <= limit) && t.rule.dates.indexOf(v) === -1) t.rule.dates.push(v);
                day.setDate(day.getDate() + (every === 'weekdays' ? 1 : parseInt(every, 10)));
            }
            t.rule.dates.sort();
            views[key] = from.slice(0, 7);
        } else if (target.classList.contains('rem-clear')) {
            if (!confirm('Unselect all the days of this notification?')) return;
            t.rule.dates = [];
        } else {
            return;
        }
        render();
        scheduleSave();
    });

    // Follow the survey form: arms added, removed or renamed
    document.addEventListener('arms-changed', function(e) {
        if (e.detail && e.detail.removed !== undefined) plan.arms.splice(e.detail.removed, 1);
        render();
        scheduleSave();
    });
    var renameTimer = null;
    var armsContainer = document.getElementById('arms-container');
    if (armsContainer) {
        armsContainer.addEventListener('input', function() {
            clearTimeout(renameTimer);
            renameTimer = setTimeout(render, 300);
        });
    }

    render();
    showApproval(state.approval);
    showProblems(state.problems || []);
});
