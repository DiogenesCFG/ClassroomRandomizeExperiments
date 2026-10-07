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
        });
    }

    // --- Build an arm block HTML for inside a question ---
    function typeHasOptions(questionType) {
        return questionType === 'multiple_choice' || questionType === 'multiple_answer';
    }

    function buildQuestionArmHTML(qi, ai, armLabel, questionType) {
        var showOptions = typeHasOptions(questionType);
        var html = '<div class="question-arm-block border-start border-3 ps-3 mb-3" data-arm-index="' + ai + '">';
        html += '<div class="d-flex justify-content-between align-items-baseline gap-2">';
        html += '<label class="form-label fw-bold arm-label-ref">' + (armLabel || 'Arm ' + (ai + 1)) + '</label>';
        html += '<button type="button" class="btn btn-link btn-sm p-0 copy-from-first-btn"' + (ai === 0 ? ' style="display:none"' : '') + '>';
        html += 'Copy from <span class="first-arm-name">' + (getArmLabels()[0] || 'Arm 1') + '</span></button>';
        html += '</div>';
        html += '<input type="text" class="form-control mb-1 arm-question-text" ';
        html += 'name="questions[' + qi + '][arms][' + ai + '][question_text]" ';
        html += 'placeholder="Question text for ' + (armLabel || 'this arm') + '" required>';
        html += '<div class="arm-image-section mb-1">';
        html += '<input type="file" class="form-control form-control-sm arm-image-input" ';
        html += 'name="questions[' + qi + '][arms][' + ai + '][image]" accept=".png,.jpg,.jpeg">';
        html += '<small class="text-muted">Optional image (PNG or JPEG, max 5MB)</small>';
        html += '</div>';
        html += '<div class="question-options-section"' + (showOptions ? '' : ' style="display:none"') + '>';
        html += '<label class="form-label text-muted small">Answer Options:</label>';
        html += '<div class="question-options-container">';
        html += '<div class="input-group mb-1 q-option-row">';
        html += '<input type="text" class="form-control form-control-sm" ';
        html += 'name="questions[' + qi + '][arms][' + ai + '][options][0]" placeholder="Option 1">';
        html += '<button type="button" class="btn btn-sm btn-outline-danger remove-q-option-btn" style="display:none">x</button>';
        html += '</div>';
        html += '<div class="input-group mb-1 q-option-row">';
        html += '<input type="text" class="form-control form-control-sm" ';
        html += 'name="questions[' + qi + '][arms][' + ai + '][options][1]" placeholder="Option 2">';
        html += '<button type="button" class="btn btn-sm btn-outline-danger remove-q-option-btn" style="display:none">x</button>';
        html += '</div>';
        html += '</div>';
        html += '<button type="button" class="btn btn-sm btn-outline-secondary add-q-option-btn mt-1">+ Add Option</button>';
        html += '</div></div>';
        return html;
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

        // Add an arm block to every question
        var questionBlocks = questionsContainer.querySelectorAll('.question-block');
        questionBlocks.forEach(function(qBlock) {
            var qi = parseInt(qBlock.dataset.questionIndex);
            var questionType = qBlock.querySelector('.question-type-select').value;
            var armsDiv = qBlock.querySelector('.question-arms');
            armsDiv.insertAdjacentHTML('beforeend', buildQuestionArmHTML(qi, i, '', questionType));
        });

        reindexAll();
    });

    // --- Remove arm ---
    armsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-arm-btn')) {
            var armBlock = e.target.closest('.arm-label-block');
            if (armsContainer.querySelectorAll('.arm-label-block').length <= 1) return;
            var removedIndex = parseInt(armBlock.dataset.armIndex);
            armBlock.remove();

            // Remove corresponding arm block from each question
            questionsContainer.querySelectorAll('.question-block').forEach(function(qBlock) {
                var armBlocks = qBlock.querySelectorAll('.question-arm-block');
                if (armBlocks[removedIndex]) {
                    armBlocks[removedIndex].remove();
                }
            });

            reindexAll();
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
        var armLabels = getArmLabels();
        var qi = questionsContainer.querySelectorAll('.question-block').length;
        if (maxQuestions && qi >= maxQuestions) return;

        var html = '<div class="question-block border rounded p-3 mb-3" data-question-index="' + qi + '">';
        html += '<div class="d-flex justify-content-between align-items-center mb-2">';
        html += '<h6 class="mb-0 question-header">Question ' + (qi + 1) + '</h6>';
        html += '<button type="button" class="btn btn-sm btn-outline-danger remove-question-btn">Remove</button>';
        html += '</div>';
        html += '<div class="row g-2 mb-3">';
        html += '<div class="col-md-4"><label class="form-label">Type</label>';
        html += '<select class="form-select question-type-select" name="questions[' + qi + '][question_type]">';
        html += '<option value="multiple_choice">Multiple Choice</option>';
        html += '<option value="multiple_answer">Multiple Answer</option>';
        html += '<option value="numeric">Numeric</option>';
        html += '<option value="short_answer">Short Answer</option>';
        html += '<option value="slider">Slider</option>';
        html += '</select></div>';
        html += '<div class="col-md-8"><label class="form-label">Label (optional)</label>';
        html += '<input type="text" class="form-control" name="questions[' + qi + '][label]" placeholder="e.g., Willingness to Pay">';
        html += '</div></div>';
        html += '<div class="slider-config-section row g-2 mb-3" style="display:none">';
        html += '<div class="col-md-4"><label class="form-label text-muted small">Min</label>';
        html += '<input type="number" class="form-control slider-min-input" name="questions[' + qi + '][slider_min]" value="0" step="any"></div>';
        html += '<div class="col-md-4"><label class="form-label text-muted small">Max</label>';
        html += '<input type="number" class="form-control slider-max-input" name="questions[' + qi + '][slider_max]" value="100" step="any"></div>';
        html += '<div class="col-md-4"><label class="form-label text-muted small">Step</label>';
        html += '<input type="number" class="form-control slider-step-input" name="questions[' + qi + '][slider_step]" value="1" step="any" min="0.01"></div>';
        html += '</div>';
        html += '<div class="question-arms">';
        for (var ai = 0; ai < armLabels.length; ai++) {
            html += buildQuestionArmHTML(qi, ai, armLabels[ai], 'multiple_choice');
        }
        html += '</div></div>';

        questionsContainer.insertAdjacentHTML('beforeend', html);
        reindexAll();
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
            var container = e.target.previousElementSibling;
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

        // Image: reuse the first arm's saved image, if any
        var srcImage = source.querySelector('.existing-image-input');
        setExistingImage(target, srcImage ? srcImage.value : null);

        reindexAll();
        target.querySelector('.arm-question-text').focus();
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
                        setStatus('All changes saved at ' + res.saved_at + '.', 'text-success');
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
