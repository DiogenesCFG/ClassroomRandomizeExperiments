document.addEventListener('DOMContentLoaded', function() {
    const armsContainer = document.getElementById('arms-container');
    const membersContainer = document.getElementById('members-container');
    const questionTypeSelect = document.getElementById('question_type');

    // Reindex all arm and member form fields after add/remove
    function reindexArms() {
        const arms = armsContainer.querySelectorAll('.arm-block');
        arms.forEach((arm, i) => {
            arm.dataset.armIndex = i;
            arm.querySelector('h6').textContent = 'Arm ' + (i + 1);

            // Update arm field names
            const labelInput = arm.querySelector('input[name*="[label]"]');
            const textInput = arm.querySelector('input[name*="[question_text]"]');
            if (labelInput) labelInput.name = `arms[${i}][label]`;
            if (textInput) textInput.name = `arms[${i}][question_text]`;

            // Update option field names
            const optionInputs = arm.querySelectorAll('.option-row input');
            optionInputs.forEach((opt, j) => {
                opt.name = `arms[${i}][options][${j}]`;
                opt.placeholder = 'Option ' + (j + 1);
            });

            // Show/hide remove buttons
            const removeBtn = arm.querySelector('.remove-arm-btn');
            if (removeBtn) {
                removeBtn.style.display = arms.length > 2 ? '' : 'none';
            }
        });
    }

    function reindexMembers() {
        const members = membersContainer.querySelectorAll('.member-row');
        members.forEach((row, i) => {
            const nameInput = row.querySelector('input[name*="[name]"]');
            const sisInput = row.querySelector('input[name*="[sis_code]"]');
            if (nameInput) nameInput.name = `members[${i}][name]`;
            if (sisInput) sisInput.name = `members[${i}][sis_code]`;

            // Show/hide remove buttons
            const removeBtn = row.querySelector('.remove-member-btn');
            if (removeBtn) {
                removeBtn.style.display = members.length > 1 ? '' : 'none';
            }
        });
    }

    // Add arm
    document.getElementById('add-arm-btn').addEventListener('click', function() {
        const armCount = armsContainer.querySelectorAll('.arm-block').length;
        if (armCount >= 4) {
            alert('Maximum 4 arms allowed.');
            return;
        }

        const isMultipleChoice = questionTypeSelect.value === 'multiple_choice';
        const i = armCount;

        const html = `
        <div class="arm-block border rounded p-3 mb-3" data-arm-index="${i}">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h6 class="mb-0">Arm ${i + 1}</h6>
                <button type="button" class="btn btn-sm btn-outline-danger remove-arm-btn">Remove</button>
            </div>
            <div class="row g-2 mb-2">
                <div class="col-md-3">
                    <input type="text" class="form-control" name="arms[${i}][label]"
                           placeholder="e.g., Treatment B" required>
                </div>
                <div class="col-md-9">
                    <input type="text" class="form-control" name="arms[${i}][question_text]"
                           placeholder="Question text for this arm" required>
                </div>
            </div>
            <div class="options-section" ${isMultipleChoice ? '' : 'style="display:none"'}>
                <label class="form-label text-muted small">Answer Options:</label>
                <div class="options-container">
                    <div class="input-group mb-1 option-row">
                        <input type="text" class="form-control form-control-sm"
                               name="arms[${i}][options][0]" placeholder="Option 1">
                        <button type="button" class="btn btn-sm btn-outline-danger remove-option-btn" style="display:none">x</button>
                    </div>
                    <div class="input-group mb-1 option-row">
                        <input type="text" class="form-control form-control-sm"
                               name="arms[${i}][options][1]" placeholder="Option 2">
                        <button type="button" class="btn btn-sm btn-outline-danger remove-option-btn" style="display:none">x</button>
                    </div>
                </div>
                <button type="button" class="btn btn-sm btn-outline-secondary add-option-btn mt-1">+ Add Option</button>
            </div>
        </div>`;

        armsContainer.insertAdjacentHTML('beforeend', html);
        reindexArms();
    });

    // Remove arm
    armsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-arm-btn')) {
            const armBlock = e.target.closest('.arm-block');
            if (armsContainer.querySelectorAll('.arm-block').length > 2) {
                armBlock.remove();
                reindexArms();
            }
        }
    });

    // Add option
    armsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('add-option-btn')) {
            const optionsContainer = e.target.previousElementSibling;
            const armBlock = e.target.closest('.arm-block');
            const armIndex = armBlock.dataset.armIndex;
            const optCount = optionsContainer.querySelectorAll('.option-row').length;

            if (optCount >= 5) {
                alert('Maximum 5 options per arm.');
                return;
            }

            const html = `
            <div class="input-group mb-1 option-row">
                <input type="text" class="form-control form-control-sm"
                       name="arms[${armIndex}][options][${optCount}]" placeholder="Option ${optCount + 1}">
                <button type="button" class="btn btn-sm btn-outline-danger remove-option-btn">x</button>
            </div>`;

            optionsContainer.insertAdjacentHTML('beforeend', html);

            // Show all remove buttons if > 2
            const rows = optionsContainer.querySelectorAll('.option-row');
            rows.forEach(row => {
                const btn = row.querySelector('.remove-option-btn');
                btn.style.display = rows.length > 2 ? '' : 'none';
            });
        }
    });

    // Remove option
    armsContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-option-btn')) {
            const optionRow = e.target.closest('.option-row');
            const container = optionRow.parentElement;

            if (container.querySelectorAll('.option-row').length > 2) {
                optionRow.remove();
                // Reindex options
                const armBlock = container.closest('.arm-block');
                const armIndex = armBlock.dataset.armIndex;
                const rows = container.querySelectorAll('.option-row');
                rows.forEach((row, j) => {
                    const input = row.querySelector('input');
                    input.name = `arms[${armIndex}][options][${j}]`;
                    input.placeholder = 'Option ' + (j + 1);
                    const btn = row.querySelector('.remove-option-btn');
                    btn.style.display = rows.length > 2 ? '' : 'none';
                });
            }
        }
    });

    // Toggle options visibility based on question type
    questionTypeSelect.addEventListener('change', function() {
        const show = this.value === 'multiple_choice';
        document.querySelectorAll('.options-section').forEach(section => {
            section.style.display = show ? '' : 'none';
        });
    });

    // Add member
    document.getElementById('add-member-btn').addEventListener('click', function() {
        const memberCount = membersContainer.querySelectorAll('.member-row').length;
        const i = memberCount;

        const html = `
        <div class="row g-2 mb-2 member-row">
            <div class="col-md-5">
                <input type="text" class="form-control" name="members[${i}][name]"
                       placeholder="Student Name" required>
            </div>
            <div class="col-md-5">
                <input type="text" class="form-control" name="members[${i}][sis_code]"
                       placeholder="SIS Code" required>
            </div>
            <div class="col-md-2">
                <button type="button" class="btn btn-outline-danger remove-member-btn">Remove</button>
            </div>
        </div>`;

        membersContainer.insertAdjacentHTML('beforeend', html);
        reindexMembers();
    });

    // Remove member
    membersContainer.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-member-btn')) {
            const memberRow = e.target.closest('.member-row');
            if (membersContainer.querySelectorAll('.member-row').length > 1) {
                memberRow.remove();
                reindexMembers();
            }
        }
    });
});
