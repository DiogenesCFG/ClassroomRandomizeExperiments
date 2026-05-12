document.addEventListener('DOMContentLoaded', function() {
    const socket = io();
    let currentSurveyId = null;
    let currentArmId = null;
    let selectedMCAnswer = null;
    let selectedMCIndex = null;

    // State management
    function showState(state) {
        document.querySelectorAll('.state-panel').forEach(p => p.classList.remove('active'));
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

    // Assignment received - show question
    socket.on('assignment', function(data) {
        currentSurveyId = data.survey_id;
        currentArmId = data.arm_id;
        selectedMCAnswer = null;
        selectedMCIndex = null;

        document.getElementById('q-group-number').textContent = data.group_number;
        document.getElementById('q-title').textContent = data.title;
        document.getElementById('q-text').textContent = data.question_text;

        if (data.question_type === 'multiple_choice') {
            document.getElementById('mc-options').style.display = '';
            document.getElementById('numeric-input').style.display = 'none';
            document.getElementById('submit-mc').style.display = 'none';

            const container = document.getElementById('mc-buttons');
            container.innerHTML = '';
            data.options.forEach(function(opt, idx) {
                const btn = document.createElement('button');
                btn.className = 'btn btn-outline-primary btn-lg btn-answer';
                btn.textContent = opt;
                btn.addEventListener('click', function() {
                    // Select this option (highlight it), don't submit yet
                    selectedMCAnswer = opt;
                    selectedMCIndex = idx;
                    container.querySelectorAll('.btn-answer').forEach(function(b) {
                        b.classList.remove('btn-primary');
                        b.classList.add('btn-outline-primary');
                    });
                    btn.classList.remove('btn-outline-primary');
                    btn.classList.add('btn-primary');
                    document.getElementById('submit-mc').style.display = '';
                });
                container.appendChild(btn);
            });
        } else {
            document.getElementById('mc-options').style.display = 'none';
            document.getElementById('numeric-input').style.display = '';
            document.getElementById('numeric-answer').value = '';
        }

        showState('answering');
    });

    // Submit MC answer via confirm button
    document.getElementById('submit-mc').addEventListener('click', function() {
        if (selectedMCAnswer === null) {
            alert('Please select an option first.');
            return;
        }
        submitAnswer(selectedMCAnswer, selectedMCIndex);
    });

    // Submit numeric answer
    document.getElementById('submit-numeric').addEventListener('click', function() {
        const val = document.getElementById('numeric-answer').value;
        if (val === '') {
            alert('Please enter a number.');
            return;
        }
        submitAnswer(val, null);
    });

    // Also submit on Enter key
    document.getElementById('numeric-answer').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            document.getElementById('submit-numeric').click();
        }
    });

    function submitAnswer(answerText, answerIndex) {
        socket.emit('submit_answer', {
            participant_id: PARTICIPANT_ID,
            survey_id: currentSurveyId,
            arm_id: currentArmId,
            answer_text: String(answerText),
            answer_index: answerIndex,
            classroom_id: CLASSROOM_ID
        });
        showState('submitted');
    }

    // Answer already submitted
    socket.on('already_answered', function(data) {
        showState('submitted');
    });

    // Answer saved confirmation
    socket.on('answer_saved', function(data) {
        showState('submitted');
    });

    // Survey deactivated - back to waiting
    socket.on('survey_deactivated', function() {
        currentSurveyId = null;
        currentArmId = null;
        selectedMCAnswer = null;
        selectedMCIndex = null;
        showState('waiting');
    });
});
