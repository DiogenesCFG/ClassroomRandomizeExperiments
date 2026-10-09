document.addEventListener('DOMContentLoaded', function() {
    var armsContainer = document.getElementById('arms-container');
    var questionsContainer = document.getElementById('questions-container');

    // --- Helper: get current arm labels ---
    function getArmLabels() {
        var labels = [];
        armsContainer.querySelectorAll('.arm-label-block').forEach(function(block) {
            var input = block.querySelector('input');
            labels.push(input.value || 'Arm ' + (labels.length + 1));
        });
        return labels;
    }

    // --- Reindex everything ---
    function reindexAll() {
        var armLabels = getArmLabels();

        // Reindex arm blocks
        var armBlocks = armsContainer.querySelectorAll('.arm-label-block');
        armBlocks.forEach(function(block, i) {
            block.dataset.armIndex = i;
            block.querySelector('.arm-number-label').textContent = 'Arm ' + (i + 1) + ':';
            block.querySelector('input').name = 'arms[' + i + '][label]';
            var removeBtn = block.querySelector('.remove-arm-btn');
            if (removeBtn) removeBtn.style.display = armBlocks.length > 1 ? '' : 'none';
        });

        // Reindex question blocks
        var questionBlocks = questionsContainer.querySelectorAll('.question-block');
        questionBlocks.forEach(function(qBlock, qi) {
            qBlock.dataset.questionIndex = qi;
            qBlock.querySelector('.question-header').textContent = 'Question ' + (qi + 1);

            // Update question field names
            var typeSelect = qBlock.querySelector('.question-type-select');
            typeSelect.name = 'questions[' + qi + '][question_type]';
            var labelInput = qBlock.querySelector('input[name*="[label]"]');
            if (labelInput) labelInput.name = 'questions[' + qi + '][label]';

            // Update slider config field names
            var sliderMin = qBlock.querySelector('.slider-min-input');
            var sliderMax = qBlock.querySelector('.slider-max-input');
            var sliderStep = qBlock.querySelector('.slider-step-input');
            if (sliderMin) sliderMin.name = 'questions[' + qi + '][slider_min]';
            if (sliderMax) sliderMax.name = 'questions[' + qi + '][slider_max]';
            if (sliderStep) sliderStep.name = 'questions[' + qi + '][slider_step]';

            // Update remove button visibility
            var removeQBtn = qBlock.querySelector('.remove-question-btn');
            if (removeQBtn) removeQBtn.style.display = questionBlocks.length > 1 ? '' : 'none';

            // Reindex arm blocks within this question
            var armBlocks = qBlock.querySelectorAll('.question-arm-block');
            armBlocks.forEach(function(aBlock, ai) {
                aBlock.dataset.armIndex = ai;
                var armLabelRef = aBlock.querySelector('.arm-label-ref');
                if (armLabelRef) armLabelRef.textContent = armLabels[ai] || 'Arm ' + (ai + 1);
                var copyBtn = aBlock.querySelector('.copy-from-first-btn');
                if (copyBtn) {
                    copyBtn.style.display = ai === 0 ? 'none' : '';
                    copyBtn.querySelector('.first-arm-name').textContent = armLabels[0] || 'Arm 1';
                }

                var qTextInput = aBlock.querySelector('.arm-question-text');
                if (qTextInput) {
                    qTextInput.name = 'questions[' + qi + '][arms][' + ai + '][question_text]';
                    qTextInput.placeholder = 'Question text for ' + (armLabels[ai] || 'this arm');
                }

                // Reindex image input
                var imageInput = aBlock.querySelector('.arm-image-input');
                if (imageInput) imageInput.name = 'questions[' + qi + '][arms][' + ai + '][image]';
                var existingImageInput = aBlock.querySelector('.existing-image-input');
                if (existingImageInput) existingImageInput.name = 'questions[' + qi + '][arms][' + ai + '][existing_image]';
                var allowOtherInput = aBlock.querySelector('.allow-other-input');
                if (allowOtherInput) allowOtherInput.name = 'questions[' + qi + '][arms][' + ai + '][allow_other]';

                // Reindex options
                var optionRows = aBlock.querySelectorAll('.q-option-row');
                optionRows.forEach(function(row, oi) {
                    var input = row.querySelector('input');
                    input.name = 'questions[' + qi + '][arms][' + ai + '][options][' + oi + ']';
                    input.placeholder = 'Option ' + (oi + 1);
                    var removeBtn = row.querySelector('.remove-q-option-btn');
                    if (removeBtn) removeBtn.style.display = optionRows.length > 2 ? '' : 'none';
                });
            });

            // Timer rows (in the Advanced options pop-up), one per arm
            qBlock.querySelectorAll('.timer-row').forEach(function(row, ai) {
                row.dataset.armIndex = ai;
                var armName = row.querySelector('.timer-arm-name');
                if (armName) armName.textContent = armLabels[ai] || 'Arm ' + (ai + 1);
                [['.timer-on-input', 'timer_on'], ['.timer-seconds-input', 'timer_seconds'],
                 ['.timer-display-input', 'timer_display'], ['.timer-default-input', 'timer_default']].forEach(function(pair) {
                    var el = row.querySelector(pair[0]);
                    if (el) el.name = 'questions[' + qi + '][arms][' + ai + '][' + pair[1] + ']';
                });
            });
            var advTitle = qBlock.querySelector('.q-adv-title');
            if (advTitle) advTitle.textContent = 'Question ' + (qi + 1);
        });
        refreshRules();
    }

    // --- One-line summary in each question's header (visible even when collapsed) ---
    var TYPE_NAMES = { multiple_choice: 'Multiple choice', multiple_answer: 'Multiple answer',
                       numeric: 'Number', short_answer: 'Short answer', slider: 'Slider' };
    function badge(text, cls, title) {
        var span = document.createElement('span');
        span.className = 'badge rounded-pill ' + (cls || 'text-bg-light border');
        span.textContent = text;
        if (title) span.title = title;
        return span;
    }
    function updateSummaries() {
        var armLabels = getArmLabels();
        questionsContainer.querySelectorAll('.question-block').forEach(function(qBlock, qi) {
            var type = qBlock.querySelector('.question-type-select').value;
            var labelInput = qBlock.querySelector('input[name*="[label]"]');
            var label = labelInput ? labelInput.value.trim() : '';
            var summary = qBlock.querySelector('.q-summary');
            if (summary) summary.textContent = (label ? label + ' \u00b7 ' : '') + (TYPE_NAMES[type] || type);

            var holder = qBlock.querySelector('.q-badges');
            if (!holder) return;
            holder.innerHTML = '';
            var shownBoxes = qBlock.querySelectorAll('.show-arm-input');
            var shownIn = [];
            shownBoxes.forEach(function(box, ai) { if (box.checked) shownIn.push(armLabels[ai]); });
            if (shownBoxes.length && shownIn.length < shownBoxes.length) {
                holder.appendChild(badge(shownIn.length ? 'Only in: ' + shownIn.join(', ') : 'Shown in no arm',
                                         shownIn.length ? 'text-bg-info' : 'text-bg-danger'));
            }
            var condInput = qBlock.querySelector('.cond-question-input');
            if (condInput && condInput.value !== '') {
                var values = Array.prototype.map.call(qBlock.querySelectorAll('.cond-value-input:checked'), function(i) { return i.value; });
                holder.appendChild(badge('Only if Q' + (parseInt(condInput.value, 10) + 1) + ' = ' + (values.join(' or ') || '?'), 'text-bg-info'));
            }
            var timers = [];
            qBlock.querySelectorAll('.timer-row').forEach(function(row, ai) {
                if (row.querySelector('.timer-on-input').checked) {
                    timers.push((row.querySelector('.timer-seconds-input').value || '?') + 's ' + armLabels[ai]);
                }
            });
            if (timers.length) holder.appendChild(badge('\u23f1 ' + timers.join(', '), 'text-bg-warning'));
            var withOther = [];
            qBlock.querySelectorAll('.question-arm-block').forEach(function(aBlock, ai) {
                var other = aBlock.querySelector('.allow-other-input');
                if (typeHasOptions(type) && other && other.value === '1') withOther.push(armLabels[ai]);
            });
            if (withOther.length) holder.appendChild(badge('+ Other' + (withOther.length < armLabels.length ? ' (' + withOther.join(', ') + ')' : '')));
            if (qBlock.dataset.part === '2') holder.appendChild(badge('Part 2', 'text-bg-dark'));
        });
    }

    // --- Two-part survey ---
    // "Part 2 starts at Question N" follows that question (by data-uid) when questions are
    // added or removed; the hidden part2_from field gets its current index ('' = one part).
    var partSwitch = document.getElementById('two-part-switch');
    var partSelect = document.getElementById('part2-select');
    var partInput = document.getElementById('part2-from');
    var partUid = null, partIndex = -1;
    function refreshParts() {
        if (!partSwitch) return;
        var blocks = Array.prototype.slice.call(questionsContainer.querySelectorAll('.question-block'));
        if (partIndex === -1 && partInput.value !== '' && blocks[parseInt(partInput.value, 10)]) {
            partIndex = parseInt(partInput.value, 10);
            partUid = blockUid(blocks[partIndex]);
        }
        var found = blocks.findIndex(function(b) { return partUid && b.dataset.uid === partUid; });
        if (found < 1) found = blocks.length > 1 ? Math.min(Math.max(partIndex, 1), blocks.length - 1) : -1;
        var html = '';
        for (var j = 1; j < blocks.length; j++) {
            html += '<option value="' + blockUid(blocks[j]) + '">Question ' + (j + 1) + '</option>';
        }
        if (partSelect.innerHTML !== html) partSelect.innerHTML = html;
        if (found > 0) {
            partUid = blockUid(blocks[found]);
            partSelect.value = partUid;
        }
        partIndex = found;
        var on = partSwitch.checked;
        document.getElementById('two-part-fields').style.display = on ? '' : 'none';
        partInput.value = on ? (found > 0 ? found : blocks.length) : '';
        blocks.forEach(function(b, i) {
            b.dataset.part = on && found > 0 && i >= found ? '2' : '1';
            b.classList.toggle('part2-first', on && i === found);
        });
        document.dispatchEvent(new CustomEvent('two-part-changed', { detail: { on: on } }));
    }
    if (partSwitch) {
        partSwitch.addEventListener('change', function() { refreshRules(); });
        partSelect.addEventListener('change', function() {
            partUid = partSelect.value;
            partIndex = -2;  // keep the chosen question (found by its uid)
            refreshRules();
        });
    }

    // --- Collapsible sections and questions (remembered for this browser tab) ---
    var surveyForm = document.getElementById('survey-form');
    var collapseScope = (surveyForm && surveyForm.dataset.collapseScope) || 'new';
    function collapseKey(el) {
        if (el.classList.contains('question-block')) {
            return 'collapse-' + collapseScope + '-q' + Array.prototype.indexOf.call(questionsContainer.querySelectorAll('.question-block'), el);
        }
        var toggle = el.querySelector('.collapse-toggle[data-collapse-key]');
        return 'collapse-' + collapseScope + '-' + (toggle ? toggle.dataset.collapseKey : el.id);
    }
    function bodyOf(el) {
        return el.classList.contains('question-block') ? el.querySelector('.q-body') : el.querySelector('.collapse-body');
    }
    function setCollapsed(el, collapsed, remember) {
        var body = bodyOf(el);
        if (!body) return;
        body.style.display = collapsed ? 'none' : '';
        var toggle = el.querySelector('.collapse-toggle');
        if (toggle) {
            toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            var chevron = toggle.querySelector('.collapse-chevron');
            if (chevron) chevron.textContent = collapsed ? '\u25b8' : '\u25be';
        }
        if (remember !== false) { try { sessionStorage.setItem(collapseKey(el), collapsed ? '1' : '0'); } catch (err) {} }
    }
    function initCollapsing() {
        document.querySelectorAll('.collapsible-card, #questions-container .question-block').forEach(function(el) {
            var saved = null;
            try { saved = sessionStorage.getItem(collapseKey(el)); } catch (err) {}
            var collapsed = saved !== null ? saved === '1' : el.dataset.defaultCollapsed === '1';
            setCollapsed(el, collapsed, false);
        });
    }
    function onToggle(e) {
        var toggle = e.target.closest('.collapse-toggle');
        if (!toggle) return;
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
        e.preventDefault();
        var el = toggle.closest('.question-block') || toggle.closest('.collapsible-card');
        var body = bodyOf(el);
        setCollapsed(el, body.style.display !== 'none');
    }
    document.addEventListener('click', onToggle);
    document.addEventListener('keydown', onToggle);
    function setAllQuestions(collapsed) {
        questionsContainer.querySelectorAll('.question-block').forEach(function(q) { setCollapsed(q, collapsed); });
    }
    var expandAll = document.getElementById('expand-all-questions');
    var collapseAll = document.getElementById('collapse-all-questions');
    if (expandAll) expandAll.addEventListener('click', function(e) { e.preventDefault(); setAllQuestions(false); });
    if (collapseAll) collapseAll.addEventListener('click', function(e) { e.preventDefault(); setAllQuestions(true); });

    // --- Advanced options pop-up (one per question, inside the question so its fields save with the form) ---
    function openAdvanced(e) {
        var btn = e.target.closest('.q-advanced-btn');
        if (!btn) return;
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
        e.preventDefault();
        refreshRules();
        var modal = btn.closest('.question-block').querySelector('.q-advanced-modal');
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }
    questionsContainer.addEventListener('click', openAdvanced);
    questionsContainer.addEventListener('keydown', openAdvanced);
    // "Done" and the close cross are links (buttons would be disabled on a locked page)
    document.addEventListener('click', function(e) {
        if (e.target.closest('.q-advanced-modal [data-bs-dismiss="modal"]')) e.preventDefault();
    });
    // Timer edits update the header badges
    questionsContainer.addEventListener('input', function(e) {
        if (e.target.closest('.timer-row') || (e.target.name || '').indexOf('[label]') !== -1) updateSummaries();
    });

    // --- (i) info tips: hover on a computer, tap on a phone ---
    function showTip(e) {
        var tip = e.target.closest && e.target.closest('.info-tip');
        if (!tip || typeof bootstrap === 'undefined') return;
        if (!bootstrap.Tooltip.getInstance(tip)) {
            bootstrap.Tooltip.getOrCreateInstance(tip, { trigger: 'hover focus', placement: 'top' }).show();
        }
    }
    document.addEventListener('mouseover', showTip);
    document.addEventListener('focusin', showTip);

    // --- Display rules ---
    // "Shown in" arm boxes follow the arms; "Show it: if Qn ..." lists earlier choice
    // questions and their answers. The condition is tracked by a per-question key
    // (data-uid) so removing or adding questions keeps it pointing at the same question;
    // the hidden cond_question field gets that question's current number on every refresh.
    var uidCounter = 0;
    function blockUid(qBlock) {
        if (!qBlock.dataset.uid) qBlock.dataset.uid = 'q' + (++uidCounter);
        return qBlock.dataset.uid;
    }
    function choiceAnswers(qBlock) {
        var values = [];
        qBlock.querySelectorAll('.question-arm-block').forEach(function(aBlock) {
            aBlock.querySelectorAll('.q-option-row input').forEach(function(input) {
                var v = input.value.trim();
                if (v && values.indexOf(v) === -1) values.push(v);
            });
            var other = aBlock.querySelector('.allow-other-input');
            if (other && other.value === '1' && values.indexOf('Other') === -1) values.push('Other');
        });
        return values;
    }
    function isChoiceBlock(qBlock) {
        return typeHasOptions(qBlock.querySelector('.question-type-select').value);
    }
    var rulesReady = false;
    function refreshRules() {
        var armLabels = getArmLabels();
        var blocks = Array.prototype.slice.call(questionsContainer.querySelectorAll('.question-block'));
        blocks.forEach(blockUid);
        blocks.forEach(function(qBlock, qi) {
            var rules = qBlock.querySelector('.rules-section');
            if (!rules) return;
            rules.querySelector('.rules-present').name = 'questions[' + qi + '][rules_present]';

            // "Shown in": one box per arm, same order
            var holder = rules.querySelector('.show-arms-boxes');
            var boxes = holder.querySelectorAll('.show-arm-box');
            for (var k = boxes.length; k < armLabels.length; k++) {
                var label = document.createElement('label');
                label.className = 'me-2 show-arm-box';
                label.innerHTML = '<input type="checkbox" class="form-check-input show-arm-input" checked> <span class="show-arm-name"></span>';
                holder.appendChild(label);
            }
            holder.querySelectorAll('.show-arm-box').forEach(function(box, ai) {
                if (ai >= armLabels.length) { box.remove(); return; }
                var input = box.querySelector('input');
                input.name = 'questions[' + qi + '][show_arms]';
                input.value = ai;
                box.querySelector('.show-arm-name').textContent = armLabels[ai];
            });
            // Dim this question's versions in arms that don't see it
            var shown = Array.prototype.map.call(holder.querySelectorAll('.show-arm-input'), function(i) { return i.checked; });
            qBlock.querySelectorAll('.question-arm-block').forEach(function(aBlock, ai) {
                var hidden = shown[ai] === false;
                aBlock.style.opacity = hidden ? '0.45' : '';
                aBlock.title = hidden ? 'Not shown in this arm (see Display rules)' : '';
            });

            // "Show it: always / if Qn ..."
            var select = rules.querySelector('.cond-select');
            if (!rulesReady && rules.dataset.condIndex !== '') {
                var src = blocks[parseInt(rules.dataset.condIndex, 10)];
                select.dataset.uid = src ? blockUid(src) : '';
            }
            var chosenUid = select.dataset.uid || '';
            var optionsHtml = '<option value="">always</option>';
            var stillValid = false;
            for (var j = 0; j < qi; j++) {
                if (!isChoiceBlock(blocks[j])) continue;
                var uid = blockUid(blocks[j]);
                var labelInput = blocks[j].querySelector('input[name*="[label]"]');
                var name = 'only if Question ' + (j + 1) + (labelInput && labelInput.value ? ' (' + labelInput.value + ')' : '');
                optionsHtml += '<option value="' + uid + '"' + (uid === chosenUid ? ' selected' : '') + '>'
                    + name.replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</option>';
                if (uid === chosenUid) stillValid = true;
            }
            if (select.innerHTML !== optionsHtml) select.innerHTML = optionsHtml;
            if (!stillValid) { chosenUid = ''; select.dataset.uid = ''; select.value = ''; }
            var srcIndex = chosenUid ? blocks.findIndex(function(b) { return b.dataset.uid === chosenUid; }) : -1;
            var condInput = rules.querySelector('.cond-question-input');
            condInput.name = 'questions[' + qi + '][cond_question]';
            condInput.value = srcIndex >= 0 ? srcIndex : '';

            // Answer boxes for the chosen question, keeping what was ticked
            var wrap = rules.querySelector('.cond-values-wrap');
            var valuesHolder = rules.querySelector('.cond-values');
            wrap.style.display = srcIndex >= 0 ? '' : 'none';
            var checked;
            if (!rulesReady) {
                try { checked = JSON.parse(rules.dataset.condValues || '[]'); } catch (e) { checked = []; }
            } else {
                checked = Array.prototype.map.call(valuesHolder.querySelectorAll('input:checked'), function(i) { return i.value; });
            }
            var answersList = srcIndex >= 0 ? choiceAnswers(blocks[srcIndex]) : [];
            var key = answersList.join('\u0001');
            if (valuesHolder.dataset.key !== key) {
                valuesHolder.dataset.key = key;
                valuesHolder.innerHTML = '';
                answersList.forEach(function(v) {
                    var label = document.createElement('label');
                    label.className = 'me-2';
                    var input = document.createElement('input');
                    input.type = 'checkbox';
                    input.className = 'form-check-input cond-value-input';
                    input.value = v;
                    input.checked = checked.indexOf(v) !== -1;
                    label.appendChild(input);
                    label.appendChild(document.createTextNode(' ' + v));
                    valuesHolder.appendChild(label);
                });
                if (!answersList.length && srcIndex >= 0) valuesHolder.innerHTML = '<em class="text-muted">(that question has no answers yet)</em>';
            }
            valuesHolder.querySelectorAll('.cond-value-input').forEach(function(input) {
                input.name = 'questions[' + qi + '][cond_values]';
            });
        });
        rulesReady = true;
        refreshParts();
        updateSummaries();
    }

    var rulesTimer = null;
    function refreshRulesSoon() {
        clearTimeout(rulesTimer);
        rulesTimer = setTimeout(refreshRules, 250);
    }
    questionsContainer.addEventListener('change', function(e) {
        if (e.target.classList.contains('cond-select')) {
            e.target.dataset.uid = e.target.value;
            refreshRules();
            e.target.form && e.target.form.dispatchEvent(new Event('change'));  // autosave the new hidden value
        } else if (e.target.classList.contains('show-arm-input') || e.target.classList.contains('question-type-select')) {
            refreshRules();
        }
    });
    // Option texts and labels feed the condition lists
    questionsContainer.addEventListener('input', function(e) {
        if (e.target.closest('.q-option-row') || (e.target.name || '').indexOf('[label]') !== -1) refreshRulesSoon();
    });
    armsContainer.addEventListener('input', refreshRulesSoon);

    // --- Build an arm block HTML for inside a question ---
    function typeHasOptions(questionType) {
        return questionType === 'multiple_choice' || questionType === 'multiple_answer';
    }

    // New questions, arm versions and timer rows are copied from the page's <template>s
    // (rendered by the same Jinja macros as the existing ones); reindexAll() then gives
    // their fields the right names.
    function fromTemplate(id) {
        var tpl = document.getElementById(id);
        return tpl ? tpl.content.firstElementChild.cloneNode(true) : null;
    }

    // Make a question have exactly one arm version and one timer row per arm
    function syncQuestionArms(qBlock) {
        var count = armsContainer.querySelectorAll('.arm-label-block').length;
        var armsDiv = qBlock.querySelector('.question-arms');
        var timerRows = qBlock.querySelector('.timer-rows');
        var showOptions = typeHasOptions(qBlock.querySelector('.question-type-select').value);
        while (armsDiv.querySelectorAll('.question-arm-block').length > count) armsDiv.lastElementChild.remove();
        while (armsDiv.querySelectorAll('.question-arm-block').length < count) {
            var arm = fromTemplate('tpl-arm');
            arm.querySelector('.question-options-section').style.display = showOptions ? '' : 'none';
            armsDiv.appendChild(arm);
        }
        if (timerRows) {
            while (timerRows.querySelectorAll('.timer-row').length > count) timerRows.lastElementChild.remove();
            while (timerRows.querySelectorAll('.timer-row').length < count) timerRows.appendChild(fromTemplate('tpl-timer-row'));
        }
    }

    // --- Add arm ---
    document.getElementById('add-arm-btn').addEventListener('click', function() {
        var armCount = armsContainer.querySelectorAll('.arm-label-block').length;
        if (armCount >= 4) {
            alert('Maximum 4 arms allowed.');
            return;
        }
        var i = armCount;
        var html = '<div class="arm-label-block d-flex align-items-center gap-2 mb-2" data-arm-index="' + i + '">';
        html += '<span class="fw-bold arm-number-label">Arm ' + (i + 1) + ':</span>';
        html += '<input type="text" class="form-control" name="arms[' + i + '][label]" placeholder="e.g., Treatment B" required>';
        html += '<button type="button" class="btn btn-sm btn-outline-danger remove-arm-btn">Remove</button>';
        html += '</div>';
        armsContainer.insertAdjacentHTML('beforeend', html);

        // Add a version of every question (and a timer row) for the new arm
        questionsContainer.querySelectorAll('.question-block').forEach(syncQuestionArms);

        reindexAll();
        document.dispatchEvent(new CustomEvent('arms-changed', { detail: { added: i } }));
    });

    // --- Remove arm ---
    armsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-arm-btn')) {
            var armBlock = e.target.closest('.arm-label-block');
            if (armsContainer.querySelectorAll('.arm-label-block').length <= 1) return;
            var removedIndex = parseInt(armBlock.dataset.armIndex);
            armBlock.remove();

            // Remove corresponding arm block (and its "Shown in" box) from each question
            questionsContainer.querySelectorAll('.question-block').forEach(function(qBlock) {
                var box = qBlock.querySelectorAll('.show-arm-box')[removedIndex];
                if (box) box.remove();
                var timerRow = qBlock.querySelectorAll('.timer-row')[removedIndex];
                if (timerRow) timerRow.remove();
                var armBlocks = qBlock.querySelectorAll('.question-arm-block');
                if (armBlocks[removedIndex]) {
                    armBlocks[removedIndex].remove();
                }
            });

            reindexAll();
            document.dispatchEvent(new CustomEvent('arms-changed', { detail: { removed: removedIndex } }));
        }
    });

    // --- Update arm labels in questions when arm label input changes ---
    armsContainer.addEventListener('input', function(e) {
        if (e.target.matches('input[name*="[label]"]')) {
            var armBlock = e.target.closest('.arm-label-block');
            var ai = parseInt(armBlock.dataset.armIndex);
            var label = e.target.value || 'Arm ' + (ai + 1);
            questionsContainer.querySelectorAll('.question-block').forEach(function(qBlock) {
                var armBlocks = qBlock.querySelectorAll('.question-arm-block');
                if (armBlocks[ai]) {
                    var ref = armBlocks[ai].querySelector('.arm-label-ref');
                    if (ref) ref.textContent = label;
                    var textInput = armBlocks[ai].querySelector('.arm-question-text');
                    if (textInput) textInput.placeholder = 'Question text for ' + label;
                }
                if (ai === 0) {
                    qBlock.querySelectorAll('.first-arm-name').forEach(function(span) { span.textContent = label; });
                }
            });
        }
    });

    // --- Add question ---
    var maxQuestions = parseInt(document.getElementById('survey-form').dataset.maxQuestions || '0', 10);
    var addQuestionBtn = document.getElementById('add-question-btn');
    function updateAddQuestionBtn() {
        if (!maxQuestions) return;
        var atLimit = questionsContainer.querySelectorAll('.question-block').length >= maxQuestions;
        addQuestionBtn.disabled = atLimit;
        addQuestionBtn.title = atLimit ? 'Your instructor allows up to ' + maxQuestions + ' question(s).' : '';
    }
    updateAddQuestionBtn();
    new MutationObserver(updateAddQuestionBtn).observe(questionsContainer, { childList: true });

    addQuestionBtn.addEventListener('click', function() {
        var qi = questionsContainer.querySelectorAll('.question-block').length;
        if (maxQuestions && qi >= maxQuestions) return;

        var qBlock = fromTemplate('tpl-question');
        questionsContainer.appendChild(qBlock);
        syncQuestionArms(qBlock);
        reindexAll();
        setCollapsed(qBlock, false);
        qBlock.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    // --- Remove question ---
    questionsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-question-btn')) {
            if (questionsContainer.querySelectorAll('.question-block').length <= 1) return;
            e.target.closest('.question-block').remove();
            reindexAll();
        }
    });

    // --- Per-question type toggle ---
    questionsContainer.addEventListener('change', function(e) {
        if (e.target.classList.contains('question-type-select')) {
            var qtype = e.target.value;
            var showOptions = typeHasOptions(qtype);
            var showSlider = qtype === 'slider';
            var qBlock = e.target.closest('.question-block');
            qBlock.querySelectorAll('.question-options-section').forEach(function(section) {
                section.style.display = showOptions ? '' : 'none';
            });
            var sliderSection = qBlock.querySelector('.slider-config-section');
            if (sliderSection) sliderSection.style.display = showSlider ? '' : 'none';
        }
    });

    // --- Add option within a question arm ---
    questionsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('add-q-option-btn')) {
            var container = e.target.closest('.question-options-section').querySelector('.question-options-container');
            var optCount = container.querySelectorAll('.q-option-row').length;
            if (optCount >= 5) {
                alert('Maximum 5 options.');
                return;
            }
            var qBlock = e.target.closest('.question-block');
            var aBlock = e.target.closest('.question-arm-block');
            var qi = parseInt(qBlock.dataset.questionIndex);
            var ai = parseInt(aBlock.dataset.armIndex);

            var html = '<div class="input-group mb-1 q-option-row">';
            html += '<input type="text" class="form-control form-control-sm" ';
            html += 'name="questions[' + qi + '][arms][' + ai + '][options][' + optCount + ']" ';
            html += 'placeholder="Option ' + (optCount + 1) + '">';
            html += '<button type="button" class="btn btn-sm btn-outline-danger remove-q-option-btn">x</button>';
            html += '</div>';
            container.insertAdjacentHTML('beforeend', html);

            var rows = container.querySelectorAll('.q-option-row');
            rows.forEach(function(row) {
                row.querySelector('.remove-q-option-btn').style.display = rows.length > 2 ? '' : 'none';
            });
        }
    });

    // --- Remove option ---
    questionsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-q-option-btn')) {
            var row = e.target.closest('.q-option-row');
            var container = row.parentElement;
            if (container.querySelectorAll('.q-option-row').length <= 2) return;
            row.remove();
            reindexAll();
        }
    });

    // --- Copy question text, options and image from the first arm ---
    questionsContainer.addEventListener('click', function(e) {
        var btn = e.target.closest('.copy-from-first-btn');
        if (!btn) return;
        var target = btn.closest('.question-arm-block');
        var source = btn.closest('.question-arms').querySelector('.question-arm-block');
        if (!source || source === target) return;

        target.querySelector('.arm-question-text').value = source.querySelector('.arm-question-text').value;

        // Options: rebuild the target's rows to mirror the source's
        var srcInputs = source.querySelectorAll('.q-option-row input');
        var container = target.querySelector('.question-options-container');
        container.innerHTML = '';
        srcInputs.forEach(function(input) {
            var row = document.createElement('div');
            row.className = 'input-group mb-1 q-option-row';
            row.innerHTML = '<input type="text" class="form-control form-control-sm">' +
                '<button type="button" class="btn btn-sm btn-outline-danger remove-q-option-btn">x</button>';
            row.querySelector('input').value = input.value;
            container.appendChild(row);
        });

        // The timer (rows in the Advanced options pop-up, same order as the arms)
        var qOfTarget = target.closest('.question-block');
        var rows = qOfTarget.querySelectorAll('.timer-row');
        var targetIndex = Array.prototype.indexOf.call(qOfTarget.querySelectorAll('.question-arm-block'), target);
        var srcRow = rows[0], dstRow = rows[targetIndex];
        if (srcRow && dstRow && srcRow !== dstRow) {
            ['.timer-seconds-input', '.timer-display-input', '.timer-default-input'].forEach(function(sel) {
                dstRow.querySelector(sel).value = srcRow.querySelector(sel).value;
            });
            var dstTimer = dstRow.querySelector('.timer-on-input');
            dstTimer.checked = srcRow.querySelector('.timer-on-input').checked;
            dstRow.querySelector('.timer-fields').style.display = dstTimer.checked ? '' : 'none';
        }

        // The "Other" choice
        var srcOther = source.querySelector('.allow-other-input');
        setAllowOther(target, !!(srcOther && srcOther.value === '1'));

        // Image: reuse the first arm's saved image, if any
        var srcImage = source.querySelector('.existing-image-input');
        setExistingImage(target, srcImage ? srcImage.value : null);

        reindexAll();
        target.querySelector('.arm-question-text').focus();
    });

    // --- Timer switch: show/hide its fields ---
    questionsContainer.addEventListener('change', function(e) {
        if (e.target.classList.contains('timer-on-input')) {
            e.target.closest('.timer-row').querySelector('.timer-fields').style.display = e.target.checked ? '' : 'none';
            updateSummaries();
        }
    });

    // --- "Other" choice (respondents type their own answer) ---
    function setAllowOther(armBlock, on) {
        var input = armBlock.querySelector('.allow-other-input');
        if (!input) return;
        input.value = on ? '1' : '';
        armBlock.querySelector('.q-other-row').style.display = on ? '' : 'none';
        armBlock.querySelector('.add-q-other-btn').style.display = on ? 'none' : '';
        input.dispatchEvent(new Event('change', { bubbles: true }));  // let autosave notice
    }

    questionsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('add-q-other-btn')) {
            setAllowOther(e.target.closest('.question-arm-block'), true);
        } else if (e.target.classList.contains('remove-q-other-btn')) {
            setAllowOther(e.target.closest('.question-arm-block'), false);
        }
    });

    // --- Existing (saved) image display for an arm block ---
    function setExistingImage(armBlock, filename) {
        var section = armBlock.querySelector('.arm-image-section');
        var info = section.querySelector('.existing-image-info');
        var hidden = section.querySelector('.existing-image-input');
        if (info) info.remove();
        if (hidden) hidden.remove();
        if (!filename) return;
        var shortName = filename.indexOf('_') !== -1 ? filename.split('_').slice(1).join('_') : filename;
        info = document.createElement('div');
        info.className = 'd-flex align-items-center gap-2 mb-1 existing-image-info';
        info.innerHTML = '<small class="text-muted"></small>' +
            '<a target="_blank" class="btn btn-sm btn-outline-secondary py-0">View</a>' +
            '<button type="button" class="btn btn-sm btn-outline-danger py-0 remove-image-btn">Remove</button>';
        info.querySelector('small').textContent = 'Image: ' + shortName;
        info.querySelector('a').href = '/uploads/' + encodeURIComponent(filename);
        hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.className = 'existing-image-input';
        hidden.value = filename;
        section.insertBefore(hidden, section.firstChild);
        section.insertBefore(info, section.firstChild);
        reindexAll();
    }

    questionsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-image-btn')) {
            setExistingImage(e.target.closest('.question-arm-block'), null);
        }
    });

    // Fill in names, display-rule controls and summaries before autosave records the page's starting version
    reindexAll();
    initCollapsing();

    // Drag questions (by their ⠿ handle) to reorder them. Display rules and the part-2 split
    // follow their questions (tracked by data-uid); the new order saves like any other change.
    var formFieldset = document.querySelector('#survey-form > fieldset');
    if (window.Sortable && !(formFieldset && formFieldset.disabled)) {
        Sortable.create(questionsContainer, {
            handle: '.q-drag', draggable: '.question-block', animation: 150,
            onEnd: function(evt) {
                if (evt.oldIndex === evt.newIndex) return;
                reindexAll();
                var surveyFormEl = document.getElementById('survey-form');
                if (surveyFormEl) surveyFormEl.dispatchEvent(new Event('change'));
            },
        });
    } else {
        document.querySelectorAll('.q-drag').forEach(function(h) { h.style.display = 'none'; });
    }

    // Coming from the flow chart (#q-3): open that question and bring it into view
    (function() {
        var m = /^#q-(\d+)$/.exec(window.location.hash);
        if (!m) return;
        var block = questionsContainer.querySelectorAll('.question-block')[parseInt(m[1], 10) - 1];
        if (!block) return;
        var card = document.getElementById('questions-card');
        if (card) setCollapsed(card, false);
        setCollapsed(block, false);
        block.classList.add('border-primary', 'border-2');
        setTimeout(function() {
            block.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
        setTimeout(function() { block.classList.remove('border-primary', 'border-2'); }, 4000);
    })();

    // --- Autosave (edit page only) ---
    // Saves the whole form in the background shortly after any change. The first
    // version seen in this browser tab is kept in sessionStorage so "Discard all
    // changes from this session" can put it back (no versions are stored on the server).
    var form = document.getElementById('survey-form');
    // "We're sending our survey from another platform": arms and questions become optional.
    // Disabling their fieldset skips their validation and leaves them out of the posted form.
    var externalBox = document.getElementById('external');
    if (externalBox) {
        externalBox.addEventListener('change', function() {
            var design = document.getElementById('in-app-design');
            design.disabled = externalBox.checked;
            design.style.display = externalBox.checked ? 'none' : '';
            document.getElementById('external-fields').style.display = externalBox.checked ? '' : 'none';
        });
    }

    var autosaveUrl = form && form.dataset.autosaveUrl;
    if (autosaveUrl) {
        var statusEl = document.getElementById('autosave-status');
        var discardBtn = document.getElementById('discard-btn');
        var baselineKey = 'survey-baseline-' + form.dataset.surveyId;
        var saveTimer = null, saving = false, pending = false, stopped = false;

        function serializeForm() {
            var entries = [];
            new FormData(form).forEach(function(value, key) {
                if (!(value instanceof File)) entries.push([key, value]);
            });
            return entries;
        }

        function storageGet(key) { try { return sessionStorage.getItem(key); } catch (err) { return null; } }
        function storageSet(key, value) { try { sessionStorage.setItem(key, value); } catch (err) {} }
        function storageRemove(key) { try { sessionStorage.removeItem(key); } catch (err) {} }

        var baseline = storageGet(baselineKey);
        if (!baseline) {
            baseline = JSON.stringify(serializeForm());
            storageSet(baselineKey, baseline);
        }

        function updateDiscardVisibility() {
            discardBtn.style.display = JSON.stringify(serializeForm()) !== baseline ? '' : 'none';
        }
        updateDiscardVisibility();

        function setStatus(text, cls) {
            statusEl.textContent = text;
            statusEl.className = cls || '';
        }

        function renderWarnings(warnings) {
            var box = document.getElementById('survey-warnings');
            if (!box) return;
            box.innerHTML = '';
            (warnings || []).forEach(function(w) {
                var div = document.createElement('div');
                div.className = 'alert alert-warning py-2 small mb-2';
                div.textContent = '⚠ ' + w;
                box.appendChild(div);
            });
        }

        function applySavedImages(images) {
            // Newly uploaded files are now on the server: show them as saved images and clear the file pickers
            questionsContainer.querySelectorAll('.question-block').forEach(function(qBlock, qi) {
                qBlock.querySelectorAll('.question-arm-block').forEach(function(aBlock, ai) {
                    var fileInput = aBlock.querySelector('.arm-image-input');
                    if (fileInput && fileInput.value) {
                        fileInput.value = '';
                        setExistingImage(aBlock, images[qi + '_' + ai] || null);
                    }
                });
            });
        }

        function post(entries, includeFiles) {
            var data = new FormData();
            entries.forEach(function(pair) { data.append(pair[0], pair[1]); });
            if (includeFiles) {
                form.querySelectorAll('.arm-image-input').forEach(function(input) {
                    if (input.files && input.files[0]) data.append(input.name, input.files[0]);
                });
            }
            return fetch(autosaveUrl, { method: 'POST', credentials: 'same-origin', body: data })
                .then(function(resp) { return resp.json(); });
        }

        function saveNow() {
            if (stopped) return;
            if (saving) { pending = true; return; }
            saving = true;
            setStatus('Saving…', 'text-muted');
            post(serializeForm(), true)
                .then(function(res) {
                    if (res.ok) {
                        applySavedImages(res.images || {});
                        renderWarnings(res.warnings);
                        var todo = res.todo || [];
                        var todoBox = document.getElementById('survey-todo');
                        if (todoBox) {
                            todoBox.style.display = todo.length ? '' : 'none';
                            document.getElementById('survey-todo-list').textContent = todo.join(' ');
                        }
                        setStatus('All changes saved at ' + res.saved_at + '.' +
                                  (todo.length ? ' Not finished yet: ' + todo.length + ' thing' + (todo.length > 1 ? 's' : '') + ' to do (see above).' : ''),
                                  'text-success');
                    } else if (res.reason === 'invalid') {
                        setStatus('Not saved yet: ' + res.errors[0] + (res.errors.length > 1 ? ' (+' + (res.errors.length - 1) + ' more)' : ''), 'text-warning-emphasis');
                    } else if (res.reason === 'locked') {
                        stopped = true;
                        setStatus('Survey editing has been locked by your instructor. Changes are no longer saved.', 'text-danger');
                    } else if (res.reason === 'has_responses') {
                        stopped = true;
                        setStatus('This survey now has responses, so autosave is off. Reload the page.', 'text-danger');
                    } else {
                        setStatus('Could not save. Check your connection; we will retry on your next change.', 'text-danger');
                    }
                })
                .catch(function() {
                    setStatus('Could not save. Check your connection; we will retry on your next change.', 'text-danger');
                })
                .finally(function() {
                    saving = false;
                    updateDiscardVisibility();
                    if (pending) { pending = false; scheduleSave(); }
                });
        }

        function scheduleSave() {
            if (stopped) return;
            clearTimeout(saveTimer);
            setStatus('Unsaved changes…', 'text-muted');
            saveTimer = setTimeout(saveNow, 1500);
        }

        form.addEventListener('input', scheduleSave);
        form.addEventListener('change', scheduleSave);
        // Adding/removing arms, questions, options or images changes the DOM without input events
        new MutationObserver(function(mutations) {
            if (saving) return;  // our own updates after a save (e.g. showing a just-uploaded image)
            var structural = mutations.some(function(m) {
                return Array.prototype.some.call(m.addedNodes.length ? m.addedNodes : m.removedNodes, function(n) {
                    return n.nodeType === 1 && (n.matches('.arm-label-block, .question-block, .question-arm-block, .q-option-row, .existing-image-input') ||
                        n.querySelector && n.querySelector('.q-option-row, .existing-image-input'));
                });
            });
            if (structural) scheduleSave();
        }).observe(form, { childList: true, subtree: true });

        // The explicit "Save now" button just saves immediately instead of reloading the page
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            clearTimeout(saveTimer);
            saveNow();
        });

        discardBtn.addEventListener('click', function() {
            if (!confirm('Go back to how the survey was when you opened it in this tab? All changes since then will be lost.')) return;
            stopped = true;
            clearTimeout(saveTimer);
            setStatus('Restoring…', 'text-muted');
            post(JSON.parse(baseline), false)
                .then(function(res) {
                    if (!res.ok) throw new Error(res.reason);
                    storageRemove(baselineKey);
                    window.location.reload();
                })
                .catch(function() {
                    stopped = false;
                    setStatus('Could not restore the earlier version.', 'text-danger');
                });
        });
    }

    // --- Teammate invite picker ---
    // Classmates come from a <datalist> whose options carry data-id. In "multi" mode
    // (new survey) picked names become chips with hidden invite_ids inputs inside the
    // survey form; in "single" mode (edit page) the picker's own form posts one invitee_id.
    function findClassmateId(list, name) {
        var match = null;
        list.querySelectorAll('option').forEach(function(opt) {
            if (opt.value.toLowerCase() === name.trim().toLowerCase()) match = opt;
        });
        return match ? { id: match.dataset.id, name: match.value } : null;
    }

    document.querySelectorAll('.invite-picker').forEach(function(picker) {
        var input = picker.querySelector('.invite-search');
        var list = document.getElementById(input.getAttribute('list'));
        var feedback = picker.querySelector('.invite-feedback');
        var chips = picker.querySelector('.invite-chips');

        function showFeedback(msg) {
            if (!feedback) return;
            feedback.textContent = msg;
            feedback.style.display = msg ? '' : 'none';
        }

        function addChip() {
            var found = findClassmateId(list, input.value);
            if (!found) { showFeedback('Pick a name from the list.'); return; }
            if (chips.querySelector('input[value="' + found.id + '"]')) { input.value = ''; return; }
            var chip = document.createElement('span');
            chip.className = 'badge rounded-pill text-bg-primary me-1 mb-1 p-2';
            chip.textContent = found.name + ' ';
            var hidden = document.createElement('input');
            hidden.type = 'hidden'; hidden.name = 'invite_ids'; hidden.value = found.id;
            var x = document.createElement('button');
            x.type = 'button'; x.className = 'btn-close btn-close-white ms-1';
            x.style.fontSize = '0.6em'; x.setAttribute('aria-label', 'Remove');
            x.addEventListener('click', function() { chip.remove(); });
            chip.appendChild(hidden); chip.appendChild(x);
            chips.appendChild(chip);
            input.value = '';
            showFeedback('');
        }

        if (picker.dataset.mode === 'multi') {
            picker.querySelector('.invite-add-btn').addEventListener('click', addChip);
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') { e.preventDefault(); addChip(); }
            });
            input.addEventListener('change', function() {
                if (findClassmateId(list, input.value)) addChip();
            });
        } else {
            picker.addEventListener('submit', function(e) {
                var found = findClassmateId(list, input.value);
                if (!found) { e.preventDefault(); showFeedback('Pick a name from the list.'); return; }
                picker.querySelector('input[name="invitee_id"]').value = found.id;
            });
        }
    });
});
