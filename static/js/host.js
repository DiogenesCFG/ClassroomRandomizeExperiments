document.addEventListener('DOMContentLoaded', function() {
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

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function isChartType(qtype) {
        return qtype === 'multiple_choice' || qtype === 'multiple_answer' || qtype === 'numeric' || qtype === 'slider';
    }

    function computeHistogramBins(q) {
        var sMin = q.slider_min != null ? q.slider_min : 0;
        var sMax = q.slider_max != null ? q.slider_max : 100;
        var sStep = q.slider_step != null ? q.slider_step : 1;
        var range = sMax - sMin;
        var numPossible = Math.round(range / sStep) + 1;

        var binLabels, binEdges;
        if (numPossible <= 20) {
            // Each possible value is its own bin
            binLabels = [];
            binEdges = [];
            for (var v = sMin; v <= sMax + sStep * 0.001; v += sStep) {
                var rounded = Math.round(v * 1000) / 1000;
                binLabels.push(String(rounded));
                binEdges.push(rounded);
            }
        } else {
            // Group into ~10 bins
            var numBins = 10;
            var binWidth = range / numBins;
            binLabels = [];
            binEdges = [];
            for (var i = 0; i < numBins; i++) {
                var lo = Math.round((sMin + i * binWidth) * 100) / 100;
                var hi = Math.round((sMin + (i + 1) * binWidth) * 100) / 100;
                binLabels.push(lo + '-' + hi);
                binEdges.push(lo);
            }
            binEdges.push(sMax); // upper bound of last bin
        }
        return { binLabels: binLabels, binEdges: binEdges, exactBins: numPossible <= 20 };
    }

    function binValues(values, binInfo) {
        var counts = new Array(binInfo.binLabels.length).fill(0);
        if (binInfo.exactBins) {
            values.forEach(function(v) {
                for (var i = 0; i < binInfo.binEdges.length; i++) {
                    if (Math.abs(v - binInfo.binEdges[i]) < 0.0001) {
                        counts[i]++;
                        break;
                    }
                }
            });
        } else {
            var numBins = binInfo.binLabels.length;
            var lo = binInfo.binEdges[0];
            var hi = binInfo.binEdges[binInfo.binEdges.length - 1];
            var binWidth = (hi - lo) / numBins;
            values.forEach(function(v) {
                var idx = Math.floor((v - lo) / binWidth);
                if (idx >= numBins) idx = numBins - 1;
                if (idx < 0) idx = 0;
                counts[idx]++;
            });
        }
        return counts;
    }

    function computeNumericBins(q) {
        var allValues = [];
        q.arms.forEach(function(arm) {
            if (arm.values) {
                arm.values.forEach(function(v) { allValues.push(v); });
            }
        });

        if (allValues.length === 0) {
            return { binLabels: ['0'], binEdges: [0], exactBins: true };
        }

        var dMin = Math.min.apply(null, allValues);
        var dMax = Math.max.apply(null, allValues);

        if (dMin === dMax) {
            return { binLabels: [String(dMin)], binEdges: [dMin], exactBins: true };
        }

        var allIntegers = allValues.every(function(v) { return v === Math.floor(v); });
        var range = dMax - dMin;

        if (allIntegers && range <= 19) {
            var binLabels = [];
            var binEdges = [];
            for (var v = dMin; v <= dMax; v++) {
                binLabels.push(String(v));
                binEdges.push(v);
            }
            return { binLabels: binLabels, binEdges: binEdges, exactBins: true };
        }

        var numBins = Math.min(10, allValues.length);
        if (numBins < 2) numBins = 2;
        var binWidth = range / numBins;
        var binLabels = [];
        var binEdges = [];
        for (var i = 0; i < numBins; i++) {
            var lo = Math.round((dMin + i * binWidth) * 100) / 100;
            var hi = Math.round((dMin + (i + 1) * binWidth) * 100) / 100;
            binLabels.push(lo + '-' + hi);
            binEdges.push(lo);
        }
        binEdges.push(dMax);
        return { binLabels: binLabels, binEdges: binEdges, exactBins: false };
    }

    function updateParticipantBadge(count) {
        if (typeof count === 'number') {
            document.getElementById('participant-badge').textContent = count + ' students';
        }
    }

    function fetchState() {
        var btn = document.getElementById('btn-refresh');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Refreshing...';
        }
        fetch(HOST_STATE_URL, { credentials: 'same-origin' })
            .then(function(resp) {
                if (!resp.ok) throw new Error('state request failed');
                return resp.json();
            })
            .then(function(data) {
                if (!data.ok) return;
                updateParticipantBadge(data.participant_count);
                if (data.results) {
                    handleResultsUpdate(data.results);
                } else if (!data.active_survey_id) {
                    showNoActiveSurvey();
                }
            })
            .catch(function(err) {
                console.warn('[host] state fetch failed:', err.message);
            })
            .finally(function() {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = 'Refresh Results';
                }
            });
    }

    function showNoActiveSurvey() {
        document.getElementById('results-panel').style.display = 'none';
        document.getElementById('all-done-msg').style.display = 'none';
        document.getElementById('no-survey-msg').style.display = '';
        document.querySelectorAll('.survey-list-item').forEach(function(item) {
            item.classList.remove('active-survey');
        });
        activeSurveyId = null;
    }

    function showAllDone() {
        document.getElementById('results-panel').style.display = 'none';
        document.getElementById('no-survey-msg').style.display = 'none';
        document.getElementById('all-done-msg').style.display = '';
        document.querySelectorAll('.survey-list-item').forEach(function(item) {
            item.classList.remove('active-survey');
        });
        activeSurveyId = null;
    }

    function postJson(url, payload) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        }).then(function(resp) {
            if (!resp.ok) throw new Error('request failed');
            return resp.json();
        });
    }

    // Activate survey by clicking
    document.querySelectorAll('.survey-list-item').forEach(function(item) {
        item.addEventListener('click', function() {
            var surveyId = parseInt(this.dataset.surveyId);
            console.log('[host] activating survey', surveyId);
            postJson(HOST_ACTIVATE_URL, { survey_id: surveyId })
                .then(function(data) {
                    if (data && data.results) handleResultsUpdate(data.results);
                })
                .catch(function(err) {
                    console.warn('[host] activate request failed:', err.message);
                });
        });
    });

    // Next survey button
    document.getElementById('btn-next').addEventListener('click', function() {
        console.log('[host] next_survey');
        postJson(HOST_NEXT_URL)
            .then(function(data) {
                if (data && data.results) handleResultsUpdate(data.results);
                if (data && data.done) showAllDone();
            })
            .catch(function(err) {
                console.warn('[host] next request failed:', err.message);
            });
    });

    // Reset button
    document.getElementById('btn-reset').addEventListener('click', function() {
        if (confirm('Reset the session? This will deactivate all surveys (data is preserved).')) {
            postJson(HOST_RESET_URL)
                .then(showNoActiveSurvey)
                .catch(function(err) {
                    console.warn('[host] reset request failed:', err.message);
                });
        }
    });

    // Refresh button
    document.getElementById('btn-refresh').addEventListener('click', function() {
        fetchState();
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
    function handleResultsUpdate(data) {
        console.log('[host] results_update survey=' + data.survey_id +
                    ' questions=' + (data.questions ? data.questions.length : 0) +
                    ' participant_count=' + data.participant_count);

        var questions = data.questions || [];

        // If same survey, fast-path: update data in place
        if (data.survey_id === activeSurveyId && Object.keys(charts).length > 0) {
            var maxResponses = 0;
            questions.forEach(function(q) {
                if (q.total_responses > maxResponses) maxResponses = q.total_responses;
                var canvasId = 'chart-' + q.question_id;
                var chart = charts[canvasId];
                var pane = document.getElementById('q-pane-' + q.question_id);

                if (q.question_type === 'multiple_choice' || q.question_type === 'multiple_answer') {
                    if (chart) updateMCChart(q, chart);
                } else if (q.question_type === 'short_answer') {
                    if (pane) updateShortAnswerPane(q, pane);
                } else if (q.question_type === 'slider') {
                    if (chart) {
                        var tbody = pane ? pane.querySelector('.stats-tbody') : null;
                        updateSliderChart(q, chart, tbody);
                    }
                } else {
                    if (chart) {
                        var tbody = pane ? pane.querySelector('.stats-tbody') : null;
                        updateNumericChart(q, chart, tbody);
                    }
                }
            });
            document.getElementById('response-count').textContent =
                maxResponses + ' responses' +
                (data.participant_count ? ' / ' + data.participant_count + ' students' : '');
            renderArmsDetail(data);
            return;
        }

        // Different survey or first load: full rebuild
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

            if (q.question_type === 'multiple_choice' || q.question_type === 'multiple_answer') {
                var chartTitle = q.question_type === 'multiple_answer' ? 'Selections by Arm' : 'Responses by Arm';
                pane.innerHTML = '<div class="chart-container"><canvas id="' + canvasId + '"></canvas></div>';
                contentContainer.appendChild(pane);
                renderMCChart(q, canvasId, chartTitle);
            } else if (q.question_type === 'short_answer') {
                pane.innerHTML = '<div class="short-answer-results"></div>';
                contentContainer.appendChild(pane);
                renderShortAnswerPane(q, pane);
                // Use a placeholder in charts so fast-path knows this question exists
                charts['chart-' + q.question_id] = { _shortAnswer: true, destroy: function() {} };
            } else if (q.question_type === 'slider') {
                pane.innerHTML = '<div class="chart-container mb-4"><canvas id="' + canvasId + '"></canvas></div>'
                    + '<div class="table-responsive"><table class="table table-bordered">'
                    + '<thead><tr><th>Arm</th><th>N</th><th>Mean</th><th>Median</th><th>Std Dev</th><th>Min</th><th>Max</th></tr></thead>'
                    + '<tbody class="stats-tbody"></tbody></table></div>';
                contentContainer.appendChild(pane);
                var tbody = pane.querySelector('.stats-tbody');
                renderSliderChart(q, canvasId, tbody);
            } else {
                // numeric
                pane.innerHTML = '<div class="chart-container mb-4"><canvas id="' + canvasId + '"></canvas></div>'
                    + '<div class="table-responsive"><table class="table table-bordered">'
                    + '<thead><tr><th>Arm</th><th>N</th><th>Mean</th><th>Median</th><th>Std Dev</th><th>Min</th><th>Max</th></tr></thead>'
                    + '<tbody class="stats-tbody"></tbody></table></div>';
                contentContainer.appendChild(pane);
                var tbody = pane.querySelector('.stats-tbody');
                renderNumericChart(q, canvasId, tbody);
            }
        });

        document.getElementById('response-count').textContent =
            maxResponses + ' responses' +
            (data.participant_count ? ' / ' + data.participant_count + ' students' : '');

        renderArmsDetail(data);
    }

    function updateMCChart(q, chart) {
        var allOptions = [];
        q.arms.forEach(function(arm) {
            if (arm.options) {
                arm.options.forEach(function(opt) {
                    if (allOptions.indexOf(opt) === -1) allOptions.push(opt);
                });
            }
        });
        chart.data.labels = allOptions;
        q.arms.forEach(function(arm, i) {
            if (chart.data.datasets[i]) {
                chart.data.datasets[i].label = arm.label + ' (n=' + arm.n + ')';
                chart.data.datasets[i].data = allOptions.map(function(opt) {
                    return (arm.counts && arm.counts[opt]) || 0;
                });
            }
        });
        chart.update();
    }

    function updateNumericChart(q, chart, tbody) {
        // Recompute bins since the data range may have changed
        var binInfo = computeNumericBins(q);
        chart.data.labels = binInfo.binLabels;
        chart._binInfo = binInfo;
        q.arms.forEach(function(arm, i) {
            if (chart.data.datasets[i]) {
                chart.data.datasets[i].label = arm.label + ' (n=' + arm.n + ')';
                chart.data.datasets[i].data = binValues(arm.values || [], binInfo);
            }
        });
        chart.update();

        if (tbody) {
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
    }

    function renderShortAnswerPane(q, pane) {
        var container = pane.querySelector('.short-answer-results');
        var html = '<div class="table-responsive"><table class="table table-bordered">'
            + '<thead><tr><th>Arm</th><th>N</th><th>Responses</th></tr></thead><tbody>';
        q.arms.forEach(function(arm, i) {
            var texts = arm.responses || [];
            var cellHtml = '';
            if (texts.length > 0) {
                cellHtml = '<ul class="mb-0 ps-3">';
                texts.forEach(function(t) {
                    cellHtml += '<li>' + escapeHtml(t) + '</li>';
                });
                cellHtml += '</ul>';
            } else {
                cellHtml = '<span class="text-muted">No responses yet</span>';
            }
            html += '<tr><td><strong style="color: ' + BORDER_COLORS[i % BORDER_COLORS.length] + '">'
                + escapeHtml(arm.label) + '</strong></td>'
                + '<td>' + arm.n + '</td>'
                + '<td>' + cellHtml + '</td></tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    }

    function updateShortAnswerPane(q, pane) {
        renderShortAnswerPane(q, pane);
    }

    function renderMCChart(q, canvasId, title) {
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
                    title: { display: true, text: title || 'Responses by Arm', font: { size: 16 } },
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
        var binInfo = computeNumericBins(q);

        var datasets = q.arms.map(function(arm, i) {
            var counts = binValues(arm.values || [], binInfo);
            return {
                label: arm.label + ' (n=' + arm.n + ')',
                data: counts,
                backgroundColor: COLORS[i % COLORS.length],
                borderColor: BORDER_COLORS[i % BORDER_COLORS.length],
                borderWidth: 1
            };
        });

        var ctx = document.getElementById(canvasId);
        charts[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: { labels: binInfo.binLabels, datasets: datasets },
            options: {
                responsive: true,
                plugins: {
                    title: { display: true, text: 'Response Distribution by Arm', font: { size: 16 } },
                    legend: { position: 'top' }
                },
                scales: {
                    x: { title: { display: true, text: 'Value' } },
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Count' },
                        ticks: { stepSize: 1 }
                    }
                }
            }
        });
        charts[canvasId]._binInfo = binInfo;

        // Stats table
        if (tbody) {
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
    }

    function renderSliderChart(q, canvasId, tbody) {
        var binInfo = computeHistogramBins(q);

        var datasets = q.arms.map(function(arm, i) {
            var counts = binValues(arm.values || [], binInfo);
            return {
                label: arm.label + ' (n=' + arm.n + ')',
                data: counts,
                backgroundColor: COLORS[i % COLORS.length],
                borderColor: BORDER_COLORS[i % BORDER_COLORS.length],
                borderWidth: 1
            };
        });

        var ctx = document.getElementById(canvasId);
        charts[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: { labels: binInfo.binLabels, datasets: datasets },
            options: {
                responsive: true,
                plugins: {
                    title: { display: true, text: 'Response Distribution by Arm', font: { size: 16 } },
                    legend: { position: 'top' }
                },
                scales: {
                    x: { title: { display: true, text: 'Value' } },
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Count' },
                        ticks: { stepSize: 1 }
                    }
                }
            }
        });
        // Store binInfo on chart for fast-path updates
        charts[canvasId]._binInfo = binInfo;

        // Stats table
        if (tbody) {
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
    }

    function updateSliderChart(q, chart, tbody) {
        var binInfo = chart._binInfo || computeHistogramBins(q);
        q.arms.forEach(function(arm, i) {
            if (chart.data.datasets[i]) {
                chart.data.datasets[i].label = arm.label + ' (n=' + arm.n + ')';
                chart.data.datasets[i].data = binValues(arm.values || [], binInfo);
            }
        });
        chart.update();

        if (tbody) {
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
                questionsHtml += '<p class="mb-1 small"><strong>' + qLabel + ':</strong> ' + escapeHtml(qText) + '</p>';
                if (armData && armData.image_url) {
                    if (armData.image_url.toLowerCase().endsWith('.pdf')) {
                        questionsHtml += '<p class="mb-1"><a href="' + armData.image_url + '" target="_blank" class="btn btn-sm btn-outline-secondary py-0">View PDF</a></p>';
                    } else {
                        questionsHtml += '<img src="' + armData.image_url + '" class="img-fluid mb-1 rounded" style="max-height:120px;" alt="Question image">';
                    }
                }
            });
            col.innerHTML = '<div class="card"><div class="card-body p-2">'
                + '<h6 style="color: ' + BORDER_COLORS[i % BORDER_COLORS.length] + '">' + arm.label + '</h6>'
                + questionsHtml
                + '</div></div>';
            container.appendChild(col);
        });
    }

    // Load initial state on page load
    fetchState();
});
