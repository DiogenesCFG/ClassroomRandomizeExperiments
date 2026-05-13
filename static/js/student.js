document.addEventListener('DOMContentLoaded', function() {
    var currentSurveyId = null;
    var currentArmId = null;
    var currentState = 'waiting';
    var answers = {}; // keyed by question_id: {answer_text, answer_index}
    var submittedSurveyIds = {}; // track surveys we've already submitted
    var isSubmitting = false;
    var statePollTimer = null;

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
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
    }

    function markSubmitFailed(message) {
        isSubmitting = false;
        setSubmitEnabled(true);
        showState('answering');
        alert(message || 'Your answer was not saved. Please try again.');
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
        answers = {};

        document.getElementById('q-group-number').textContent = data.group_number;
        document.getElementById('q-title').textContent = data.title;

        var container = document.getElementById('questions-container');
        container.innerHTML = '';

        data.questions.forEach(function(q, idx) {
            var section = document.createElement('div');
            section.className = 'question-section mb-4' + (idx > 0 ? ' border-top pt-3' : '');
            section.dataset.questionId = q.question_id;
            section.dataset.questionType = q.question_type;

            var headerText = 'Question ' + (idx + 1);
            if (q.label) headerText += ': ' + q.label;

            var html = '<h5>' + escapeHtml(headerText) + '</h5>';
            html += '<p class="fs-5 mb-3">' + escapeHtml(q.question_text) + '</p>';

            if (q.question_type === 'multiple_choice') {
                html += '<div class="mc-buttons d-grid gap-2" data-qid="' + q.question_id + '">';
                q.options.forEach(function(opt, oidx) {
                    html += '<button type="button" class="btn btn-outline-primary btn-lg btn-mc-option" '
                          + 'data-qid="' + q.question_id + '" '
                          + 'data-answer="' + escapeHtml(opt) + '" '
                          + 'data-index="' + oidx + '">'
                          + escapeHtml(opt) + '</button>';
                });
                html += '</div>';
            } else {
                html += '<div class="input-group input-group-lg">'
                      + '<input type="number" class="form-control numeric-answer-input" '
                      + 'data-qid="' + q.question_id + '" placeholder="Enter a number" step="any">'
                      + '</div>';
            }

            section.innerHTML = html;
            container.appendChild(section);
        });

        showState('answering');
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

    // MC option selection via event delegation
    document.getElementById('questions-container').addEventListener('click', function(e) {
        var btn = e.target.closest('.btn-mc-option');
        if (!btn) return;

        var qid = parseInt(btn.dataset.qid);
        var answerText = btn.dataset.answer;
        var answerIndex = parseInt(btn.dataset.index);

        // Record answer
        answers[qid] = { answer_text: answerText, answer_index: answerIndex };

        // Highlight: deselect siblings, select this one
        var group = btn.closest('.mc-buttons');
        group.querySelectorAll('.btn-mc-option').forEach(function(b) {
            b.classList.remove('btn-primary');
            b.classList.add('btn-outline-primary');
        });
        btn.classList.remove('btn-outline-primary');
        btn.classList.add('btn-primary');
    });

    // Submit all answers
    document.getElementById('submit-all').addEventListener('click', function() {
        if (isSubmitting) return;

        var sections = document.querySelectorAll('.question-section');
        var answersArray = [];
        var allAnswered = true;

        sections.forEach(function(section) {
            var qid = parseInt(section.dataset.questionId);
            var qtype = section.dataset.questionType;

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
            } else {
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

        if (!allAnswered) {
            alert('Please answer all questions before submitting.');
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
                    markSubmitted(currentSurveyId);
                } else {
                    markSubmitFailed();
                }
            })
            .catch(function() {
                markSubmitFailed('Your answer was not saved. Please try again.');
            });
    });

    // Also submit numeric on Enter key (only if single question)
    document.getElementById('questions-container').addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && e.target.classList.contains('numeric-answer-input')) {
            var sections = document.querySelectorAll('.question-section');
            if (sections.length === 1) {
                document.getElementById('submit-all').click();
            }
        }
    });

    startStatePolling();
});
