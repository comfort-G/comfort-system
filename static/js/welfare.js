document.querySelector('.welfare-hero-action')?.addEventListener('click', () => {
    const claimForm = document.getElementById('welfare-claim');
    if (claimForm instanceof HTMLDetailsElement) claimForm.open = true;
});

function setWelfareMessage(id, text, isError = false) {
    const element = document.getElementById(id);
    if (!element) return;
    element.style.color = isError ? '#e74c3c' : '#27ae60';
    element.textContent = text;
}

function appendEmptyRow(body, colspan, text) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = colspan;
    cell.style.textAlign = 'center';
    cell.textContent = text;
    row.appendChild(cell);
    body.replaceChildren(row);
}

async function loadWelfareDashboard() {
    const claimsBody = document.getElementById('my-claims-body');
    if (!claimsBody) return;
    try {
        const response = await fetch('/api/welfare/my-claims', { credentials: 'include' });
        const result = await readApiJson(response, 'Could not load welfare claims. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not load your welfare claims.');
        const claims = result.data?.claims_history || [];
        claimsBody.replaceChildren();
        if (claims.length === 0) {
            appendEmptyRow(claimsBody, 8, 'No welfare claims submitted yet.');
        } else {
            claims.forEach(claim => {
                const row = document.createElement('tr');
                const caseCell = document.createElement('td');
                const strong = document.createElement('strong');
                strong.textContent = claim.case_number || '';
                caseCell.appendChild(strong);
                const category = document.createElement('td');
                category.textContent = claim.support_category || '';
                const beneficiary = document.createElement('td');
                beneficiary.textContent = [
                    claim.beneficiary_relationship,
                    claim.beneficiary_name
                ].filter(Boolean).join(' · ') || 'Not recorded (legacy claim)';
                const description = document.createElement('td');
                description.textContent = (claim.description || '').substring(0, 80);
                const stage = document.createElement('td');
                stage.textContent = claim.current_stage || 'Submitted';
                const status = document.createElement('td');
                const badge = document.createElement('span');
                badge.className = ['Approved', 'Paid'].includes(claim.status)
                    ? 'badge-approved' : claim.status === 'Rejected' ? 'badge-rejected' : 'badge-pending';
                badge.textContent = claim.status || '';
                status.appendChild(badge);
                const disbursed = document.createElement('td');
                disbursed.textContent = claim.disbursed_amount == null
                    ? '-'
                    : `UGX ${Number(claim.disbursed_amount).toLocaleString()}`;
                const date = document.createElement('td');
                date.textContent = claim.created_at ? claim.created_at.substring(0, 10) : 'N/A';
                row.append(caseCell, category, beneficiary, description, stage, status, disbursed, date);
                claimsBody.appendChild(row);
            });
        }
    } catch (error) {
        setWelfareMessage('message', error.message || 'Could not load your welfare claims.', true);
        console.error('Error loading welfare claims:', error);
    }

}

async function loadEligibleBeneficiaries() {
    const category = document.getElementById('support-category');
    const select = document.getElementById('beneficiary-id');
    const guidance = document.getElementById('beneficiary-guidance');
    const eligibilityGuidance = document.getElementById('welfare-eligibility-guidance');
    const submitButton = document.getElementById('submit-welfare-claim');
    if (!category || !select || !guidance || !eligibilityGuidance || !submitButton) return;

    const selectedCategory = category.value;
    select.replaceChildren();
    select.disabled = true;
    submitButton.disabled = true;
    if (!selectedCategory) {
        select.add(new Option('Choose an event first', ''));
        guidance.textContent = 'Choose an event to see who is eligible.';
        eligibilityGuidance.textContent = 'Eligibility is checked when you choose a support event.';
        return;
    }

    select.add(new Option('Loading eligible people...', ''));
    guidance.textContent = 'Loading eligible people from your Family Registry...';
    eligibilityGuidance.textContent = 'Checking membership status and welfare balance...';
    try {
        const response = await fetch(
            `/api/welfare/eligible-beneficiaries?support_category=${encodeURIComponent(selectedCategory)}`,
            { credentials: 'include' }
        );
        const result = await readApiJson(response, 'Could not load eligible beneficiaries. Please try again.');
        if (!response.ok) {
            throw new Error(result.detail || 'Could not load eligible people.');
        }
        if (category.value !== selectedCategory) return;

        const beneficiaries = result.data?.beneficiaries || [];
        const eligibility = result.data || {};
        if (!eligibility.eligible) {
            eligibilityGuidance.textContent = (eligibility.reasons || []).join(' ');
            select.replaceChildren(new Option('Not eligible to apply', ''));
            guidance.textContent = 'You must meet the welfare application requirements before submitting a claim.';
            return;
        }
        eligibilityGuidance.textContent = `Eligible to apply · Welfare balance: UGX ${Number(eligibility.welfare_balance).toLocaleString()}.`;
        select.replaceChildren(new Option('Select the person', ''));
        beneficiaries.forEach(beneficiary => {
            const label = beneficiary.is_self
                ? `${beneficiary.full_legal_name} (Member)`
                : `${beneficiary.full_legal_name} (${beneficiary.relationship_type})`;
            select.add(new Option(label, String(beneficiary.id)));
        });
        select.disabled = beneficiaries.length === 0;
        submitButton.disabled = beneficiaries.length === 0;
        guidance.textContent = selectedCategory === 'Wedding'
            || selectedCategory === 'Traditional Introduction'
            ? 'Wedding and traditional introduction support is for the member only.'
            : selectedCategory === 'Illness'
                ? 'Illness support covers the member, or a registered spouse or child marked Alive.'
                : 'Death support covers the member, or a registered spouse, child, parent, or parent-in-law marked Alive.';
        if (beneficiaries.length === 0) {
            guidance.textContent = 'No eligible person was returned. Refresh the page and try again; contact support if this continues.';
            setWelfareMessage('message', guidance.textContent, true);
        }
    } catch (error) {
        select.replaceChildren(new Option('Could not load eligible people', ''));
        guidance.textContent = error.message || 'Could not load eligible people.';
        eligibilityGuidance.textContent = error.message || 'Could not check welfare application eligibility.';
        submitButton.disabled = true;
        setWelfareMessage('message', guidance.textContent, true);
        console.error('Error loading welfare beneficiaries:', error);
    }
}

document.getElementById('support-category')
    ?.addEventListener('change', loadEligibleBeneficiaries);

document.getElementById('welfare-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const category = document.getElementById('support-category');
    const beneficiary = document.getElementById('beneficiary-id');
    const description = document.getElementById('description');
    const evidence = document.getElementById('evidence-url');
    if (!category || !beneficiary || !description || !evidence) return;
    if (!beneficiary.value) {
        setWelfareMessage('message', 'Choose an eligible person for this claim.', true);
        beneficiary.focus();
        return;
    }
    try {
        const response = await fetch('/api/welfare/claim', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                support_category: category.value,
                beneficiary_id: beneficiary.value,
                description: description.value.trim(),
                evidence_file_url: evidence.value.trim()
            })
        });
        const result = await readApiJson(response, 'Could not submit the welfare claim. Please try again.');
        setWelfareMessage('message', response.ok ? result.message : result.detail || 'Submission failed.', !response.ok);
        if (response.ok) {
            document.getElementById('welfare-form').reset();
            await loadEligibleBeneficiaries();
            await loadWelfareDashboard();
        }
    } catch (error) {
        setWelfareMessage(
            'message',
            error.message || 'Could not submit the welfare claim. Please try again.',
            true
        );
        console.error('Error submitting welfare claim:', error);
    }
});

loadWelfareDashboard();
