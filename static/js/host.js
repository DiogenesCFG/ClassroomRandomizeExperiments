document.addEventListener('DOMContentLoaded', function() {
    var socket = io({
        transports: ['websocket', 'polling'],
        upgrade: true,
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionAttempts: 10,
    });
    var charts = {};
    var activeSurveyId = null;

    var COLORS = [
        'rgba(54, 162, 235, 0.7)',
        'rgba(255, 99, 132, 0.7)',
        'rgba(75, 192, 192, 0.7)',
        'rgba(255, 159, 64, 0.7)',
    ];
    var BORDER_COLORS = [
        'rgba(54, 162, 235, 1)',
        'rgba(255, 99, 132, 1)',
        'rgba(75, 192, 192, 1)',
        'rgba(255, 159, 64, 1)',
    ];

    // Connect as host
    socket.on('connect', function() {
        console.log('[host] connected, transport:', socket.io.engine.transport.name);
        socket.emit('join_host', { classroom_id: CLASSROOM_ID });
    });

    socket.on('disconnect', function(reason) {
        console.log('[host] disconnected:', reason);
    });

    socket.on('connect_error', function(err) {
        console.error('[host] connect_error:', err.message);
    });

    // Participant count
    socket.on('participant_count', function(data) {
        console.log('[host] received: participant_count', data.count);
        document.getElementById('participant-badge').textContent = data.count + ' students';
    });

    // Activate survey by clicking
    document.querySelectorAll('.survey-list-item').forEach(function(item) {
        item.addEventListener('click', function() {
            var surveyId = parseInt(this.dataset.surveyId);
            console.log('[host] activating survey', surveyId);
            socket.emit('activate_survey', { survey_id: surveyId, classroom_id: CLASSROOM_ID });
            setActiveSurvey(surveyId);
        });
    });

    // Next survey button
    document.getElementById('btn-next').addEventListener('click', function() {
        console.log('[host] next_survey');
        socket.emit('next_survey', { classroom_id: CLASSROOM_ID });
    });

    // Reset button
    document.getElementById('btn-reset').addEventListener('click', function() {
        if (confirm('Reset the session? This will deactivate all surveys (data is preserved).')) {
            socket.emit('deactivate_all', { classroom_id: CLASSROOM_ID });
        }
    });

    function setActiveSurvey(surveyId) {
        activeSurveyId = surveyId;
        document.querySelectorAll('.survey-list-item').forEach(function(item) {
            item.classList.remove('active-survey');
            if (parseInt(item.dataset.surveyId) === surveyId) {
                item.classList.add('active-survey');
                item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        });
        document.getElementById('no-survey-msg').style.display = 'none';
        document.getElementById('all-done-msg').style.display = 'none';
        document.getElementById('results-panel').style.display = '';
    }

    // Results update (multi-question format)
    socket.on('results_update', function(data) {
        console.log('[host] received: results_update survey=' + data.survey_id +
                    ' questions=' + (data.questions ? data.questions.length : 0) +
                    ' participant_count=' + data.participant_count);
        if (data.questions) {
            data.questions.forEach(function(q) {
                console.log('[host]   question=' + q.question_id + ' type=' + q.question_type +
                            ' total_responses=' + q.total_responses);
            });
        }

        setActiveSurvey(data.survey_id);

        document.getElementById('result-title').textContent = data.title;
        document.getElementById('result-group').textContent = data.group_number;

        var tabsContainer = document.getElementById('question-tabs');
        var contentContainer = document.getElementById('question-tab-content');
        tabsContainer.innerHTML = '';
        contentContainer.innerHTML = '';

        // Destroy existing charts
        Object.keys(charts).forEach(function(key) {
            charts[key].destroy();
        });
        charts = {};

        var maxResponses = 0;
        var questions = data.questions || [];

        // If only one question, hide the tab bar
        var showTabs = questions.length > 1;
        tabsContainer.style.display = showTabs ? '' : 'none';

        questions.forEach(function(q, idx) {
            if (q.total_responses > maxResponses) maxResponses = q.total_responses;

            var tabId = 'q-tab-' + q.question_id;
            var paneId = 'q-pane-' + q.question_id;

            // Create tab
            if (showTabs) {
                var li = document.createElement('li');
                li.className = 'nav-item';
                var tabLabel = 'Q' + (idx + 1);
                if (q.label) tabLabel += ': ' + q.label;
                li.innerHTML = '<button class="nav-link' + (idx === 0 ? ' active' : '') + '" '
                    + 'id="' + tabId + '" data-bs-toggle="tab" data-bs-target="#' + paneId + '" '
                    + 'type="button" role="tab">' + tabLabel + '</button>';
                tabsContainer.appendChild(li);
            }

            // Create tab pane
            var pane = document.createElement('div');
            pane.className = 'tab-pane fade' + (idx === 0 ? ' show active' : '');
            pane.id = paneId;
            pane.setAttribute('role', 'tabpanel');

            var canvasId = 'chart-' + q.question_id;

            if (q.question_type === 'multiple_choice') {
                pane.innerHTML = '<div class="chart-container"><canvas id="' + canvasId + '"></canvas></div>';
            } else {
                pane.innerHTML = '<div class="chart-container mb-4"><canvas id="' + canvasId + '"></canvas></div>'
                    + '<div class="table-responsive"><table class="table table-bordered">'
                    + '<thead><tr><th>Arm</th><th>N</th><th>Mean</th><th>Median</th><th>Std Dev</th><th>Min</th><th>Max</th></tr></thead>'
                    + '<tbody class="stats-tbody"></tbody></table></div>';
            }
            contentContainer.appendChild(pane);

            // Render chart
            if (q.question_type === 'multiple_choice') {
                renderMCChart(q, canvasId);
            } else {
                var tbody = pane.querySelector('.stats-tbody');
                renderNumericChart(q, canvasId, tbody);
            }
        });

        document.getElementById('response-count').textContent =
            maxResponses + ' responses' +
            (data.participant_count ? ' / ' + data.participant_count + ' students' : '');

        renderArmsDetail(data);
    });

    function renderMCChart(q, canvasId) {
        var allOptions = [];
        q.arms.forEach(function(arm) {
            if (arm.options) {
                arm.options.forEach(function(opt) {
                    if (allOptions.indexOf(opt) === -1) allOptions.push(opt);
                });
            }
        });

        var datasets = q.arms.map(function(arm, i) {
            return {
                label: arm.label + ' (n=' + arm.n + ')',
                data: allOptions.map(function(opt) { return (arm.counts && arm.counts[opt]) || 0; }),
                backgroundColor: COLORS[i % COLORS.length],
                borderColor: BORDER_COLORS[i % BORDER_COLORS.length],
                borderWidth: 1
            };
        });

        var ctx = document.getElementById(canvasId);
        charts[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: { labels: allOptions, datasets: datasets },
            options: {
                responsive: true,
                plugins: {
                    title: { display: true, text: 'Responses by Arm', font: { size: 16 } },
                    legend: { position: 'top' }
                },
                scales: {
                    x: { title: { display: true, text: 'Answer' } },
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Count' },
                        ticks: { stepSize: 1 }
                    }
                }
            }
        });
    }

    function renderNumericChart(q, canvasId, tbody) {
        var labels = q.arms.map(function(a) { return a.label; });
        var means = q.arms.map(function(a) { return a.stats ? a.stats.mean : 0; });

        var datasets = [{
            label: 'Mean',
            data: means,
            backgroundColor: q.arms.map(function(_, i) { return COLORS[i % COLORS.length]; }),
            borderColor: q.arms.map(function(_, i) { return BORDER_COLORS[i % BORDER_COLORS.length]; }),
            borderWidth: 1
        }];

        var ctx = document.getElementById(canvasId);
        charts[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                plugins: {
                    title: { display: true, text: 'Mean Response by Arm', font: { size: 16 } },
                    legend: { display: false }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Value' }
                    }
                }
            }
        });

        // Stats table
        tbody.innerHTML = '';
        q.arms.forEach(function(arm) {
            var row = document.createElement('tr');
            if (arm.stats) {
                row.innerHTML = '<td><strong>' + arm.label + '</strong></td>'
                    + '<td>' + arm.n + '</td>'
                    + '<td>' + arm.stats.mean + '</td>'
                    + '<td>' + arm.stats.median + '</td>'
                    + '<td>' + arm.stats.std + '</td>'
                    + '<td>' + arm.stats.min + '</td>'
                    + '<td>' + arm.stats.max + '</td>';
            } else {
                row.innerHTML = '<td><strong>' + arm.label + '</strong></td>'
                    + '<td>0</td>'
                    + '<td colspan="5" class="text-muted">No responses yet</td>';
            }
            tbody.appendChild(row);
        });
    }

    function renderArmsDetail(data) {
        var container = document.getElementById('arms-detail');
        container.innerHTML = '';
        var questions = data.questions || [];
        if (questions.length === 0) return;

        var armList = questions[0].arms;
        armList.forEach(function(arm, i) {
            var col = document.createElement('div');
            col.className = 'col-md-6 mb-2';
            var questionsHtml = '';
            questions.forEach(function(q, qi) {
                var armData = null;
                q.arms.forEach(function(a) {
                    if (a.arm_id === arm.arm_id) armData = a;
                });
                var qText = armData ? armData.question_text : '(N/A)';
                var qLabel = 'Q' + (qi + 1);
                if (q.label) qLabel += ' (' + q.label + ')';
                questionsHtml += '<p class="mb-1 small"><strong>' + qLabel + ':</strong> ' + qText + '</p>';
            });
            col.innerHTML = '<div class="card"><div class="card-body p-2">'
                + '<h6 style="color: ' + BORDER_COLORS[i % BORDER_COLORS.length] + '">' + arm.label + '</h6>'
                + questionsHtml
                + '</div></div>';
            container.appendChild(col);
        });
    }

    // Survey changed (from next_survey)
    socket.on('survey_changed', function(data) {
        console.log('[host] received: survey_changed', data.survey_id);
        setActiveSurvey(data.survey_id);
    });

    // All done
    socket.on('all_done', function() {
        console.log('[host] received: all_done');
        document.getElementById('results-panel').style.display = 'none';
        document.getElementById('no-survey-msg').style.display = 'none';
        document.getElementById('all-done-msg').style.display = '';
        document.querySelectorAll('.survey-list-item').forEach(function(item) {
            item.classList.remove('active-survey');
        });
    });

    // Session reset
    socket.on('session_reset', function() {
        console.log('[host] received: session_reset');
        document.getElementById('results-panel').style.display = 'none';
        document.getElementById('all-done-msg').style.display = 'none';
        document.getElementById('no-survey-msg').style.display = '';
        document.querySelectorAll('.survey-list-item').forEach(function(item) {
            item.classList.remove('active-survey');
        });
        activeSurveyId = null;
    });
});
