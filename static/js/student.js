document.addEventListener('DOMContentLoaded', function() {
    var currentSurveyId = null;
    var currentArmId = null;
    var currentState = 'waiting';
    var answers = {}; // keyed by question_id: {answer_text, answer_index}
    var submittedSurveyIds = {}; // track surveys we've already submitted
    var declinedSurveyIds = {};  // surveys whose consent screen they declined (nothing is recorded)
    var isSubmitting = false;
    var statePollTimer = null;
    var currentQuestionIndex = 0;
    var questionsData = []; // store questions for navigation and piping
    var introActive = false;  // the survey's intro / consent screen is showing

    // Answers being built for the newer types: ranking order, grid ratings, price-list / lottery choices
    var rankState = {};  // question_id -> [option index, ...] in the order tapped
    var gridState = {};  // question_id -> {row index: value}
    var listState = {};  // question_id -> ['A' | 'B' | null, ...]

    // Time on each question: the clock runs only while that question is shown and the
    // page is in view. Switching apps/tabs pauses it and flags the question (left_page).
    var timeSpent = {};   // question_id -> seconds
    var leftPage = {};    // question_id -> true if the respondent switched away on it
    var clockStart = null;

    function currentQid() {
        var q = questionsData[currentQuestionIndex];
        return q ? q.question_id : null;
    }
    function stopClock() {
        var qid = currentQid();
        if (clockStart !== null && qid !== null) {
            timeSpent[qid] = (timeSpent[qid] || 0) + (performance.now() - clockStart) / 1000;
        }
        clockStart = null;
    }
    function startClock() {
        if (currentState === 'answering' && !introActive && document.visibilityState === 'visible' && clockStart === null) {
            clockStart = performance.now();
        }
    }
    document.addEventListener('visibilitychange', function() {
        if (currentState !== 'answering' || introActive) return;
        if (document.visibilityState === 'hidden') {
            stopClock();
            var qid = currentQid();
            if (qid !== null) leftPage[qid] = true;
        } else {
            startClock();
        }
    });

    // --- Question timers (set per arm by the builders) ---
    // Each timed question gets a wall-clock deadline the first time it's shown. It keeps
    // running if the respondent switches apps or goes back, and is remembered in this
    // browser so reloading doesn't restart it. When it runs out, an answer already given
    // stands; otherwise the builders' default is recorded and marked timed out.
    var deadlines = {};   // question_id -> ms since epoch
    var expired = {};     // question_id -> true once its time is up
    var timedOut = {};    // question_id -> true if the default was recorded
    var sliderMoved = {}; // question_id -> true once a slider was touched
    var timerTick = null;

    function questionById(qid) {
        for (var i = 0; i < questionsData.length; i++) {
            if (questionsData[i].question_id === qid) return questionsData[i];
        }
        return null;
    }
    function sectionOf(qid) {
        return document.querySelector('.question-section[data-question-id="' + qid + '"]');
    }
    function timerKey(qid) {
        // Only real respondents keep deadlines across reloads (previews start fresh)
        return (typeof PARTICIPANT_ID !== 'undefined' && PARTICIPANT_ID > 0)
            ? 'qtimer-' + PARTICIPANT_ID + '-' + currentSurveyId + '-' + currentArmId + '-' + qid : null;
    }
    function startTimerFor(q) {
        if (!q || !q.timer || deadlines[q.question_id]) return;
        var key = timerKey(q.question_id), stored = null;
        try { stored = key ? parseInt(localStorage.getItem(key), 10) : null; } catch (e) {}
        deadlines[q.question_id] = stored || (Date.now() + q.timer.seconds * 1000);
        if (key && !stored) { try { localStorage.setItem(key, String(deadlines[q.question_id])); } catch (e) {} }
    }
    function formatClock(ms) {
        var secs = Math.max(0, Math.ceil(ms / 1000));
        return Math.floor(secs / 60) + ':' + ('0' + (secs % 60)).slice(-2);
    }
    function hasAnswer(q) {
        return stateOf(q) === 'complete' && !problemWith(q);
    }
    function defaultAnswer(q) {
        var d = q.timer.default || '';
        if (q.question_type === 'multiple_choice' || q.question_type === 'picture_choice') {
            var idx = q.options.indexOf(d);
            return { answer_text: d, answer_index: idx >= 0 ? idx : null };
        }
        if (q.question_type === 'multiple_answer') {
            return { answer_text: d ? JSON.stringify([d]) : '', answer_index: null };
        }
        if (q.question_type === 'rating') {
            var pos = d === '' ? -1 : q.scale.values.indexOf(Number(d));
            return { answer_text: pos >= 0 ? d : '', answer_index: pos >= 0 ? pos : null };
        }
        if (JSON_TYPES.indexOf(q.question_type) !== -1) return { answer_text: '', answer_index: null };
        return { answer_text: d, answer_index: null };
    }
    function expire(q) {
        var qid = q.question_id;
        if (expired[qid]) return;
        expired[qid] = true;
        captureCurrentAnswer();
        var answeredInTime = hasAnswer(q);
        if (answeredInTime) {
            answers[qid] = buildAnswer(q);
        } else {
            timedOut[qid] = true;
            answers[qid] = defaultAnswer(q);
        }
        var section = sectionOf(qid);
        if (section) {
            section.querySelectorAll('button, input').forEach(function(el) { el.disabled = true; });
            var msg = section.querySelector('.timeout-msg');
            var recorded = answers[qid].answer_text;
            if (msg) {
                msg.textContent = answeredInTime ? 'Time’s up! Your answer was recorded.'
                    : (recorded ? 'Time’s up! The answer "' + recorded + '" was recorded.'
                                : 'Time’s up! No answer was recorded.');
                msg.style.display = '';
            }
        }
        updateTimerDisplay(q);
        // Move on by itself, unless this is the last question (then they just submit)
        updateNav();
        if (currentQid() === qid && nextVisible(currentQuestionIndex) !== -1) {
            var from = currentQuestionIndex;
            setTimeout(function() {
                var next = nextVisible(from);
                if (currentState === 'answering' && currentQuestionIndex === from && next !== -1) showQuestion(next);
            }, 1500);
        }
    }
    function updateTimerDisplay(q) {
        var box = document.querySelector('.q-timer[data-qid="' + q.question_id + '"]');
        if (!box || !deadlines[q.question_id]) return;
        var left = expired[q.question_id] ? 0 : deadlines[q.question_id] - Date.now();
        var count = box.querySelector('.timer-count');
        if (count) count.textContent = formatClock(left);
        var bar = box.querySelector('.timer-bar');
        if (bar) {
            var pct = Math.max(0, Math.min(100, left / (q.timer.seconds * 1000) * 100));
            bar.style.width = pct + '%';
            bar.className = 'progress-bar timer-bar ' + (pct <= 15 ? 'bg-danger' : pct <= 40 ? 'bg-warning' : 'bg-primary');
        }
    }
    function tickTimers() {
        if (currentState !== 'answering' || introActive) return;
        var q = questionsData[currentQuestionIndex];
        if (!q || !q.timer) return;
        updateTimerDisplay(q);
        if (!expired[q.question_id] && Date.now() >= deadlines[q.question_id]) expire(q);
    }
    // Questions whose time ran out while the respondent was elsewhere (e.g. went back)
    function expireOverdue() {
        questionsData.forEach(function(q) {
            if (q.timer && deadlines[q.question_id] && !expired[q.question_id] && Date.now() >= deadlines[q.question_id]) expire(q);
        });
    }
    function timerHtml(q) {
        var show = q.timer.display || 'both';
        var html = '<div class="q-timer mb-3" data-qid="' + q.question_id + '">';
        if (show === 'both' || show === 'countdown') {
            html += '<div class="d-flex justify-content-end align-items-baseline gap-2 mb-1">'
                  + '<span class="small text-muted">Time left</span><strong class="fs-4 timer-count">'
                  + formatClock(q.timer.seconds * 1000) + '</strong></div>';
        }
        if (show === 'both' || show === 'bar') {
            html += '<div class="progress" style="height: 10px;" role="progressbar" aria-label="Time left">'
                  + '<div class="progress-bar timer-bar bg-primary" style="width: 100%; transition: width 0.2s linear;"></div></div>';
        }
        return html + '<div class="timeout-msg alert alert-warning py-2 small mt-2 mb-0" style="display:none"></div></div>';
    }

    // "Other" choice: the typed text for a question, or '' if none
    function otherText(qid) {
        var input = document.querySelector('.other-input[data-qid="' + qid + '"]');
        return input ? input.value.trim() : '';
    }
    function otherChosen(qid) {
        var btn = document.querySelector('.btn-other[data-qid="' + qid + '"]');
        return !!(btn && btn.classList.contains('btn-primary'));
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    var JSON_TYPES = ['ranking', 'rating_grid', 'budget', 'price_list', 'lottery'];

    // An answer as readable text (for {{Qn}} piping)
    function readable(q, ans) {
        var text = ans.answer_text;
        if (!text) return '';
        var typed = otherChosen(q.question_id) ? otherText(q.question_id) : '';
        try {
            if (q.question_type === 'multiple_answer' || q.question_type === 'ranking') {
                return JSON.parse(text).map(function(a) { return (a === 'Other' && typed) ? typed : a; }).join(', ');
            }
            if (q.question_type === 'rating_grid' || q.question_type === 'budget') {
                var obj = JSON.parse(text);
                return Object.keys(obj).map(function(k) { return k + ': ' + obj[k]; }).join(', ');
            }
            if (q.question_type === 'price_list' || q.question_type === 'lottery') return JSON.parse(text).join(' ');
        } catch (e) { return text; }
        if (q.question_type === 'rating') {
            var label = q.scale.labels[q.scale.values.indexOf(Number(text))];
            return label || text;
        }
        if (text === 'Other' && typed) return typed;
        return text;
    }

    // Answer piping: replace {{Q1}}, {{Q2}}, etc. with answers from earlier questions
    function pipeAnswers(text) {
        return text.replace(/\{\{Q(\d+)\}\}/gi, function(match, num) {
            // {{Q1}} is Question 1 of the design, even if this arm skips some questions
            var qIndex = questionByIndex(parseInt(num) - 1);
            if (qIndex < 0) return match;
            var q = questionsData[qIndex];
            var ans = answers[q.question_id];
            if (!ans) return match; // not answered yet, keep placeholder
            if (ans.answer_text === '') return '(no answer)';
            return readable(q, ans) || match;
        });
    }

    // --- Display rules ---
    // The server only sends this arm's questions. A question with a `condition` is shown
    // only if the earlier question it names (by its index in the design) was shown and
    // answered with one of the condition's values.
    function questionByIndex(designIndex) {
        for (var i = 0; i < questionsData.length; i++) {
            if (questionsData[i].question_index === designIndex) return i;
        }
        return -1;
    }
    function answerIncludes(qid, values) {
        var ans = answers[qid];
        if (!ans || !ans.answer_text) return false;
        var chosen = [ans.answer_text];
        if (ans.answer_text.charAt(0) === '[') {
            try { chosen = JSON.parse(ans.answer_text); } catch (e) {}
        }
        return chosen.some(function(c) { return values.indexOf(c) !== -1; });
    }
    function isVisible(i) {
        var q = questionsData[i];
        if (!q) return false;
        if (!q.condition) return true;
        var src = questionByIndex(q.condition.question_index);
        if (src < 0 || src >= i || !isVisible(src)) return false;
        return answerIncludes(questionsData[src].question_id, q.condition.values);
    }
    function nextVisible(from) {
        for (var i = from + 1; i < questionsData.length; i++) { if (isVisible(i)) return i; }
        return -1;
    }
    function prevVisible(from) {
        for (var i = from - 1; i >= 0; i--) { if (isVisible(i)) return i; }
        return -1;
    }
    function visibleCount() {
        var n = 0;
        for (var i = 0; i < questionsData.length; i++) { if (isVisible(i)) n++; }
        return n;
    }
    function visiblePosition(index) {
        var n = 0;
        for (var i = 0; i <= index; i++) { if (isVisible(i)) n++; }
        return n;
    }

    // Navigation buttons and "Question x of y" for the current question; answers can
    // reveal or hide later questions, so this runs again after every choice
    function updateNav() {
        var prevBtn = document.getElementById('prev-question');
        var nextBtn = document.getElementById('next-question');
        var submitBtn = document.getElementById('submit-all');
        var navDiv = document.getElementById('question-nav');
        var progress = document.getElementById('question-progress');
        if (introActive) {
            navDiv.style.display = 'none';
            submitBtn.style.display = 'none';
            progress.style.display = 'none';
            return;
        }
        var index = currentQuestionIndex;
        var total = visibleCount();
        document.getElementById('q-current-num').textContent = visiblePosition(index);
        document.getElementById('q-total-num').textContent = total;
        progress.style.display = total > 1 ? '' : 'none';

        var isLast = nextVisible(index) === -1;
        if (total <= 1 && isLast) {
            navDiv.style.display = 'none';
            submitBtn.style.display = '';
        } else {
            navDiv.style.display = '';
            prevBtn.disabled = prevVisible(index) === -1;
            nextBtn.style.display = isLast ? 'none' : '';
            submitBtn.style.display = isLast ? '' : 'none';
        }
    }

    // State management
    function showState(state) {
        console.log('[student] state ->', state);
        currentState = state;
        document.querySelectorAll('.state-panel').forEach(function(p) { p.classList.remove('active'); });
        document.getElementById('state-' + state).classList.add('active');
    }

    function setSubmitEnabled(enabled) {
        var btn = document.getElementById('submit-all');
        if (!btn) return;
        btn.disabled = !enabled;
        btn.textContent = enabled ? 'Submit All Answers' : 'Submitting...';
    }

    function markSubmitted(surveyId) {
        var sid = surveyId || currentSurveyId;
        if (sid) submittedSurveyIds[sid] = true;
        isSubmitting = false;
        setSubmitEnabled(true);
        showState('submitted');
        // Lets the page offer the optional feedback note for this survey
        if (sid) document.dispatchEvent(new CustomEvent('survey-submitted', { detail: { surveyId: sid } }));
    }

    function markSubmitFailed(message) {
        isSubmitting = false;
        setSubmitEnabled(true);
        showState('answering');
        startClock();
        alert(message || 'Your answer was not saved. Please try again.');
    }

    // --- Sequential question navigation ---

    function showQuestion(index) {
        stopClock();
        currentQuestionIndex = index;
        startClock();
        startTimerFor(questionsData[index]);
        expireOverdue();
        if (questionsData[index] && questionsData[index].timer) updateTimerDisplay(questionsData[index]);
        var sections = document.querySelectorAll('.question-section');
        sections.forEach(function(s, i) {
            s.style.display = (i === index) ? '' : 'none';
        });

        // Apply answer piping to the visible question's text, and number it among the
        // questions this respondent actually sees
        if (questionsData[index]) {
            var section = sections[index];
            var pElem = section.querySelector('.question-text-display');
            if (pElem) {
                pElem.innerHTML = escapeHtml(pipeAnswers(questionsData[index].question_text));
            }
            var header = section.querySelector('.q-header');
            if (header) {
                var label = questionsData[index].label;
                header.textContent = 'Question ' + visiblePosition(index) + (label ? ': ' + label : '');
            }
        }

        updateNav();
    }

    // --- Where each answer stands: 'empty', 'partial' (started, not finished) or 'complete' ---
    function stateOf(q) {
        var qid = q.question_id;
        var section = sectionOf(qid);
        var t = q.question_type;
        if (t === 'multiple_choice' || t === 'multiple_answer' || t === 'picture_choice') {
            if (!answers[qid]) return 'empty';
            return (otherChosen(qid) && !otherText(qid)) ? 'partial' : 'complete';
        }
        if (t === 'short_answer' || t === 'numeric') {
            var input = section && section.querySelector('.short-answer-input, .numeric-answer-input');
            return input && input.value.trim() !== '' ? 'complete' : 'empty';
        }
        if (t === 'slider') return (q.required || sliderMoved[qid]) ? 'complete' : 'empty';
        if (t === 'rating') return answers[qid] ? 'complete' : 'empty';
        if (t === 'ranking') {
            var ranked = (rankState[qid] || []).length;
            return ranked === 0 ? 'empty' : ranked === q.options.length ? 'complete' : 'partial';
        }
        if (t === 'rating_grid') {
            var rated = Object.keys(gridState[qid] || {}).length;
            return rated === 0 ? 'empty' : rated === q.options.length ? 'complete' : 'partial';
        }
        if (t === 'price_list' || t === 'lottery') {
            var picks = (listState[qid] || []).filter(function(c) { return c; }).length;
            return picks === 0 ? 'empty' : picks === q.rows.length ? 'complete' : 'partial';
        }
        if (t === 'budget') {
            var filled = 0;
            section.querySelectorAll('.budget-input').forEach(function(i) { if (i.value.trim() !== '') filled++; });
            if (filled === 0) return 'empty';
            var b = budgetTotals(q);
            return b.valid && Math.abs(b.sum - q.total) < 1e-6 ? 'complete' : 'partial';
        }
        return 'empty';
    }

    function budgetTotals(q) {
        var sum = 0, valid = true;
        sectionOf(q.question_id).querySelectorAll('.budget-input').forEach(function(input) {
            if (input.value.trim() === '') return;
            var v = Number(input.value);
            if (isNaN(v) || v < 0 || (q.integer && v !== Math.floor(v))) valid = false;
            else sum += v;
        });
        return { sum: Math.round(sum * 1e6) / 1e6, valid: valid };
    }

    // The answer to store for a complete question
    function buildAnswer(q) {
        var qid = q.question_id, t = q.question_type, section = sectionOf(qid);
        if (t === 'short_answer') return { answer_text: section.querySelector('.short-answer-input').value.trim(), answer_index: null };
        if (t === 'numeric') return { answer_text: section.querySelector('.numeric-answer-input').value, answer_index: null };
        if (t === 'slider') return { answer_text: section.querySelector('.slider-answer-input').value, answer_index: null };
        if (t === 'ranking') {
            return { answer_text: JSON.stringify(rankState[qid].map(function(i) { return q.options[i]; })), answer_index: null };
        }
        if (t === 'rating_grid') {
            var obj = {};
            q.options.forEach(function(row, i) { obj[row] = gridState[qid][i]; });
            return { answer_text: JSON.stringify(obj), answer_index: null };
        }
        if (t === 'budget') {
            var amounts = {};
            section.querySelectorAll('.budget-input').forEach(function(input) {
                amounts[q.options[parseInt(input.dataset.index, 10)]] = input.value.trim() === '' ? 0 : Number(input.value);
            });
            var ordered = {};
            q.options.forEach(function(item) { ordered[item] = amounts[item]; });
            return { answer_text: JSON.stringify(ordered), answer_index: null };
        }
        if (t === 'price_list' || t === 'lottery') {
            var choices = listState[qid];
            return { answer_text: JSON.stringify(choices), answer_index: choices.filter(function(c) { return c === 'A'; }).length };
        }
        return answers[qid];
    }

    // A complete answer that breaks a rule (number limits), or null
    function problemWith(q) {
        if (q.question_type !== 'numeric') return null;
        var input = sectionOf(q.question_id).querySelector('.numeric-answer-input');
        var v = Number(input.value);
        if (input.value.trim() === '' || isNaN(v)) return 'Please type a number.';
        if (q.integer && v !== Math.floor(v)) return 'Please type a whole number.';
        if (q.min !== null && q.min !== undefined && v < q.min) return 'Please type a number of at least ' + q.min + '.';
        if (q.max !== null && q.max !== undefined && v > q.max) return 'Please type a number no larger than ' + q.max + '.';
        return null;
    }

    // Why a question can't be left yet ('' = fine)
    function blocker(q) {
        if (expired[q.question_id]) return '';
        var state = stateOf(q);
        if (state === 'complete') return problemWith(q) || '';
        if (state === 'empty') return q.required ? 'Please answer this question before continuing.' : '';
        var t = q.question_type, msg;
        if (t === 'ranking') msg = 'Please rank all the items: tap them in order, starting with your favorite.';
        else if (t === 'rating_grid') msg = 'Please rate every statement.';
        else if (t === 'price_list' || t === 'lottery') msg = 'Please choose A or B in every row.';
        else if (t === 'budget') {
            var b = budgetTotals(q);
            msg = !b.valid ? (q.integer ? 'Please use whole numbers of 0 or more.' : 'Please use numbers of 0 or more.')
                           : 'The amounts must add up to ' + q.total + ' (now ' + b.sum + ').';
        } else msg = 'Please type your answer in the "Other" box, or pick another option.';
        return msg + (q.required ? '' : ' Or tap "Clear answer" to skip it.');
    }

    // Capture short_answer and numeric values into the answers object (needed for piping)
    function captureCurrentAnswer() {
        var q = questionsData[currentQuestionIndex];
        if (!q || timedOut[q.question_id]) return;  // the recorded default stands
        if (q.question_type === 'short_answer' || q.question_type === 'numeric') {
            if (stateOf(q) === 'complete') answers[q.question_id] = buildAnswer(q);
            else delete answers[q.question_id];
        }
    }

    // The options in the order this respondent sees them (shuffled questions carry `order`)
    function displayOrder(q, n) {
        if (q.order && q.order.length === n) return q.order;
        var out = [];
        for (var i = 0; i < n; i++) out.push(i);
        return out;
    }

    function choiceButtons(q, cls, wrapCls) {
        var html = '<div class="' + wrapCls + ' d-grid gap-2" data-qid="' + q.question_id + '">';
        displayOrder(q, q.options.length).forEach(function(oidx) {
            var opt = q.options[oidx];
            html += '<button type="button" class="btn btn-outline-primary btn-lg ' + cls + '" '
                  + 'data-qid="' + q.question_id + '" data-answer="' + escapeHtml(opt) + '" data-index="' + oidx + '">'
                  + escapeHtml(opt) + '</button>';
        });
        if (q.allow_other) {
            html += '<button type="button" class="btn btn-outline-primary btn-lg ' + cls + ' btn-other" '
                  + 'data-qid="' + q.question_id + '" data-answer="Other" data-index="' + q.options.length + '">Other</button>';
        }
        html += '</div>';
        if (q.allow_other) {
            html += '<input type="text" class="form-control form-control-lg mt-2 other-input" style="display:none" '
                  + 'data-qid="' + q.question_id + '" maxlength="140" placeholder="Please specify...">';
        }
        return html;
    }

    // Labels under a scale: the two ends (and the middle, if labeled)
    function scaleEnds(scale) {
        var n = scale.values.length, mid = n % 2 === 1 ? scale.labels[(n - 1) / 2] : '';
        return '<div class="d-flex justify-content-between small text-muted mt-1 gap-2">'
             + '<span>' + escapeHtml(scale.labels[0] || '') + '</span>'
             + (mid ? '<span class="text-center">' + escapeHtml(mid) + '</span>' : '')
             + '<span class="text-end">' + escapeHtml(scale.labels[n - 1] || '') + '</span></div>';
    }

    // The input part of a question, by type
    function inputHtml(q) {
        var qid = q.question_id, html = '';
        var t = q.question_type;
        if (t === 'multiple_choice') {
            html += choiceButtons(q, 'btn-mc-option', 'mc-buttons');
        } else if (t === 'multiple_answer') {
            html += '<p class="text-muted small mb-2">Select all that apply:</p>' + choiceButtons(q, 'btn-ma-option', 'ma-buttons');
        } else if (t === 'picture_choice') {
            html += '<div class="row row-cols-2 g-2 pic-options" data-qid="' + qid + '">';
            displayOrder(q, q.pictures.length).forEach(function(i) {
                var p = q.pictures[i];
                html += '<div class="col"><button type="button" class="btn btn-outline-primary w-100 h-100 p-1 pic-option" '
                      + 'data-qid="' + qid + '" data-index="' + i + '" data-answer="' + escapeHtml(p.label) + '">'
                      + (p.url ? '<img src="' + p.url + '" alt="' + escapeHtml(p.label) + '" class="img-fluid rounded" style="max-height: 180px; object-fit: contain;">' : '')
                      + '<div class="small mt-1">' + escapeHtml(p.label) + '</div></button></div>';
            });
            html += '</div>';
        } else if (t === 'rating') {
            var sc = q.scale, labeled = sc.labels.every(function(l) { return l; });
            if (labeled && sc.values.length <= 7) {
                // Every point labeled: a list of labeled buttons (easiest to read on a phone)
                html += '<div class="rating-buttons d-grid gap-2" data-qid="' + qid + '">';
                sc.values.forEach(function(v, i) {
                    html += '<button type="button" class="btn btn-outline-primary btn-lg text-start btn-rating" data-qid="' + qid
                          + '" data-value="' + v + '" data-index="' + i + '"><span class="badge text-bg-light border me-2">' + v + '</span>'
                          + escapeHtml(sc.labels[i]) + '</button>';
                });
                html += '</div>';
            } else {
                html += '<div class="rating-buttons d-flex gap-1" data-qid="' + qid + '">';
                sc.values.forEach(function(v, i) {
                    html += '<button type="button" class="btn btn-outline-primary px-0 py-2 btn-rating" style="flex: 1 1 0; min-width: 0;" '
                          + 'data-qid="' + qid + '" data-value="' + v + '" data-index="' + i + '"'
                          + (sc.labels[i] ? ' title="' + escapeHtml(sc.labels[i]) + '"' : '') + '>' + v + '</button>';
                });
                html += '</div>' + scaleEnds(sc);
            }
        } else if (t === 'rating_grid') {
            var g = q.scale, all = g.labels.every(function(l) { return l; });
            if (all) {
                html += '<p class="small text-muted mb-2">' + g.values.map(function(v, i) { return v + ' = ' + escapeHtml(g.labels[i]); }).join(' &middot; ') + '</p>';
            }
            displayOrder(q, q.options.length).forEach(function(r) {
                html += '<div class="grid-row border rounded p-2 mb-2" data-qid="' + qid + '" data-row="' + r + '">'
                      + '<div class="fw-semibold mb-2">' + escapeHtml(q.options[r]) + '</div><div class="d-flex gap-1">';
                g.values.forEach(function(v) {
                    html += '<button type="button" class="btn btn-outline-primary btn-sm px-0 py-2 btn-grid" style="flex: 1 1 0; min-width: 0;" '
                          + 'data-qid="' + qid + '" data-row="' + r + '" data-value="' + v + '">' + v + '</button>';
                });
                html += '</div>' + (all ? '' : scaleEnds(g)) + '</div>';
            });
        } else if (t === 'ranking') {
            html += '<p class="text-muted small mb-2">Tap the items in order, starting with your favorite. Tap one again to undo it.</p>'
                  + '<div class="rank-list d-grid gap-2" data-qid="' + qid + '">';
            displayOrder(q, q.options.length).forEach(function(i) {
                html += '<button type="button" class="btn btn-outline-primary btn-lg text-start btn-rank" data-qid="' + qid + '" data-index="' + i + '">'
                      + '<span class="badge rounded-pill text-bg-light border me-2 rank-badge">&nbsp;</span>' + escapeHtml(q.options[i]) + '</button>';
            });
            html += '</div>';
        } else if (t === 'budget') {
            html += '<p class="text-muted small mb-2">Split <strong>' + q.total + '</strong> between these. The amounts must add up to ' + q.total + '.</p>';
            displayOrder(q, q.options.length).forEach(function(i) {
                html += '<div class="input-group mb-2"><span class="input-group-text flex-grow-1 text-wrap text-start">' + escapeHtml(q.options[i]) + '</span>'
                      + '<input type="number" inputmode="decimal" min="0" step="' + (q.integer ? '1' : 'any') + '" class="form-control budget-input" style="max-width: 7rem;" '
                      + 'data-qid="' + qid + '" data-index="' + i + '" placeholder="0"></div>';
            });
            html += '<div class="budget-total fw-semibold small" data-qid="' + qid + '">Total: 0 of ' + q.total + '</div>';
        } else if (t === 'price_list' || t === 'lottery') {
            html += '<p class="text-muted small mb-2">In each row, choose option A or option B.'
                  + (q.single_switch ? ' Choosing B in a row also picks B in the rows below it; choosing A also picks A in the rows above it.' : '') + '</p>'
                  + '<div class="list-rows" data-qid="' + qid + '">';
            q.rows.forEach(function(row, i) {
                html += '<div class="list-row border rounded p-2 mb-2" data-row="' + i + '"><div class="small text-muted mb-1">Row ' + (i + 1) + '</div>'
                      + '<div class="row g-2">'
                      + ['A', 'B'].map(function(c) {
                            return '<div class="col-6"><button type="button" class="btn btn-outline-primary w-100 h-100 text-start small btn-list" '
                                 + 'data-qid="' + qid + '" data-row="' + i + '" data-choice="' + c + '"><strong>' + c + ':</strong> '
                                 + escapeHtml(c === 'A' ? row.a : row.b) + '</button></div>';
                        }).join('')
                      + '</div></div>';
            });
            html += '</div>';
        } else if (t === 'short_answer') {
            html += '<div class="mb-1">'
                  + '<input type="text" class="form-control form-control-lg short-answer-input" '
                  + 'data-qid="' + qid + '" placeholder="Type your answer..." maxlength="140">'
                  + '</div>'
                  + '<small class="text-muted"><span class="char-count" data-qid="' + qid + '">0</span>/140</small>';
        } else if (t === 'slider') {
            var sMin = q.slider_min != null ? q.slider_min : 0;
            var sMax = q.slider_max != null ? q.slider_max : 100;
            var sStep = q.slider_step != null ? q.slider_step : 1;
            var sDefault = Math.round(((sMin + sMax) / 2) / sStep) * sStep;
            html += '<div class="slider-container mb-2">'
                  + '<input type="range" class="form-range slider-answer-input" '
                  + 'data-qid="' + qid + '" '
                  + 'min="' + sMin + '" max="' + sMax + '" step="' + sStep + '" '
                  + 'value="' + sDefault + '">'
                  + '<div class="d-flex justify-content-between">'
                  + '<small class="text-muted">' + sMin + '</small>'
                  + '<strong class="slider-value-display" data-qid="' + qid + '">' + sDefault + '</strong>'
                  + '<small class="text-muted">' + sMax + '</small>'
                  + '</div></div>';
            // A required slider counts as answered at its starting value (an optional one only once moved)
            if (q.required) answers[qid] = { answer_text: String(sDefault), answer_index: null };
        } else {
            // numeric
            var limits = (q.min !== null && q.min !== undefined ? ' min="' + q.min + '"' : '')
                       + (q.max !== null && q.max !== undefined ? ' max="' + q.max + '"' : '');
            html += '<div class="input-group input-group-lg">'
                  + '<input type="number" class="form-control numeric-answer-input" '
                  + 'data-qid="' + qid + '" placeholder="Enter a number" step="' + (q.integer ? '1' : 'any') + '"' + limits
                  + (q.integer ? ' inputmode="numeric"' : '') + '>'
                  + '</div>';
            if ((q.min !== null && q.min !== undefined) || (q.max !== null && q.max !== undefined)) {
                html += '<small class="text-muted">' + (q.min !== null && q.min !== undefined ? 'From ' + q.min : 'Up')
                      + (q.max !== null && q.max !== undefined ? ' to ' + q.max : '') + (q.integer ? ', whole numbers' : '') + '</small>';
            } else if (q.integer) {
                html += '<small class="text-muted">Whole numbers</small>';
            }
        }
        if (!q.required) {
            html += '<div class="mt-2"><a href="#" class="small text-muted clear-answer" data-qid="' + qid + '">Clear answer</a></div>';
        }
        return html;
    }

    function sectionHtml(q, idx) {
        var headerText = 'Question ' + (idx + 1);
        if (q.label) headerText += ': ' + q.label;
        var html = (q.timer ? timerHtml(q) : '') + '<h5 class="q-header">' + escapeHtml(headerText) + '</h5>';
        if (q.image_url) {
            html += '<img src="' + q.image_url + '" class="img-fluid mb-2 rounded" style="max-height:300px;" alt="Question image">';
        }
        html += '<p class="fs-5 mb-' + (q.required ? '3' : '1') + ' question-text-display">' + escapeHtml(q.question_text) + '</p>';
        if (!q.required) html += '<p class="small text-muted mb-3">Optional: you can skip this question.</p>';
        return html + inputHtml(q);
    }

    function resetAnswerState() {
        answers = {};
        rankState = {};
        gridState = {};
        listState = {};
        timeSpent = {};
        leftPage = {};
        deadlines = {};
        expired = {};
        timedOut = {};
        sliderMoved = {};
    }

    // The intro / consent screen before the first question
    function introHtml(intro) {
        var html = '<div class="intro-section">';
        if (intro.text) html += '<p class="fs-5" style="white-space: pre-wrap;">' + escapeHtml(intro.text) + '</p>';
        if (intro.consent) {
            html += '<div class="d-grid gap-2 mt-3"><button type="button" class="btn btn-primary btn-lg intro-start">I agree, start</button>'
                  + '<button type="button" class="btn btn-outline-secondary intro-decline">I don’t want to take part</button></div>';
        } else {
            html += '<button type="button" class="btn btn-primary btn-lg w-100 mt-3 intro-start">Start</button>';
        }
        return html + '</div>';
    }

    function renderAssignment(data) {
        console.log('[student] assignment survey=' + data.survey_id +
                    ' arm=' + data.arm_id + ' questions=' + data.questions.length);

        if (submittedSurveyIds[data.survey_id]) {
            console.log('[student] already submitted survey ' + data.survey_id + ', ignoring assignment');
            showState('submitted');
            return;
        }

        if (currentState === 'answering' && currentSurveyId === data.survey_id && currentArmId === data.arm_id) {
            return;
        }

        currentSurveyId = data.survey_id;
        currentArmId = data.arm_id;
        stopClock();
        resetAnswerState();
        if (timerTick) { clearInterval(timerTick); timerTick = null; }
        questionsData = data.questions;
        currentQuestionIndex = 0;

        document.getElementById('q-group-number').textContent = data.group_number;
        document.getElementById('q-title').textContent = data.title;

        var container = document.getElementById('questions-container');
        container.innerHTML = '';

        data.questions.forEach(function(q, idx) {
            var section = document.createElement('div');
            section.className = 'question-section mb-4';
            section.dataset.questionId = q.question_id;
            section.dataset.questionType = q.question_type;
            section.innerHTML = sectionHtml(q, idx);
            container.appendChild(section);
        });

        introActive = !!data.intro;
        if (introActive) {
            container.insertAdjacentHTML('afterbegin', introHtml(data.intro));
            container.querySelectorAll('.question-section').forEach(function(s) { s.style.display = 'none'; });
            if (declinedSurveyIds[data.survey_id]) showDeclined();
        }
        showState('answering');
        if (data.questions.some(function(q) { return q.timer; })) timerTick = setInterval(tickTimers, 200);
        if (introActive) updateNav();
        else showQuestion(Math.max(0, nextVisible(-1)));
    }

    function showDeclined() {
        var intro = document.querySelector('.intro-section');
        if (intro) intro.innerHTML = '<h5>Thank you.</h5><p class="text-muted mb-0">You chose not to take part in this survey, so nothing was recorded. '
            + (POLL_ONCE ? 'You can go back to your lobby.' : 'Please wait for the next one.') + '</p>';
    }

    document.getElementById('questions-container').addEventListener('click', function(e) {
        if (e.target.closest('.intro-start')) {
            document.querySelector('.intro-section').remove();
            introActive = false;
            showQuestion(Math.max(0, nextVisible(-1)));
        } else if (e.target.closest('.intro-decline')) {
            if (!confirm('Skip this survey? Nothing will be recorded.')) return;
            declinedSurveyIds[currentSurveyId] = true;
            showDeclined();
        }
    });

    function pollStateOnce() {
        fetch(STUDENT_STATE_URL, { credentials: 'same-origin' })
            .then(function(resp) {
                if (!resp.ok) throw new Error('state request failed');
                return resp.json();
            })
            .then(function(data) {
                if (!data.ok) return;
                if (data.state === 'waiting') {
                    if (currentState !== 'waiting') showState('waiting');
                } else if (data.state === 'submitted') {
                    markSubmitted(data.survey_id);
                } else if (data.state === 'blocked_designer' || data.state === 'skip') {
                    // skip: a live part 2 for someone who didn't answer part 1
                    document.getElementById('blocked-title').textContent = data.title || 'You designed this survey';
                    document.getElementById('blocked-message').textContent = data.message ||
                        'You cannot participate in your own survey. Please wait for the next one.';
                    showState('blocked');
                } else if (data.state === 'closed') {
                    if (data.title) document.getElementById('closed-title').textContent = data.title;
                    if (data.message) document.getElementById('closed-message').textContent = data.message;
                    showState('closed');
                } else if (data.state === 'assignment' && data.assignment) {
                    renderAssignment(data.assignment);
                }
            })
            .catch(function(err) {
                console.warn('[student] state poll failed:', err.message);
            });
    }

    function startStatePolling() {
        pollStateOnce();
        if (!statePollTimer) {
            statePollTimer = setInterval(pollStateOnce, 3000);
        }
    }

    function submitViaHttp(payload) {
        return fetch(STUDENT_SUBMIT_URL, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function(resp) {
            if (!resp.ok) throw new Error('submit failed');
            return resp.json();
        });
    }

    function select(btn, group, cls) {
        group.querySelectorAll(cls).forEach(function(b) {
            b.classList.remove('btn-primary');
            b.classList.add('btn-outline-primary');
        });
        btn.classList.remove('btn-outline-primary');
        btn.classList.add('btn-primary');
    }

    var questionsBox = document.getElementById('questions-container');

    // MC option selection (single select) via event delegation
    questionsBox.addEventListener('click', function(e) {
        var btn = e.target.closest('.btn-mc-option');
        if (!btn) return;
        var qid = parseInt(btn.dataset.qid);
        answers[qid] = { answer_text: btn.dataset.answer, answer_index: parseInt(btn.dataset.index) };
        select(btn, btn.closest('.mc-buttons'), '.btn-mc-option');
        toggleOtherInput(qid);
        updateNav();
    });

    // Picture choice and rating scale: one tap picks one
    questionsBox.addEventListener('click', function(e) {
        var btn = e.target.closest('.pic-option, .btn-rating');
        if (!btn) return;
        var qid = parseInt(btn.dataset.qid);
        if (btn.classList.contains('pic-option')) {
            answers[qid] = { answer_text: btn.dataset.answer, answer_index: parseInt(btn.dataset.index) };
            btn.closest('.pic-options').querySelectorAll('.pic-option').forEach(function(b) { b.classList.remove('pic-selected'); });
            btn.classList.add('pic-selected');
        } else {
            answers[qid] = { answer_text: btn.dataset.value, answer_index: parseInt(btn.dataset.index) };
            select(btn, btn.closest('.rating-buttons'), '.btn-rating');
        }
        updateNav();
    });

    // Rating grid: one value per statement
    questionsBox.addEventListener('click', function(e) {
        var btn = e.target.closest('.btn-grid');
        if (!btn) return;
        var qid = parseInt(btn.dataset.qid), q = questionById(qid);
        gridState[qid] = gridState[qid] || {};
        gridState[qid][parseInt(btn.dataset.row)] = Number(btn.dataset.value);
        select(btn, btn.closest('.grid-row'), '.btn-grid');
        if (stateOf(q) === 'complete') answers[qid] = buildAnswer(q); else delete answers[qid];
        updateNav();
    });

    // Ranking: tap in order; tapping a ranked item takes it out (the others move up)
    function drawRanks(q) {
        var order = rankState[q.question_id] || [];
        sectionOf(q.question_id).querySelectorAll('.btn-rank').forEach(function(btn) {
            var pos = order.indexOf(parseInt(btn.dataset.index));
            btn.classList.toggle('btn-primary', pos !== -1);
            btn.classList.toggle('btn-outline-primary', pos === -1);
            btn.querySelector('.rank-badge').innerHTML = pos !== -1 ? String(pos + 1) : '&nbsp;';
        });
    }
    questionsBox.addEventListener('click', function(e) {
        var btn = e.target.closest('.btn-rank');
        if (!btn) return;
        var qid = parseInt(btn.dataset.qid), q = questionById(qid), i = parseInt(btn.dataset.index);
        var order = rankState[qid] = rankState[qid] || [];
        var pos = order.indexOf(i);
        if (pos !== -1) order.splice(pos, 1); else order.push(i);
        drawRanks(q);
        if (stateOf(q) === 'complete') answers[qid] = buildAnswer(q); else delete answers[qid];
        updateNav();
    });

    // Price list / lottery: A or B in each row; with "one switch", B fills the rows below, A the rows above
    function drawList(q) {
        var choices = listState[q.question_id] || [];
        sectionOf(q.question_id).querySelectorAll('.btn-list').forEach(function(btn) {
            var on = choices[parseInt(btn.dataset.row)] === btn.dataset.choice;
            btn.classList.toggle('btn-primary', on);
            btn.classList.toggle('btn-outline-primary', !on);
        });
    }
    questionsBox.addEventListener('click', function(e) {
        var btn = e.target.closest('.btn-list');
        if (!btn) return;
        var qid = parseInt(btn.dataset.qid), q = questionById(qid);
        var row = parseInt(btn.dataset.row), choice = btn.dataset.choice;
        var choices = listState[qid] = listState[qid] || q.rows.map(function() { return null; });
        choices[row] = choice;
        if (q.single_switch) {
            for (var i = 0; i < choices.length; i++) {
                if (choice === 'B' && i > row) choices[i] = 'B';
                if (choice === 'A' && i < row) choices[i] = 'A';
            }
        }
        drawList(q);
        if (stateOf(q) === 'complete') answers[qid] = buildAnswer(q); else delete answers[qid];
        updateNav();
    });

    // Optional questions: "Clear answer" puts the question back as it was
    questionsBox.addEventListener('click', function(e) {
        var link = e.target.closest('.clear-answer');
        if (!link) return;
        e.preventDefault();
        var qid = parseInt(link.dataset.qid), q = questionById(qid);
        if (expired[qid]) return;
        delete answers[qid]; delete rankState[qid]; delete gridState[qid]; delete listState[qid]; delete sliderMoved[qid];
        var section = sectionOf(qid);
        section.innerHTML = sectionHtml(q, questionsData.indexOf(q));
        if (q.timer) updateTimerDisplay(q);
        showQuestion(currentQuestionIndex);
    });

    function toggleOtherInput(qid) {
        var input = document.querySelector('.other-input[data-qid="' + qid + '"]');
        if (!input) return;
        var show = otherChosen(qid);
        input.style.display = show ? '' : 'none';
        if (show) input.focus();
    }

    // Multiple answer option selection (toggle) via event delegation
    questionsBox.addEventListener('click', function(e) {
        var btn = e.target.closest('.btn-ma-option');
        if (!btn) return;

        var qid = parseInt(btn.dataset.qid);

        // Toggle this button
        if (btn.classList.contains('btn-primary')) {
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-outline-primary');
        } else {
            btn.classList.remove('btn-outline-primary');
            btn.classList.add('btn-primary');
        }

        // Collect all selected options for this question (in the design's order, even if shuffled)
        var group = btn.closest('.ma-buttons');
        var selected = [];
        Array.prototype.slice.call(group.querySelectorAll('.btn-ma-option.btn-primary'))
            .sort(function(a, b) { return parseInt(a.dataset.index) - parseInt(b.dataset.index); })
            .forEach(function(b) { selected.push(b.dataset.answer); });

        if (selected.length > 0) {
            answers[qid] = { answer_text: JSON.stringify(selected), answer_index: null };
        } else {
            delete answers[qid];
        }
        toggleOtherInput(qid);
        updateNav();
    });

    // Short answer character counter, slider value, budget total
    questionsBox.addEventListener('input', function(e) {
        if (e.target.classList.contains('short-answer-input')) {
            var qid = e.target.dataset.qid;
            var counter = document.querySelector('.char-count[data-qid="' + qid + '"]');
            if (counter) counter.textContent = e.target.value.length;
        }
        if (e.target.classList.contains('slider-answer-input')) {
            var sqid = parseInt(e.target.dataset.qid);
            var display = document.querySelector('.slider-value-display[data-qid="' + sqid + '"]');
            if (display) display.textContent = e.target.value;
            answers[sqid] = { answer_text: e.target.value, answer_index: null };
            sliderMoved[sqid] = true;
        }
        if (e.target.classList.contains('budget-input')) {
            var bq = questionById(parseInt(e.target.dataset.qid));
            var b = budgetTotals(bq);
            var total = sectionOf(bq.question_id).querySelector('.budget-total');
            var done = b.valid && Math.abs(b.sum - bq.total) < 1e-6;
            total.textContent = 'Total: ' + b.sum + ' of ' + bq.total + (done ? ' ✓' : (b.sum > bq.total ? ' (too much)' : ''));
            total.className = 'budget-total fw-semibold small ' + (done ? 'text-success' : b.sum > bq.total || !b.valid ? 'text-danger' : '');
            if (stateOf(bq) === 'complete') answers[bq.question_id] = buildAnswer(bq); else delete answers[bq.question_id];
        }
    });

    // Next question button
    document.getElementById('next-question').addEventListener('click', function() {
        var q = questionsData[currentQuestionIndex];
        var problem = q ? blocker(q) : '';
        if (problem) { alert(problem); return; }
        captureCurrentAnswer();
        if (q && !q.required && stateOf(q) === 'empty' && !expired[q.question_id]) answers[q.question_id] = { answer_text: '', answer_index: null };
        var next = nextVisible(currentQuestionIndex);
        if (next !== -1) showQuestion(next);
    });

    // Previous question button
    document.getElementById('prev-question').addEventListener('click', function() {
        captureCurrentAnswer();
        var prev = prevVisible(currentQuestionIndex);
        if (prev !== -1) showQuestion(prev);
    });

    // Submit all answers
    document.getElementById('submit-all').addEventListener('click', function() {
        if (isSubmitting) return;

        // Capture current question's answer before validating
        captureCurrentAnswer();
        stopClock();

        var answersArray = [];
        var firstProblem = '';

        expireOverdue();
        questionsData.forEach(function(q, i) {
            var qid = q.question_id;
            if (!isVisible(i)) return;  // a display rule hid it: nothing to send

            var entry;
            if (timedOut[qid]) {
                entry = { question_id: qid, answer_text: answers[qid].answer_text,
                          answer_index: answers[qid].answer_index, timed_out: true };
            } else {
                var problem = expired[qid] && !hasAnswer(q) ? '' : blocker(q);
                if (problem) { if (!firstProblem) firstProblem = problem; return; }
                if (stateOf(q) === 'complete') {
                    var built = buildAnswer(q);
                    entry = { question_id: qid, answer_text: built.answer_text, answer_index: built.answer_index };
                    if (otherChosen(qid)) entry.other_text = otherText(qid);
                } else {
                    entry = { question_id: qid, answer_text: '', answer_index: null };  // optional, skipped
                }
            }
            entry.seconds = timeSpent[qid] != null ? Math.round(timeSpent[qid] * 10) / 10 : null;
            entry.left_page = !!leftPage[qid];
            entry.position = visiblePosition(i);
            if (q.order) {
                var labels = q.question_type === 'picture_choice' ? q.pictures.map(function(p) { return p.label; }) : q.options;
                entry.display_order = q.order.map(function(k) { return labels[k]; });
            }
            answersArray.push(entry);
        });

        if (firstProblem) {
            startClock();
            alert(firstProblem.indexOf('Please answer this question') === 0 ? 'Please answer all questions before submitting.' : firstProblem);
            return;
        }

        console.log('[student] submitting answers:', JSON.stringify(answersArray));
        isSubmitting = true;
        setSubmitEnabled(false);

        var payload = {
            participant_id: PARTICIPANT_ID,
            survey_id: currentSurveyId,
            arm_id: currentArmId,
            classroom_id: CLASSROOM_ID,
            answers: answersArray,
        };

        submitViaHttp(payload)
            .then(function(data) {
                if (data && data.ok) {
                    questionsData.forEach(function(q) {
                        var key = timerKey(q.question_id);
                        if (key) { try { localStorage.removeItem(key); } catch (e) {} }
                    });
                    if (timerTick) { clearInterval(timerTick); timerTick = null; }
                    markSubmitted(currentSurveyId);
                } else {
                    markSubmitFailed();
                }
            })
            .catch(function() {
                markSubmitFailed('Your answer was not saved. Please try again.');
            });
    });

    // Enter key: advance to next question, or submit on last question
    questionsBox.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && (e.target.classList.contains('numeric-answer-input') || e.target.classList.contains('short-answer-input'))) {
            if (nextVisible(currentQuestionIndex) !== -1) {
                document.getElementById('next-question').click();
            } else {
                document.getElementById('submit-all').click();
            }
        }
    });

    // Previews and early-open surveys load one assignment; there is no live session to watch
    if (typeof POLL_ONCE !== 'undefined' && POLL_ONCE) {
        pollStateOnce();
    } else {
        startStatePolling();
    }
});
