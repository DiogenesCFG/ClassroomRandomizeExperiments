document.addEventListener('DOMContentLoaded', function() {
    var armsContainer = document.getElementById('arms-container');
    var questionsContainer = document.getElementById('questions-container');
    var membersContainer = document.getElementById('members-container');

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
            if (removeBtn) removeBtn.style.display = armBlocks.length > 2 ? '' : 'none';
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

            // Update remove button visibility
            var removeQBtn = qBlock.querySelector('.remove-question-btn');
            if (removeQBtn) removeQBtn.style.display = questionBlocks.length > 1 ? '' : 'none';

            // Reindex arm blocks within this question
            var armBlocks = qBlock.querySelectorAll('.question-arm-block');
            armBlocks.forEach(function(aBlock, ai) {
                aBlock.dataset.armIndex = ai;
                var armLabelRef = aBlock.querySelector('.arm-label-ref');
                if (armLabelRef) armLabelRef.textContent = armLabels[ai] || 'Arm ' + (ai + 1);

                var qTextInput = aBlock.querySelector('.arm-question-text');
                if (qTextInput) {
                    qTextInput.name = 'questions[' + qi + '][arms][' + ai + '][question_text]';
                    qTextInput.placeholder = 'Question text for ' + (armLabels[ai] || 'this arm');
                }

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

        // Reindex members
        var memberRows = membersContainer.querySelectorAll('.member-row');
        memberRows.forEach(function(row, i) {
            var nameInput = row.querySelector('input[name*="[name]"]');
            var sisInput = row.querySelector('input[name*="[sis_code]"]');
            if (nameInput) nameInput.name = 'members[' + i + '][name]';
            if (sisInput) sisInput.name = 'members[' + i + '][sis_code]';
            var removeBtn = row.querySelector('.remove-member-btn');
            if (removeBtn) removeBtn.style.display = memberRows.length > 1 ? '' : 'none';
        });
    }

    // --- Build an arm block HTML for inside a question ---
    function buildQuestionArmHTML(qi, ai, armLabel, questionType) {
        var showOptions = questionType === 'multiple_choice';
        var html = '<div class="question-arm-block border-start border-3 ps-3 mb-3" data-arm-index="' + ai + '">';
        html += '<label class="form-label fw-bold arm-label-ref">' + (armLabel || 'Arm ' + (ai + 1)) + '</label>';
        html += '<input type="text" class="form-control mb-1 arm-question-text" ';
        html += 'name="questions[' + qi + '][arms][' + ai + '][question_text]" ';
        html += 'placeholder="Question text for ' + (armLabel || 'this arm') + '" required>';
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
            if (armsContainer.querySelectorAll('.arm-label-block').length <= 2) return;
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
            });
        }
    });

    // --- Add question ---
    document.getElementById('add-question-btn').addEventListener('click', function() {
        var armLabels = getArmLabels();
        var qi = questionsContainer.querySelectorAll('.question-block').length;

        var html = '<div class="question-block border rounded p-3 mb-3" data-question-index="' + qi + '">';
        html += '<div class="d-flex justify-content-between align-items-center mb-2">';
        html += '<h6 class="mb-0 question-header">Question ' + (qi + 1) + '</h6>';
        html += '<button type="button" class="btn btn-sm btn-outline-danger remove-question-btn">Remove</button>';
        html += '</div>';
        html += '<div class="row g-2 mb-3">';
        html += '<div class="col-md-4"><label class="form-label">Type</label>';
        html += '<select class="form-select question-type-select" name="questions[' + qi + '][question_type]">';
        html += '<option value="multiple_choice">Multiple Choice</option>';
        html += '<option value="numeric">Numeric</option>';
        html += '</select></div>';
        html += '<div class="col-md-8"><label class="form-label">Label (optional)</label>';
        html += '<input type="text" class="form-control" name="questions[' + qi + '][label]" placeholder="e.g., Willingness to Pay">';
        html += '</div></div>';
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
            var show = e.target.value === 'multiple_choice';
            var qBlock = e.target.closest('.question-block');
            qBlock.querySelectorAll('.question-options-section').forEach(function(section) {
                section.style.display = show ? '' : 'none';
            });
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

    // --- Add member ---
    document.getElementById('add-member-btn').addEventListener('click', function() {
        var i = membersContainer.querySelectorAll('.member-row').length;
        var html = '<div class="row g-2 mb-2 member-row">';
        html += '<div class="col-md-5"><input type="text" class="form-control" name="members[' + i + '][name]" placeholder="Student Name" required></div>';
        html += '<div class="col-md-5"><input type="text" class="form-control" name="members[' + i + '][sis_code]" placeholder="SIS Code" required></div>';
        html += '<div class="col-md-2"><button type="button" class="btn btn-outline-danger remove-member-btn">Remove</button></div>';
        html += '</div>';
        membersContainer.insertAdjacentHTML('beforeend', html);
        reindexAll();
    });

    // --- Remove member ---
    membersContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-member-btn')) {
            if (membersContainer.querySelectorAll('.member-row').length <= 1) return;
            e.target.closest('.member-row').remove();
            reindexAll();
        }
    });
});
