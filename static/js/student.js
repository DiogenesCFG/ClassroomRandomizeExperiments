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

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Answer piping: replace {{Q1}}, {{Q2}}, etc. with answers from earlier questions
    function pipeAnswers(text) {
        return text.replace(/\{\{Q(\d+)\}\}/gi, function(match, num) {
            var qIndex = parseInt(num) - 1; // Q1 -> index 0
            if (qIndex < 0 || qIndex >= questionsData.length) return match;
            var qid = questionsData[qIndex].question_id;
            var qtype = questionsData[qIndex].question_type;
            var ans = answers[qid];
            if (!ans) return match; // not answered yet, keep placeholder

            var answerText = ans.answer_text;
            if (qtype === 'multiple_answer' && answerText) {
                try {
                    var arr = JSON.parse(answerText);
                    return arr.join(', ');
                } catch(e) {
                    return answerText;
                }
            }
            return answerText || match;
        });
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

    // --- Sequential question navigation ---

    function showQuestion(index) {
        currentQuestionIndex = index;
        var sections = document.querySelectorAll('.question-section');
        sections.forEach(function(s, i) {
            s.style.display = (i === index) ? '' : 'none';
        });

        // Apply answer piping to the visible question's text
        if (questionsData[index]) {
            var section = sections[index];
            var pElem = section.querySelector('.question-text-display');
            if (pElem) {
                pElem.innerHTML = escapeHtml(pipeAnswers(questionsData[index].question_text));
            }
        }

        // Update progress indicator
        var totalQuestions = questionsData.length;
        document.getElementById('q-current-num').textContent = index + 1;
        document.getElementById('q-total-num').textContent = totalQuestions;
        document.getElementById('question-progress').style.display = '';

        // Update navigation buttons
        var prevBtn = document.getElementById('prev-question');
        var nextBtn = document.getElementById('next-question');
        var submitBtn = document.getElementById('submit-all');
        var navDiv = document.getElementById('question-nav');

        if (totalQuestions <= 1) {
            // Single question: no navigation, just submit
            navDiv.style.display = 'none';
            submitBtn.style.display = '';
        } else {
            navDiv.style.display = '';
            prevBtn.disabled = (index === 0);

            if (index === totalQuestions - 1) {
                // Last question: hide Next, show Submit
                nextBtn.style.display = 'none';
                submitBtn.style.display = '';
            } else {
                // Not last: show Next, hide Submit
                nextBtn.style.display = '';
                submitBtn.style.display = 'none';
            }
        }
    }

    function isCurrentQuestionAnswered() {
        var sections = document.querySelectorAll('.question-section');
        var section = sections[currentQuestionIndex];
        if (!section) return false;

        var qid = parseInt(section.dataset.questionId);
        var qtype = section.dataset.questionType;

        if (qtype === 'multiple_choice' || qtype === 'multiple_answer') {
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
        answers = {};
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

            var html = '<h5>' + escapeHtml(headerText) + '</h5>';
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
                html += '</div>';
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
                html += '</div>';
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
        showQuestion(0);
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
                } else if (data.state === 'blocked_designer') {
                    showState('blocked');
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
    });

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
        }
    });

    // Next question button
    document.getElementById('next-question').addEventListener('click', function() {
        if (!isCurrentQuestionAnswered()) {
            alert('Please answer this question before continuing.');
            return;
        }
        captureCurrentAnswer();
        if (currentQuestionIndex < questionsData.length - 1) {
            showQuestion(currentQuestionIndex + 1);
        }
    });

    // Previous question button
    document.getElementById('prev-question').addEventListener('click', function() {
        captureCurrentAnswer();
        if (currentQuestionIndex > 0) {
            showQuestion(currentQuestionIndex - 1);
        }
    });

    // Submit all answers
    document.getElementById('submit-all').addEventListener('click', function() {
        if (isSubmitting) return;

        // Capture current question's answer before validating
        captureCurrentAnswer();

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

    // Enter key: advance to next question, or submit on last question
    document.getElementById('questions-container').addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && (e.target.classList.contains('numeric-answer-input') || e.target.classList.contains('short-answer-input'))) {
            if (currentQuestionIndex < questionsData.length - 1) {
                document.getElementById('next-question').click();
            } else {
                document.getElementById('submit-all').click();
            }
        }
    });

    startStatePolling();
});
