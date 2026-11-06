const familyForm = document.getElementById('family-form');
const familyEntry = document.getElementById('family-entry');
const familyTableBody = document.getElementById('family-table-body');
const familyFormMessage = document.getElementById('family-form-message');
const familyListMessage = document.getElementById('family-list-message');
const familySubmitButton = document.getElementById('family-submit-button');
const familyCancelEdit = document.getElementById('family-cancel-edit');
const familySubmitRegistry = document.getElementById('family-submit-registry');
const familyRegistryState = document.getElementById('family-registry-state');
const familyExecutiveSection = document.getElementById('family-executive-section');
const familyExecutiveTableBody = document.getElementById('family-executive-table-body');
const familyExecutiveMessage = document.getElementById('family-executive-message');
const familyExecutiveMemberSelect = document.getElementById('family-executive-member-select');
let editingRelativeId = null;
let adminTargetMemberId = null;
let familyRecords = [];
let currentRegistry = { submitted: false, relatives: [] };
let currentRole = 'Member';
let executiveRegistries = [];

function isChairperson() {
    return currentRole.toLowerCase() === 'chairperson';
}

function setFamilyMessage(element, text, isError = false) {
    if (!element) return;
    element.textContent = text;
    element.classList.toggle('family-message-error', isError);
}

function createFamilyCell(text) {
    const cell = document.createElement('td');
    cell.textContent = text || '—';
    return cell;
}

function createActionButton(label, action, id, memberId, cssClass = 'family-secondary-button') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = cssClass;
    button.dataset.action = action;
    if (id !== null && id !== undefined) button.dataset.id = id;
    if (memberId) button.dataset.memberId = memberId;
    button.textContent = label;
    return button;
}

function setRegistryState() {
    const isSubmitted = Boolean(currentRegistry.submitted);
    if (familyRegistryState) {
        if (isSubmitted) {
            const submittedDate = currentRegistry.submission?.submitted_at
                ? new Date(currentRegistry.submission.submitted_at).toLocaleDateString()
                : 'date unavailable';
            const reviewed = currentRegistry.submission?.reviewed_at
                ? ` Reviewed by the Chairperson on ${new Date(currentRegistry.submission.reviewed_at).toLocaleDateString()}.`
                : ' Awaiting Chairperson review.';
            familyRegistryState.textContent =
                `Submitted on ${submittedDate}. Your registry is now view-only.${reviewed}`;
        } else {
            familyRegistryState.textContent =
                'This registry is still a draft. Add your relatives, verify the details, then submit it to lock it for review.';
        }
    }

    if (familyEntry) familyEntry.hidden = isSubmitted;
    if (familySubmitRegistry) {
        familySubmitRegistry.hidden = isSubmitted || currentRegistry.relatives.length === 0;
    }
}

function renderFamilyRecords(records) {
    if (!familyTableBody) return;
    familyRecords = records;
    familyTableBody.replaceChildren();
    if (records.length === 0) {
        const row = document.createElement('tr');
        const cell = createFamilyCell('No family records have been added yet.');
        cell.colSpan = 6;
        cell.classList.add('family-empty-state');
        row.appendChild(cell);
        familyTableBody.appendChild(row);
        return;
    }

    records.forEach(relative => {
        const row = document.createElement('tr');
        row.append(
            createFamilyCell(relative.relationship_type),
            createFamilyCell(relative.full_legal_name),
            createFamilyCell(relative.primary_contact),
            createFamilyCell(relative.vital_status),
            createFamilyCell(relative.created_at ? new Date(relative.created_at).toLocaleDateString() : '—')
        );
        const actions = document.createElement('td');
        actions.classList.add('family-row-actions');
        if (!currentRegistry.submitted) {
            actions.append(
                createActionButton('Edit', 'edit', relative.id),
                createActionButton('Delete', 'delete', relative.id, null, 'family-delete-button')
            );
        } else {
            actions.textContent = 'View only';
        }
        row.appendChild(actions);
        familyTableBody.appendChild(row);
    });
}

function renderExecutiveRegistries(registries) {
    if (!familyExecutiveTableBody) return;
    executiveRegistries = registries;
    if (familyExecutiveMemberSelect) {
        const selectedMemberId = familyExecutiveMemberSelect.value;
        familyExecutiveMemberSelect.replaceChildren();
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = registries.length
            ? 'Choose a member to review'
            : 'No member registries are available';
        familyExecutiveMemberSelect.appendChild(placeholder);
        registries.forEach(registry => {
            const option = document.createElement('option');
            option.value = registry.member_id;
            option.textContent = `${registry.member_name} (${registry.member_id})`;
            familyExecutiveMemberSelect.appendChild(option);
        });
        familyExecutiveMemberSelect.value = registries.some(
            registry => registry.member_id === selectedMemberId
        ) ? selectedMemberId : '';
    }

    familyExecutiveTableBody.replaceChildren();
    const selectedMemberId = familyExecutiveMemberSelect?.value || '';
    if (!selectedMemberId) {
        const row = document.createElement('tr');
        const cell = createFamilyCell(
            registries.length
                ? 'Select a member above to review their registry.'
                : 'No member registries are available.'
        );
        cell.colSpan = 7;
        cell.classList.add('family-empty-state');
        row.appendChild(cell);
        familyExecutiveTableBody.appendChild(row);
        return;
    }

    const registry = registries.find(item => item.member_id === selectedMemberId);
    if (!registry) return;

    const heading = document.createElement('tr');
    const memberCell = document.createElement('td');
    memberCell.colSpan = 7;
    memberCell.classList.add('family-registry-heading');
    memberCell.append(
        document.createTextNode(`${registry.member_name} (${registry.member_id})`),
        document.createTextNode(
            registry.submitted
                ? ` · Submitted ${new Date(registry.submitted_at).toLocaleDateString()}`
                : ' · Draft'
        )
    );
    if (isChairperson()) {
        memberCell.appendChild(
            createActionButton('Add Relative', 'admin-add', null, registry.member_id)
        );
        if (registry.submitted && !registry.reviewed_at) {
            memberCell.appendChild(
                createActionButton('Mark Reviewed', 'review', null, registry.member_id)
            );
        }
    }
    heading.appendChild(memberCell);
    familyExecutiveTableBody.appendChild(heading);

    if (!registry.relatives.length) {
        const row = document.createElement('tr');
        const cell = createFamilyCell('No relatives entered.');
        cell.colSpan = 7;
        row.appendChild(cell);
        familyExecutiveTableBody.appendChild(row);
        return;
    }
    registry.relatives.forEach(relative => {
        const row = document.createElement('tr');
        row.append(
            createFamilyCell(''),
            createFamilyCell(relative.relationship_type),
            createFamilyCell(relative.full_legal_name),
            createFamilyCell(relative.primary_contact),
            createFamilyCell(relative.vital_status),
            createFamilyCell(registry.reviewed_at
                ? `Reviewed ${new Date(registry.reviewed_at).toLocaleDateString()}`
                : registry.submitted ? 'Awaiting review' : 'Draft'),
        );
        const actions = document.createElement('td');
        if (isChairperson()) {
            actions.classList.add('family-row-actions');
            actions.appendChild(
                createActionButton('Edit', 'admin-edit', relative.id, registry.member_id)
            );
        } else {
            actions.textContent = 'View only';
        }
        row.appendChild(actions);
        familyExecutiveTableBody.appendChild(row);
    });
}

familyExecutiveMemberSelect?.addEventListener('change', () => {
    renderExecutiveRegistries(executiveRegistries);
});

async function loadExecutiveRegistries() {
    try {
        const response = await fetch('/api/family/executive/registries', {
            credentials: 'include'
        });
        const result = await readApiJson(response, 'Could not load executive registries. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not load executive registries.');
        renderExecutiveRegistries(result.data || []);
    } catch (error) {
        setFamilyMessage(familyExecutiveMessage, error.message || 'A network error occurred.', true);
        console.error('Error loading executive family registries:', error);
    }
}

async function loadFamilyRecords() {
    if (!familyTableBody) return;
    setFamilyMessage(familyListMessage, '');
    try {
        const response = await fetch('/api/family/relatives', { credentials: 'include' });
        const result = await readApiJson(response, 'Could not load family records. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not load family records.');
        const data = result.data || {};
        currentRegistry = data;
        currentRole = data.role || 'Member';
        familyExecutiveSection.hidden = ![
            'chairperson', 'treasurer', 'secretary', 'welfare', 'welfare officer'
        ].includes(currentRole.toLowerCase());
        setRegistryState();
        renderFamilyRecords(data.relatives || []);
        if (!familyExecutiveSection.hidden) await loadExecutiveRegistries();
    } catch (error) {
        setFamilyMessage(familyListMessage, error.message || 'A network error occurred.', true);
        familyTableBody.replaceChildren();
        console.error('Error loading family records:', error);
    }
}

function resetFamilyForm() {
    if (!familyForm) return;
    familyForm.reset();
    editingRelativeId = null;
    adminTargetMemberId = null;
    if (familySubmitButton) familySubmitButton.textContent = 'Add Relative';
    if (familyCancelEdit) familyCancelEdit.hidden = true;
    const heading = document.getElementById('family-form-heading');
    if (heading) heading.textContent = 'Add a Relative';
    const vitalStatus = document.getElementById('vital-status');
    if (vitalStatus) vitalStatus.disabled = true;
    if (familyEntry) familyEntry.hidden = Boolean(currentRegistry.submitted);
    setFamilyMessage(familyFormMessage, '');
}

function openAdminForm(memberId, relative = null) {
    adminTargetMemberId = memberId;
    editingRelativeId = relative ? Number(relative.id) : null;
    familyEntry.hidden = false;
    document.getElementById('relationship-type').value = relative?.relationship_type || '';
    document.getElementById('full-legal-name').value = relative?.full_legal_name || '';
    document.getElementById('primary-contact').value = relative?.primary_contact || '';
    const vitalStatus = document.getElementById('vital-status');
    vitalStatus.disabled = false;
    vitalStatus.value = relative?.vital_status || 'Alive';
    if (familySubmitButton) familySubmitButton.textContent = editingRelativeId
        ? 'Save Chairperson Changes'
        : 'Add Relative';
    if (familyCancelEdit) familyCancelEdit.hidden = false;
    const heading = document.getElementById('family-form-heading');
    if (heading) heading.textContent = `Chairperson Review: ${memberId}`;
    familyForm?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

familyForm?.addEventListener('submit', async event => {
    event.preventDefault();
    setFamilyMessage(familyFormMessage, '');
    const field = id => document.getElementById(id);
    const relationship = field('relationship-type');
    const fullName = field('full-legal-name');
    const contact = field('primary-contact');
    const vitalStatus = field('vital-status');
    if (!relationship || !fullName || !contact || !vitalStatus) return;

    const payload = {
        relationship_type: relationship.value.trim(),
        full_legal_name: fullName.value.trim(),
        primary_contact: contact.value.trim(),
        vital_status: vitalStatus.value
    };
    let url = '/api/family/relatives';
    let method = editingRelativeId ? 'PUT' : 'POST';
    if (adminTargetMemberId) {
        url = editingRelativeId
            ? `/api/family/executive/relatives/${encodeURIComponent(editingRelativeId)}`
            : `/api/family/executive/registries/${encodeURIComponent(adminTargetMemberId)}/relatives`;
        method = editingRelativeId ? 'PUT' : 'POST';
    } else if (editingRelativeId) {
        url = `/api/family/relatives/${encodeURIComponent(editingRelativeId)}`;
    }

    try {
        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify(payload)
        });
        const result = await readApiJson(response, 'Could not save this family record. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not save this family record.');
        resetFamilyForm();
        setFamilyMessage(familyFormMessage, 'Family record saved.');
        await loadFamilyRecords();
    } catch (error) {
        setFamilyMessage(familyFormMessage, error.message || 'A network error occurred.', true);
    }
});

familySubmitRegistry?.addEventListener('click', async () => {
    if (!window.confirm('Submit this registry? After submission, only the Chairperson can edit it.')) {
        return;
    }
    try {
        const response = await fetch('/api/family/submit', {
            method: 'POST',
            credentials: 'include'
        });
        const result = await readApiJson(response, 'Could not submit the registry. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not submit the registry.');
        setFamilyMessage(familyListMessage, 'Registry submitted for Chairperson review.');
        await loadFamilyRecords();
    } catch (error) {
        setFamilyMessage(familyListMessage, error.message || 'A network error occurred.', true);
    }
});

familyCancelEdit?.addEventListener('click', resetFamilyForm);

familyTableBody?.addEventListener('click', async event => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const relativeId = Number(button.dataset.id);
    const relative = familyRecords.find(record => Number(record.id) === relativeId);
    if (!relative) return;

    if (button.dataset.action === 'edit') {
        editingRelativeId = relativeId;
        document.getElementById('relationship-type').value = relative.relationship_type || '';
        document.getElementById('full-legal-name').value = relative.full_legal_name || '';
        document.getElementById('primary-contact').value = relative.primary_contact || '';
        const vitalStatus = document.getElementById('vital-status');
        vitalStatus.value = relative.vital_status || 'Alive';
        vitalStatus.disabled = true;
        if (familySubmitButton) familySubmitButton.textContent = 'Save Changes';
        if (familyCancelEdit) familyCancelEdit.hidden = false;
        const heading = document.getElementById('family-form-heading');
        if (heading) heading.textContent = 'Edit Relative';
        familyForm?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
    }

    if (!window.confirm(`Delete the family record for ${relative.full_legal_name}?`)) return;
    try {
        const response = await fetch(`/api/family/relatives/${encodeURIComponent(relativeId)}`, {
            method: 'DELETE',
            credentials: 'include'
        });
        const result = await readApiJson(response, 'Could not delete this family record. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not delete this family record.');
        setFamilyMessage(familyListMessage, result.message);
        await loadFamilyRecords();
    } catch (error) {
        setFamilyMessage(familyListMessage, error.message || 'A network error occurred.', true);
    }
});

familyExecutiveTableBody?.addEventListener('click', async event => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    const memberId = button.dataset.memberId;
    if (action === 'admin-add') {
        openAdminForm(memberId);
        return;
    }
    if (action === 'admin-edit') {
        const registry = executiveRegistries.find(item => item.member_id === memberId);
        const relative = registry?.relatives.find(item => Number(item.id) === Number(button.dataset.id));
        if (relative) openAdminForm(memberId, relative);
        return;
    }
    if (action === 'review') {
        try {
            const response = await fetch(
                `/api/family/executive/registries/${encodeURIComponent(memberId)}/review`,
                { method: 'POST', credentials: 'include' }
            );
            const result = await readApiJson(response, 'Could not mark the registry reviewed. Please try again.');
            if (!response.ok) throw new Error(result.detail || 'Could not mark registry reviewed.');
            setFamilyMessage(familyExecutiveMessage, 'Registry marked as reviewed.');
            await loadFamilyRecords();
        } catch (error) {
            setFamilyMessage(familyExecutiveMessage, error.message || 'A network error occurred.', true);
        }
    }
});

loadFamilyRecords();
