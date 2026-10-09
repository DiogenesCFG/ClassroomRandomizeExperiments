document.addEventListener('DOMContentLoaded', function() {
    var currentSurveyId = null;
    var currentArmId = null;
    var currentState = 'waiting';
    var answers = {}; // keyed by question_id: {answer_text, answer_index}
    var submittedSurveyIds = {}; // track surveys we've already submitted
    var isSubmitting = false;
    var statePollTimer = null;
    var currentQuestionIndex = 0;
    var questionsData = []; // store questions for navigation and piping

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
        if (currentState === 'answering' && document.visibilityState === 'visible' && clockStart === null) {
            clockStart = performance.now();
        }
    }
    document.addEventListener('visibilitychange', function() {
        if (currentState !== 'answering') return;
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
        var qid = q.question_id;
        var section = document.querySelector('.question-section[data-question-id="' + qid + '"]');
        if (q.question_type === 'multiple_choice' || q.question_type === 'multiple_answer') {
            return !!answers[qid] && !(otherChosen(qid) && !otherText(qid));
        }
        if (q.question_type === 'slider') return !!sliderMoved[qid];
        var input = section && section.querySelector('.short-answer-input, .numeric-answer-input');
        return !!(input && input.value.trim() !== '');
    }
    function defaultAnswer(q) {
        var d = q.timer.default || '';
        if (q.question_type === 'multiple_choice') {
            var idx = q.options.indexOf(d);
            return { answer_text: d, answer_index: idx >= 0 ? idx : null };
        }
        if (q.question_type === 'multiple_answer') {
            return { answer_text: d ? JSON.stringify([d]) : '', answer_index: null };
        }
        return { answer_text: d, answer_index: null };
    }
    function expire(q) {
        var qid = q.question_id;
        if (expired[qid]) return;
        expired[qid] = true;
        captureCurrentAnswer();
        var answeredInTime = hasAnswer(q);
        if (!answeredInTime) {
            timedOut[qid] = true;
            answers[qid] = defaultAnswer(q);
        }
        var section = document.querySelector('.question-section[data-question-id="' + qid + '"]');
        if (section) {
            section.querySelectorAll('button, input').forEach(function(el) { el.disabled = true; });
            var msg = section.querySelector('.timeout-msg');
            if (msg) {
                msg.textContent = answeredInTime ? 'Time\u2019s up! Your answer was recorded.'
                    : (q.timer.default ? 'Time\u2019s up! The answer "' + q.timer.default + '" was recorded.'
                                       : 'Time\u2019s up! No answer was recorded.');
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
        if (currentState !== 'answering') return;
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

    // Answer piping: replace {{Q1}}, {{Q2}}, etc. with answers from earlier questions
    function pipeAnswers(text) {
        return text.replace(/\{\{Q(\d+)\}\}/gi, function(match, num) {
            // {{Q1}} is Question 1 of the design, even if this arm skips some questions
            var qIndex = questionByIndex(parseInt(num) - 1);
            if (qIndex < 0) return match;
            var qid = questionsData[qIndex].question_id;
            var qtype = questionsData[qIndex].question_type;
            var ans = answers[qid];
            if (!ans) return match; // not answered yet, keep placeholder

            var answerText = ans.answer_text;
            var typed = otherChosen(qid) ? otherText(qid) : '';
            if (qtype === 'multiple_answer' && answerText) {
                try {
                    var arr = JSON.parse(answerText).map(function(a) { return (a === 'Other' && typed) ? typed : a; });
                    return arr.join(', ');
                } catch(e) {
                    return answerText;
                }
            }
            if (answerText === 'Other' && typed) return typed;
            return answerText || match;
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
        var index = currentQuestionIndex;
        var total = visibleCount();
        document.getElementById('q-current-num').textContent = visiblePosition(index);
        document.getElementById('q-total-num').textContent = total;
        document.getElementById('question-progress').style.display = total > 1 ? '' : 'none';

        var prevBtn = document.getElementById('prev-question');
        var nextBtn = document.getElementById('next-question');
        var submitBtn = document.getElementById('submit-all');
        var navDiv = document.getElementById('question-nav');
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

    function isCurrentQuestionAnswered() {
        var sections = document.querySelectorAll('.question-section');
        var section = sections[currentQuestionIndex];
        if (!section) return false;

        var qid = parseInt(section.dataset.questionId);
        var qtype = section.dataset.questionType;
        if (expired[qid]) return true;

        if (qtype === 'multiple_choice' || qtype === 'multiple_answer') {
            if (otherChosen(qid) && !otherText(qid)) return false;
            return !!answers[qid];
        } else if (qtype === 'short_answer') {
            var textInput = section.querySelector('.short-answer-input');
            return textInput && textInput.value.trim() !== '';
        } else if (qtype === 'slider') {
            return !!answers[qid];
        } else {
            // numeric
            var numInput = section.querySelector('.numeric-answer-input');
            return numInput && numInput.value !== '';
        }
    }

    // Capture short_answer and numeric values into the answers object (needed for piping)
    function captureCurrentAnswer() {
        var sections = document.querySelectorAll('.question-section');
        var section = sections[currentQuestionIndex];
        if (!section) return;

        var qid = parseInt(section.dataset.questionId);
        var qtype = section.dataset.questionType;
        if (timedOut[qid]) return;  // the recorded default stands

        if (qtype === 'short_answer') {
            var textInput = section.querySelector('.short-answer-input');
            if (textInput && textInput.value.trim() !== '') {
                answers[qid] = { answer_text: textInput.value.trim(), answer_index: null };
            }
        } else if (qtype === 'numeric') {
            var numInput = section.querySelector('.numeric-answer-input');
            if (numInput && numInput.value !== '') {
                answers[qid] = { answer_text: numInput.value, answer_index: null };
            }
        }
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
        answers = {};
        timeSpent = {};
        leftPage = {};
        deadlines = {};
        expired = {};
        timedOut = {};
        sliderMoved = {};
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

            var headerText = 'Question ' + (idx + 1);
            if (q.label) headerText += ': ' + q.label;

            var html = (q.timer ? timerHtml(q) : '') + '<h5 class="q-header">' + escapeHtml(headerText) + '</h5>';
            if (q.image_url) {
                html += '<img src="' + q.image_url + '" class="img-fluid mb-2 rounded" style="max-height:300px;" alt="Question image">';
            }
            html += '<p class="fs-5 mb-3 question-text-display">' + escapeHtml(q.question_text) + '</p>';

            if (q.question_type === 'multiple_choice') {
                html += '<div class="mc-buttons d-grid gap-2" data-qid="' + q.question_id + '">';
                q.options.forEach(function(opt, oidx) {
                    html += '<button type="button" class="btn btn-outline-primary btn-lg btn-mc-option" '
                          + 'data-qid="' + q.question_id + '" '
                          + 'data-answer="' + escapeHtml(opt) + '" '
                          + 'data-index="' + oidx + '">'
                          + escapeHtml(opt) + '</button>';
                });
                if (q.allow_other) {
                    html += '<button type="button" class="btn btn-outline-primary btn-lg btn-mc-option btn-other" '
                          + 'data-qid="' + q.question_id + '" data-answer="Other" data-index="' + q.options.length + '">Other</button>';
                }
                html += '</div>';
                if (q.allow_other) {
                    html += '<input type="text" class="form-control form-control-lg mt-2 other-input" style="display:none" '
                          + 'data-qid="' + q.question_id + '" maxlength="140" placeholder="Please specify...">';
                }
            } else if (q.question_type === 'multiple_answer') {
                html += '<p class="text-muted small mb-2">Select all that apply:</p>';
                html += '<div class="ma-buttons d-grid gap-2" data-qid="' + q.question_id + '">';
                q.options.forEach(function(opt, oidx) {
                    html += '<button type="button" class="btn btn-outline-primary btn-lg btn-ma-option" '
                          + 'data-qid="' + q.question_id + '" '
                          + 'data-answer="' + escapeHtml(opt) + '" '
                          + 'data-index="' + oidx + '">'
                          + escapeHtml(opt) + '</button>';
                });
                if (q.allow_other) {
                    html += '<button type="button" class="btn btn-outline-primary btn-lg btn-ma-option btn-other" '
                          + 'data-qid="' + q.question_id + '" data-answer="Other" data-index="' + q.options.length + '">Other</button>';
                }
                html += '</div>';
                if (q.allow_other) {
                    html += '<input type="text" class="form-control form-control-lg mt-2 other-input" style="display:none" '
                          + 'data-qid="' + q.question_id + '" maxlength="140" placeholder="Please specify...">';
                }
            } else if (q.question_type === 'short_answer') {
                html += '<div class="mb-1">'
                      + '<input type="text" class="form-control form-control-lg short-answer-input" '
                      + 'data-qid="' + q.question_id + '" placeholder="Type your answer..." maxlength="140">'
                      + '</div>'
                      + '<small class="text-muted"><span class="char-count" data-qid="' + q.question_id + '">0</span>/140</small>';
            } else if (q.question_type === 'slider') {
                var sMin = q.slider_min != null ? q.slider_min : 0;
                var sMax = q.slider_max != null ? q.slider_max : 100;
                var sStep = q.slider_step != null ? q.slider_step : 1;
                var sDefault = Math.round(((sMin + sMax) / 2) / sStep) * sStep;
                html += '<div class="slider-container mb-2">'
                      + '<input type="range" class="form-range slider-answer-input" '
                      + 'data-qid="' + q.question_id + '" '
                      + 'min="' + sMin + '" max="' + sMax + '" step="' + sStep + '" '
                      + 'value="' + sDefault + '">'
                      + '<div class="d-flex justify-content-between">'
                      + '<small class="text-muted">' + sMin + '</small>'
                      + '<strong class="slider-value-display" data-qid="' + q.question_id + '">' + sDefault + '</strong>'
                      + '<small class="text-muted">' + sMax + '</small>'
                      + '</div></div>';
                // Pre-populate answer with default value
                answers[q.question_id] = { answer_text: String(sDefault), answer_index: null };
            } else {
                // numeric
                html += '<div class="input-group input-group-lg">'
                      + '<input type="number" class="form-control numeric-answer-input" '
                      + 'data-qid="' + q.question_id + '" placeholder="Enter a number" step="any">'
                      + '</div>';
            }

            section.innerHTML = html;
            container.appendChild(section);
        });

        showState('answering');
        if (data.questions.some(function(q) { return q.timer; })) timerTick = setInterval(tickTimers, 200);
        showQuestion(Math.max(0, nextVisible(-1)));
    }

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

    // MC option selection (single select) via event delegation
    document.getElementById('questions-container').addEventListener('click', function(e) {
        var btn = e.target.closest('.btn-mc-option');
        if (!btn) return;

        var qid = parseInt(btn.dataset.qid);
        var answerText = btn.dataset.answer;
        var answerIndex = parseInt(btn.dataset.index);

        answers[qid] = { answer_text: answerText, answer_index: answerIndex };

        var group = btn.closest('.mc-buttons');
        group.querySelectorAll('.btn-mc-option').forEach(function(b) {
            b.classList.remove('btn-primary');
            b.classList.add('btn-outline-primary');
        });
        btn.classList.remove('btn-outline-primary');
        btn.classList.add('btn-primary');
        toggleOtherInput(qid);
        updateNav();
    });

    function toggleOtherInput(qid) {
        var input = document.querySelector('.other-input[data-qid="' + qid + '"]');
        if (!input) return;
        var show = otherChosen(qid);
        input.style.display = show ? '' : 'none';
        if (show) input.focus();
    }

    // Multiple answer option selection (toggle) via event delegation
    document.getElementById('questions-container').addEventListener('click', function(e) {
        var btn = e.target.closest('.btn-ma-option');
        if (!btn) return;

        var qid = parseInt(btn.dataset.qid);
        var answerText = btn.dataset.answer;

        // Toggle this button
        if (btn.classList.contains('btn-primary')) {
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-outline-primary');
        } else {
            btn.classList.remove('btn-outline-primary');
            btn.classList.add('btn-primary');
        }

        // Collect all selected options for this question
        var group = btn.closest('.ma-buttons');
        var selected = [];
        group.querySelectorAll('.btn-ma-option.btn-primary').forEach(function(b) {
            selected.push(b.dataset.answer);
        });

        if (selected.length > 0) {
            answers[qid] = { answer_text: JSON.stringify(selected), answer_index: null };
        } else {
            delete answers[qid];
        }
        toggleOtherInput(qid);
        updateNav();
    });

    // Short answer character counter + capture for piping
    document.getElementById('questions-container').addEventListener('input', function(e) {
        if (e.target.classList.contains('short-answer-input')) {
            var qid = e.target.dataset.qid;
            var counter = document.querySelector('.char-count[data-qid="' + qid + '"]');
            if (counter) counter.textContent = e.target.value.length;
        }
        // Slider value update
        if (e.target.classList.contains('slider-answer-input')) {
            var qid = parseInt(e.target.dataset.qid);
            var display = document.querySelector('.slider-value-display[data-qid="' + qid + '"]');
            if (display) display.textContent = e.target.value;
            answers[qid] = { answer_text: e.target.value, answer_index: null };
            sliderMoved[qid] = true;
        }
    });

    // Next question button
    document.getElementById('next-question').addEventListener('click', function() {
        if (!isCurrentQuestionAnswered()) {
            var cq = currentQid();
            alert(cq !== null && otherChosen(cq) && !otherText(cq)
                ? 'Please type your answer in the "Other" box, or pick another option.'
                : 'Please answer this question before continuing.');
            return;
        }
        captureCurrentAnswer();
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

        var sections = document.querySelectorAll('.question-section');
        var answersArray = [];
        var allAnswered = true;

        expireOverdue();
        sections.forEach(function(section, i) {
            var qid = parseInt(section.dataset.questionId);
            var qtype = section.dataset.questionType;
            if (!isVisible(i)) return;  // a display rule hid it: nothing to send

            if (timedOut[qid]) {
                answersArray.push({ question_id: qid, answer_text: answers[qid].answer_text,
                                    answer_index: answers[qid].answer_index, timed_out: true });
                return;
            }
            if (qtype === 'multiple_choice') {
                if (answers[qid]) {
                    answersArray.push({
                        question_id: qid,
                        answer_text: answers[qid].answer_text,
                        answer_index: answers[qid].answer_index,
                    });
                } else {
                    allAnswered = false;
                }
            } else if (qtype === 'multiple_answer') {
                if (answers[qid]) {
                    answersArray.push({
                        question_id: qid,
                        answer_text: answers[qid].answer_text,  // JSON array string
                        answer_index: null,
                    });
                } else {
                    allAnswered = false;
                }
            } else if (qtype === 'short_answer') {
                var textInput = section.querySelector('.short-answer-input');
                if (textInput && textInput.value.trim() !== '') {
                    answersArray.push({
                        question_id: qid,
                        answer_text: textInput.value.trim(),
                        answer_index: null,
                    });
                } else {
                    allAnswered = false;
                }
            } else if (qtype === 'slider') {
                var sliderInput = section.querySelector('.slider-answer-input');
                if (sliderInput) {
                    answersArray.push({
                        question_id: qid,
                        answer_text: sliderInput.value,
                        answer_index: null,
                    });
                } else {
                    allAnswered = false;
                }
            } else {
                // numeric
                var numInput = section.querySelector('.numeric-answer-input');
                if (numInput && numInput.value !== '') {
                    answersArray.push({
                        question_id: qid,
                        answer_text: numInput.value,
                        answer_index: null,
                    });
                } else {
                    allAnswered = false;
                }
            }
        });

        var missingOther = false;
        answersArray.forEach(function(a) {
            if (otherChosen(a.question_id) && !a.timed_out) {
                a.other_text = otherText(a.question_id);
                if (!a.other_text) missingOther = true;
            }
            a.seconds = timeSpent[a.question_id] != null ? Math.round(timeSpent[a.question_id] * 10) / 10 : null;
            a.left_page = !!leftPage[a.question_id];
        });

        if (!allAnswered || missingOther) {
            startClock();
            alert(missingOther ? 'Please type your answer in the "Other" box, or pick another option.'
                               : 'Please answer all questions before submitting.');
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
    document.getElementById('questions-container').addEventListener('keypress', function(e) {
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
