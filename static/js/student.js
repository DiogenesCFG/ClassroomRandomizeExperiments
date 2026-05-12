document.addEventListener('DOMContentLoaded', function() {
    var socket = io({
        transports: ['websocket', 'polling'],
        upgrade: true,
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionAttempts: 10,
    });
    var currentSurveyId = null;
    var currentArmId = null;
    var answers = {}; // keyed by question_id: {answer_text, answer_index}

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // State management
    function showState(state) {
        document.querySelectorAll('.state-panel').forEach(function(p) { p.classList.remove('active'); });
        document.getElementById('state-' + state).classList.add('active');
    }

    // Connect and join
    socket.on('connect', function() {
        socket.emit('join_student', {
            participant_id: PARTICIPANT_ID,
            student_id: STUDENT_ID,
            classroom_id: CLASSROOM_ID
        });
    });

    // Waiting state
    socket.on('waiting', function() {
        showState('waiting');
    });

    // Survey activated - request assignment
    socket.on('survey_activated', function(data) {
        currentSurveyId = data.survey_id;
        socket.emit('request_assignment', {
            participant_id: PARTICIPANT_ID,
            student_id: STUDENT_ID,
            survey_id: data.survey_id,
            classroom_id: CLASSROOM_ID
        });
    });

    // Assignment received - show all questions
    socket.on('assignment', function(data) {
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
    });

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

        socket.emit('submit_answer', {
            participant_id: PARTICIPANT_ID,
            survey_id: currentSurveyId,
            arm_id: currentArmId,
            classroom_id: CLASSROOM_ID,
            answers: answersArray,
        });
        showState('submitted');
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

    // Answer already submitted
    socket.on('already_answered', function() {
        showState('submitted');
    });

    // Answer saved confirmation
    socket.on('answer_saved', function() {
        showState('submitted');
    });

    // Survey deactivated - back to waiting
    socket.on('survey_deactivated', function() {
        currentSurveyId = null;
        currentArmId = null;
        answers = {};
        showState('waiting');
    });
});
