document.addEventListener('DOMContentLoaded', function() {
    const socket = io();
    let mcChart = null;
    let numericChart = null;
    let activeSurveyId = null;

    const COLORS = [
        'rgba(54, 162, 235, 0.7)',   // blue
        'rgba(255, 99, 132, 0.7)',   // red
        'rgba(75, 192, 192, 0.7)',   // teal
        'rgba(255, 159, 64, 0.7)',   // orange
    ];
    const BORDER_COLORS = [
        'rgba(54, 162, 235, 1)',
        'rgba(255, 99, 132, 1)',
        'rgba(75, 192, 192, 1)',
        'rgba(255, 159, 64, 1)',
    ];

    // Connect as host
    socket.on('connect', function() {
        socket.emit('join_host', { token: HOST_TOKEN });
    });

    // Participant count
    socket.on('participant_count', function(data) {
        document.getElementById('participant-badge').textContent = data.count + ' students';
    });

    // Activate survey by clicking
    document.querySelectorAll('.survey-list-item').forEach(function(item) {
        item.addEventListener('click', function() {
            const surveyId = parseInt(this.dataset.surveyId);
            socket.emit('activate_survey', { survey_id: surveyId });
            setActiveSurvey(surveyId);
        });
    });

    // Next survey button
    document.getElementById('btn-next').addEventListener('click', function() {
        socket.emit('next_survey', {});
    });

    // Reset button
    document.getElementById('btn-reset').addEventListener('click', function() {
        if (confirm('Reset the session? This will deactivate all surveys (data is preserved).')) {
            socket.emit('deactivate_all', {});
        }
    });

    function setActiveSurvey(surveyId) {
        activeSurveyId = surveyId;
        // Highlight in sidebar
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

    // Results update
    socket.on('results_update', function(data) {
        setActiveSurvey(data.survey_id);

        document.getElementById('result-title').textContent = data.title;
        document.getElementById('result-group').textContent = data.group_number;
        document.getElementById('response-count').textContent =
            data.total_responses + ' responses' +
            (data.participant_count ? ' / ' + data.participant_count + ' students' : '');

        if (data.question_type === 'multiple_choice') {
            renderMCChart(data);
        } else {
            renderNumericResults(data);
        }

        renderArmsDetail(data);
    });

    // Survey changed (from next_survey)
    socket.on('survey_changed', function(data) {
        setActiveSurvey(data.survey_id);
    });

    // All done
    socket.on('all_done', function() {
        document.getElementById('results-panel').style.display = 'none';
        document.getElementById('no-survey-msg').style.display = 'none';
        document.getElementById('all-done-msg').style.display = '';
        document.querySelectorAll('.survey-list-item').forEach(item => {
            item.classList.remove('active-survey');
        });
    });

    // Session reset
    socket.on('session_reset', function() {
        document.getElementById('results-panel').style.display = 'none';
        document.getElementById('all-done-msg').style.display = 'none';
        document.getElementById('no-survey-msg').style.display = '';
        document.querySelectorAll('.survey-list-item').forEach(item => {
            item.classList.remove('active-survey');
        });
        activeSurveyId = null;
    });

    function renderMCChart(data) {
        document.getElementById('mc-chart-container').style.display = '';
        document.getElementById('numeric-results-container').style.display = 'none';

        // Collect all unique options across arms
        const allOptions = [];
        data.arms.forEach(arm => {
            if (arm.options) {
                arm.options.forEach(opt => {
                    if (!allOptions.includes(opt)) allOptions.push(opt);
                });
            }
        });

        const datasets = data.arms.map((arm, i) => ({
            label: arm.label + ' (n=' + arm.n + ')',
            data: allOptions.map(opt => (arm.counts && arm.counts[opt]) || 0),
            backgroundColor: COLORS[i % COLORS.length],
            borderColor: BORDER_COLORS[i % BORDER_COLORS.length],
            borderWidth: 1
        }));

        if (mcChart) mcChart.destroy();

        mcChart = new Chart(document.getElementById('mc-chart'), {
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

    function renderNumericResults(data) {
        document.getElementById('mc-chart-container').style.display = 'none';
        document.getElementById('numeric-results-container').style.display = '';

        // Bar chart of means
        const labels = data.arms.map(a => a.label);
        const means = data.arms.map(a => a.stats ? a.stats.mean : 0);

        const datasets = [{
            label: 'Mean',
            data: means,
            backgroundColor: data.arms.map((_, i) => COLORS[i % COLORS.length]),
            borderColor: data.arms.map((_, i) => BORDER_COLORS[i % BORDER_COLORS.length]),
            borderWidth: 1
        }];

        if (numericChart) numericChart.destroy();

        numericChart = new Chart(document.getElementById('numeric-chart'), {
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
        const tbody = document.querySelector('#stats-table tbody');
        tbody.innerHTML = '';
        data.arms.forEach(function(arm) {
            const row = document.createElement('tr');
            if (arm.stats) {
                row.innerHTML = `
                    <td><strong>${arm.label}</strong></td>
                    <td>${arm.n}</td>
                    <td>${arm.stats.mean}</td>
                    <td>${arm.stats.median}</td>
                    <td>${arm.stats.std}</td>
                    <td>${arm.stats.min}</td>
                    <td>${arm.stats.max}</td>
                `;
            } else {
                row.innerHTML = `
                    <td><strong>${arm.label}</strong></td>
                    <td>0</td>
                    <td colspan="5" class="text-muted">No responses yet</td>
                `;
            }
            tbody.appendChild(row);
        });
    }

    function renderArmsDetail(data) {
        const container = document.getElementById('arms-detail');
        container.innerHTML = '';
        data.arms.forEach(function(arm, i) {
            const col = document.createElement('div');
            col.className = 'col-md-6 mb-2';
            col.innerHTML = `
                <div class="card">
                    <div class="card-body p-2">
                        <h6 style="color: ${BORDER_COLORS[i % BORDER_COLORS.length]}">${arm.label}</h6>
                        <p class="mb-0 small">${arm.question_text || '(Question text not available)'}</p>
                    </div>
                </div>
            `;
            container.appendChild(col);
        });
    }
});
