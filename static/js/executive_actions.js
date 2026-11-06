(() => {
    const currencyFormat = new Intl.NumberFormat('en-UG', {
        maximumFractionDigits: 2
    });
    let memberFinanceAccounts = [];
    let manualSubscriptionPreview = null;
    let latestEmergencyAction = null;

    function setMessage(id, text, isError = false) {
        const element = document.getElementById(id);
        if (!element) return;
        element.textContent = text || '';
        element.classList.toggle('is-error', isError);
        element.classList.toggle('is-success', Boolean(text) && !isError);
    }

    function createCell(text, className = '') {
        const cell = document.createElement('td');
        cell.textContent = text == null ? '' : String(text);
        if (className) cell.className = className;
        return cell;
    }

    function createMemberStatusIndicator(value) {
        const statusText = value == null || value === '' ? 'Not recorded' : String(value);
        const normalizedStatus = statusText.toLowerCase();
        const statusClass = normalizedStatus.includes('inactive')
            || normalizedStatus.includes('suspend')
            ? 'is-inactive'
            : normalizedStatus.includes('active') ? 'is-active' : 'is-unknown';
        const indicator = document.createElement('span');
        indicator.className = `member-status-indicator ${statusClass}`;
        const dot = document.createElement('span');
        dot.className = 'member-status-indicator-dot';
        dot.setAttribute('aria-hidden', 'true');
        indicator.append(dot, document.createTextNode(statusText));
        return indicator;
    }

    function appendEmptyRow(body, colspan, text) {
        const row = document.createElement('tr');
        row.append(createCell(text, 'empty-cell'));
        row.firstElementChild.colSpan = colspan;
        body.replaceChildren(row);
    }

    async function requestJson(url, options = {}) {
        const response = await fetch(url, {
            credentials: 'include',
            ...options
        });
        return await readApiJson(response, 'The request failed. Please try again.');
    }

    async function submitMemberGenerator(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const button = document.getElementById('member-generator-submit');
        if (!(form instanceof HTMLFormElement) || !(button instanceof HTMLButtonElement)) return;

        const formData = new FormData(form);
        const payload = Object.fromEntries(formData.entries());
        payload.member_id = String(payload.member_id || '').trim();
        payload.full_name = String(payload.full_name || '').trim();
        payload.email = String(payload.email || '').trim();
        payload.phone_number = String(payload.phone_number || '').trim();
        button.disabled = true;

        try {
            const result = await requestJson('/api/admin/create-member', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            window.alert(result.message || 'Member account saved successfully.');
            form.reset();
        } catch (error) {
            window.alert(error instanceof Error ? error.message : 'Could not save the member account.');
            console.error('Unable to save member account:', error);
        } finally {
            button.disabled = false;
        }
    }

    function renderEmergencyAction(action) {
        const container = document.getElementById('emergency-reversal-action');
        const form = document.getElementById('emergency-reversal-form');
        if (!container || !form) return;
        container.replaceChildren();
        form.hidden = true;
        latestEmergencyAction = action || null;

        if (!action) {
            const empty = document.createElement('p');
            empty.textContent = 'No eligible loan approval or welfare disbursement is recorded.';
            container.appendChild(empty);
            return;
        }

        const summary = document.createElement('div');
        summary.className = 'emergency-reversal-summary';
        const heading = document.createElement('h3');
        heading.textContent = `${action.action_label} · ${action.action_type === 'loan_approval' ? `Loan #${action.action_id}` : `Case ${action.case_number || action.action_id}`}`;
        const details = document.createElement('p');
        const amountLabel = action.action_type === 'loan_approval'
            ? 'principal'
            : 'disbursed amount';
        const dateLabel = action.occurred_at
            ? new Date(action.occurred_at).toLocaleString('en-UG')
            : 'time unavailable';
        details.textContent = `${action.full_name || 'Member'} (${action.member_id}) · ${amountLabel}: ${formatAmount(action.amount)} · Recorded: ${dateLabel}`;
        summary.append(heading, details);
        container.appendChild(summary);

        const state = document.createElement('p');
        state.className = action.can_reverse
            ? 'emergency-reversal-available'
            : 'emergency-reversal-blocked';
        state.textContent = action.can_reverse
            ? 'This is the latest action and is within the 24-hour reversal window.'
            : action.blocked_reason || 'This action cannot be reversed.';
        container.appendChild(state);
        if (action.can_reverse) {
            form.dataset.actionType = action.action_type;
            form.dataset.actionId = String(action.action_id);
            form.hidden = false;
        }
    }

    async function loadLatestEmergencyAction() {
        const container = document.getElementById('emergency-reversal-action');
        if (!container) return;
        try {
            const result = await requestJson(
                '/api/executive-actions/emergency-reversal/latest'
            );
            renderEmergencyAction(result.data);
        } catch (error) {
            latestEmergencyAction = null;
            const form = document.getElementById('emergency-reversal-form');
            if (form) form.hidden = true;
            container.textContent = `Could not check the latest financial action: ${error.message}`;
            setMessage('emergency-reversal-message', error.message, true);
            console.error('Unable to load latest emergency reversal action:', error);
        }
    }

    async function submitEmergencyReversal(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const reason = document.getElementById('emergency-reversal-reason');
        const fundsReceived = document.getElementById('emergency-reversal-funds-received');
        const button = document.getElementById('emergency-reversal-submit');
        if (!reason || !fundsReceived || !button || !latestEmergencyAction?.can_reverse) return;
        if (!reason.value.trim()) {
            reason.setCustomValidity('Enter the reason for this reversal.');
            reason.reportValidity();
            return;
        }
        reason.setCustomValidity('');
        if (!fundsReceived.checked) {
            fundsReceived.reportValidity();
            return;
        }
        const confirmed = window.confirm(
            `Confirm that ${formatAmount(latestEmergencyAction.amount)} has physically been returned to the group account and reverse this latest action?`
        );
        if (!confirmed) return;

        button.disabled = true;
        setMessage('emergency-reversal-message', 'Recording audited reversal...');
        const actionType = form.dataset.actionType;
        const actionId = form.dataset.actionId;
        try {
            const result = await requestJson(
                `/api/executive-actions/emergency-reversal/${encodeURIComponent(actionType)}/${encodeURIComponent(actionId)}`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        reason: reason.value.trim(),
                        funds_received: fundsReceived.checked
                    })
                }
            );
            setMessage('emergency-reversal-message', result.message);
            form.reset();
            await Promise.all([
                loadLatestEmergencyAction(),
                loadLoanQueue(),
                loadWelfareQueue()
            ]);
        } catch (error) {
            setMessage('emergency-reversal-message', error.message, true);
            await loadLatestEmergencyAction();
            console.error('Unable to reverse latest financial action:', error);
        } finally {
            button.disabled = false;
        }
    }

    function formatAmount(value) {
        return `UGX ${currencyFormat.format(Number(value) || 0)}`;
    }

    function formatBillingMonth(value) {
        return new Date(`${value}T00:00:00`).toLocaleDateString('en-GB', {
            month: 'long',
            year: 'numeric'
        });
    }

    function renderAllocationList(container, allocations) {
        const list = document.createElement('ul');
        allocations.forEach(allocation => {
            const item = document.createElement('li');
            item.textContent = `${formatBillingMonth(allocation.billing_month)} — ${formatAmount(allocation.amount)}`;
            list.appendChild(item);
        });
        container.appendChild(list);
    }

    function setProofMessageWithManualOption(message, proof, amount) {
        const element = document.getElementById('proof-message');
        if (!element) return;
        element.replaceChildren();
        element.append(document.createTextNode(message));

        const page = document.querySelector('.executive-actions-page');
        if (page?.dataset.canManageMemberFinances === 'true') {
            element.append(document.createTextNode(' You may ask the member to upload a corrected proof, or record the verified transaction manually: '));
            const link = document.createElement('a');
            const url = new URL('/api/executive-actions/view', window.location.origin);
            url.searchParams.set('manual_member_id', proof.member_id);
            if (Number.isFinite(amount) && amount > 0) {
                url.searchParams.set('manual_amount', String(amount));
            }
            url.hash = 'manual-subscription-heading';
            link.href = url.href;
            link.className = 'proof-review-manual-link';
            link.textContent = 'Open manual subscription update';
            element.appendChild(link);
        } else {
            element.append(document.createTextNode(' Ask the member to upload a corrected proof or contact the Treasurer for a manual update.'));
        }
    }

    async function loadProofQueue() {
        const body = document.getElementById('proof-queue');
        if (!body) return;
        try {
            const result = await requestJson('/api/subscriptions/admin/pending-proofs');
            const proofs = result.data || [];
            body.replaceChildren();
            if (!proofs.length) {
                appendEmptyRow(body, 6, 'No pending subscription proofs.');
                return;
            }

            proofs.forEach(proof => {
                const row = document.createElement('tr');
                const submitted = proof.upload_timestamp
                    ? new Date(proof.upload_timestamp).toLocaleDateString('en-GB')
                    : '—';
                const amountCell = document.createElement('td');
                row.append(
                    createCell(`${proof.member_name || 'Member'} (${proof.member_id})`),
                    createCell(submitted),
                    amountCell,
                    createCell([proof.payment_method, proof.transaction_reference].filter(Boolean).join(' · ')),
                );
                const amount = document.createElement('input');
                amount.type = 'number';
                amount.min = '0.01';
                amount.step = '0.01';
                amount.className = 'proof-amount';
                amount.placeholder = 'Read from SMS';
                amount.setAttribute('aria-label', `Verified transaction amount for ${proof.member_name || proof.member_id}`);
                amountCell.appendChild(amount);
                const evidenceCell = document.createElement('td');
                const evidenceUrl = String(proof.cloudinary_file_url || '');
                try {
                    const parsed = new URL(evidenceUrl, window.location.origin);
                    if (['http:', 'https:'].includes(parsed.protocol)) {
                        const link = document.createElement('a');
                        link.href = parsed.href;
                        link.target = '_blank';
                        link.rel = 'noopener noreferrer';
                        link.className = 'evidence-link';
                        link.textContent = 'Open proof';
                        evidenceCell.appendChild(link);
                    } else {
                        evidenceCell.textContent = 'No valid proof link';
                    }
                } catch {
                    evidenceCell.textContent = 'No valid proof link';
                }
                row.appendChild(evidenceCell);

                const actionsCell = document.createElement('td');
                const reviewControls = document.createElement('div');
                reviewControls.className = 'proof-review-controls';
                const comment = document.createElement('input');
                comment.className = 'proof-comment';
                comment.maxLength = 500;
                comment.placeholder = 'Optional review note';
                const actions = document.createElement('div');
                actions.className = 'row-actions';
                const previewButton = document.createElement('button');
                previewButton.type = 'button';
                previewButton.textContent = 'Preview allocation';
                previewButton.addEventListener('click', () =>
                    previewProofAllocation(proof, amount, comment, preview, previewButton)
                );
                const rejectButton = document.createElement('button');
                rejectButton.type = 'button';
                rejectButton.className = 'reject-button';
                rejectButton.textContent = 'Reject proof';
                rejectButton.addEventListener('click', () => {
                    const reason = window.prompt('Why is this payment proof being rejected?');
                    if (reason === null) return;
                    reviewProof(
                        proof,
                        'Rejected',
                        Number(amount.value),
                        [],
                        reason.trim(),
                        rejectButton
                    );
                });
                actions.append(previewButton, rejectButton);
                const preview = document.createElement('div');
                preview.className = 'proof-allocation-preview';
                preview.hidden = true;
                amount.addEventListener('input', () => {
                    preview.hidden = true;
                    preview.replaceChildren();
                });
                reviewControls.append(amount, comment, actions, preview);
                actionsCell.appendChild(reviewControls);
                row.appendChild(actionsCell);
                body.appendChild(row);
            });
        } catch (error) {
            appendEmptyRow(body, 6, 'Could not load subscription proofs.');
            setMessage('proof-message', error.message, true);
            console.error('Unable to load subscription proof queue:', error);
        }
    }

    async function previewProofAllocation(proof, amountInput, comment, preview, button) {
        const amount = Number(amountInput.value);
        if (!Number.isFinite(amount) || amount <= 0) {
            setMessage('proof-message', 'Enter the exact transaction amount shown in the proof.', true);
            amountInput.focus();
            return;
        }
        button.disabled = true;
        setMessage('proof-message', 'Checking the member ledger and preparing allocation...');
        try {
            const result = await requestJson(
                `/api/subscriptions/admin/proofs/${encodeURIComponent(proof.proof_id)}/preview`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ amount })
                }
            );
            preview.replaceChildren();
            preview.hidden = false;
            const heading = document.createElement('p');
            heading.textContent = `Carefully verify the screenshot. UGX ${currencyFormat.format(amount)} will be allocated as follows:`;
            preview.appendChild(heading);
            renderAllocationList(preview, result.allocations || []);
            const confirmButton = document.createElement('button');
            confirmButton.type = 'button';
            confirmButton.textContent = 'Confirm and post payment';
            confirmButton.addEventListener('click', () =>
                reviewProof(
                    proof,
                    'Paid',
                    amount,
                    result.allocations || [],
                    comment.value,
                    confirmButton
                )
            );
            preview.appendChild(confirmButton);
            setMessage('proof-message', 'Review the allocation above. Confirm only after matching the screenshot and SMS amount.');
        } catch (error) {
            setMessage('proof-message', error.message, true);
            console.error('Unable to preview subscription proof allocation:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function reviewProof(proof, decision, amount, allocations, comment, button) {
        button.disabled = true;
        setMessage('proof-message', 'Saving proof review...');
        const body = { decision, comment };
        if (decision === 'Paid') {
            body.amount = amount;
            body.expected_allocations = allocations;
        }
        try {
            const result = await requestJson(
                `/api/subscriptions/admin/proofs/${encodeURIComponent(proof.proof_id)}/review`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                }
            );
            if (decision === 'Rejected') {
                setProofMessageWithManualOption(
                    `${result.message} Ask the member to repeat the payment-proof upload if the screenshot or details were incorrect.`,
                    proof,
                    amount
                );
            } else {
                const allocationSummary = (result.allocations || [])
                    .map(item => `${formatBillingMonth(item.billing_month)} ${formatAmount(item.amount)}`)
                    .join('; ');
                setMessage(
                    'proof-message',
                    `${result.message} Posted: ${allocationSummary}.`
                );
            }
            await loadProofQueue();
        } catch (error) {
            setMessage('proof-message', error.message, true);
            console.error('Unable to review subscription proof:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function loadLoanQueue() {
        const body = document.getElementById('loan-queue');
        if (!body) return;
        try {
            const result = await requestJson('/api/loans/pending-review');
            const loans = result.data || [];
            const count = document.getElementById('pending-loan-count');
            if (count) {
                count.textContent = loans.length
                    ? `${loans.length} application${loans.length === 1 ? '' : 's'} awaiting executive review.`
                    : 'No applications are currently awaiting executive review.';
            }
            const table = body.closest('.table-wrap');
            const collapseButton = table?.previousElementSibling;
            if (collapseButton?.classList.contains('sheet-collapse-toggle')) {
                collapseButton.textContent =
                    `${collapseButton.dataset.collapseLabel || 'Pending loan applications'} (${loans.length} pending)`;
                collapseButton.setAttribute('aria-label', collapseButton.textContent);
            }
            body.replaceChildren();
            if (!loans.length) {
                appendEmptyRow(body, 7, 'No pending loan applications.');
                return;
            }

            loans.forEach(loan => {
                const row = document.createElement('tr');
                const amountCell = createCell(currencyFormat.format(Number(loan.amount_requested) || 0));
                const isExceeded = Boolean(loan.is_working_capital_exceeded);
                if (isExceeded) {
                    const warning = document.createElement('div');
                    warning.className = 'warning-text';
                    warning.textContent = loan.working_capital_warning || 'Warning: request exceeds available working capital.';
                    amountCell.appendChild(warning);
                }
                row.append(
                    createCell(`#${loan.id}`),
                    createCell(loan.member_id),
                    amountCell,
                    createCell(loan.mobile_money_number || '—'),
                    createCell(loan.purpose),
                    createCell(loan.created_at),
                );
                const actions = document.createElement('td');
                const buttons = document.createElement('div');
                buttons.className = 'row-actions';
                [['Approve', 'Approved', ''], ['Reject', 'Rejected', 'reject-button']].forEach(
                    ([label, decision, className]) => {
                        const button = document.createElement('button');
                        button.type = 'button';
                        button.textContent = label;
                        if (className) button.className = className;
                        if (decision === 'Approved' && isExceeded) {
                            button.disabled = true;
                            button.title = loan.working_capital_warning || 'Request exceeds available working capital.';
                        }
                        button.addEventListener('click', () => reviewLoan(loan.id, decision, button));
                        buttons.appendChild(button);
                    }
                );
                actions.appendChild(buttons);
                row.appendChild(actions);
                body.appendChild(row);
            });
        } catch (error) {
            appendEmptyRow(body, 7, 'Could not load pending loan applications.');
            setMessage('loan-message', error.message, true);
            console.error('Unable to load loan queue:', error);
        }
    }

    async function reviewLoan(loanId, decision, button) {
        let reason = '';
        if (decision === 'Rejected') {
            reason = window.prompt(
                'State the specific eligibility requirement not met or the reason for rejecting this application:'
            ) || '';
            if (!reason.trim()) {
                setMessage('loan-message', 'Enter a clear rejection reason. No decision was submitted.', true);
                return;
            }
        }
        button.disabled = true;
        try {
            const result = await requestJson(`/api/loans/${encodeURIComponent(loanId)}/review`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ decision, reason: reason.trim() })
            });
            setMessage('loan-message', result.message);
            await loadLoanQueue();
        } catch (error) {
            setMessage('loan-message', error.message, true);
            console.error('Unable to review loan:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function loadWelfareQueue() {
        const body = document.getElementById('welfare-queue');
        if (!body) return;
        const role = document.getElementById('welfare-queue-container')
            ?.dataset.welfareRole || '';
        try {
            const result = await requestJson('/api/welfare/admin/queue');
            const claims = result.data || [];
            body.replaceChildren();
            if (!claims.length) {
                appendEmptyRow(body, 8, 'No welfare requests require review.');
                return;
            }

            claims.forEach(claim => {
                const row = document.createElement('tr');
                row.append(
                    createCell(claim.case_number),
                    createCell(`${claim.member_name || ''} (${claim.member_id || ''})`),
                    createCell(claim.support_category),
                    createCell([
                        claim.beneficiary_relationship,
                        claim.beneficiary_name
                    ].filter(Boolean).join(' · ') || 'Not recorded (legacy claim)'),
                    createCell(claim.description),
                    createCell(claim.current_stage),
                    createCell(formatAmount(claim.disbursed_amount)),
                );
                const actionsCell = document.createElement('td');
                const addAction = (label, action) => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.textContent = label;
                    button.addEventListener('click', () => action(claim.id, button));
                    actionsCell.appendChild(button);
                };
                const stage = String(claim.current_stage || '');
                if (['treasurer', 'welfare', 'welfare officer'].includes(role)
                    && stage === 'Submitted') {
                    addAction('Start review', (id, button) =>
                        moderateWelfare(id, button, 'Under Review', 'Under Review'));
                }
                if (role === 'chairperson' && stage === 'Under Review') {
                    addAction('Approve', (id, button) =>
                        moderateWelfare(id, button, 'Executive Approved', 'Approved'));
                    addAction('Reject', (id, button) =>
                        moderateWelfare(id, button, 'Rejected', 'Rejected'));
                }
                if (role === 'treasurer'
                    && ['Executive Approved', 'Partially Disbursed', 'Funding Shortfall'].includes(stage)) {
                    addAction(
                        stage === 'Executive Approved' ? 'Disburse' : 'Disburse available funds',
                        disburseWelfare
                    );
                }
                if (!actionsCell.childElementCount) {
                    actionsCell.textContent = 'No action available';
                }
                row.appendChild(actionsCell);
                body.appendChild(row);
            });
        } catch (error) {
            appendEmptyRow(body, 8, 'Could not load welfare requests.');
            setMessage('welfare-message', error.message, true);
            console.error('Unable to load welfare queue:', error);
        }
    }

    async function moderateWelfare(claimId, button, stage, status) {
        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/welfare/admin/claims/${encodeURIComponent(claimId)}/moderate`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        status,
                        current_stage: stage,
                        comment: `${status} by authorized reviewer`
                    })
                }
            );
            setMessage('welfare-message', result.message);
            await loadWelfareQueue();
        } catch (error) {
            setMessage('welfare-message', error.message, true);
            console.error('Unable to moderate welfare request:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function disburseWelfare(claimId, button) {
        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/welfare/admin/claims/${encodeURIComponent(claimId)}/disburse`,
                { method: 'POST' }
            );
            setMessage('welfare-message', result.message);
            await loadWelfareQueue();
        } catch (error) {
            setMessage('welfare-message', error.message, true);
            console.error('Unable to disburse welfare request:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function loadTransferBalances() {
        const select = document.getElementById('transfer-member');
        if (!select) return;
        try {
            const result = await requestJson('/api/executive-actions/subscription-balances');
            select.replaceChildren();
            const first = document.createElement('option');
            first.value = '';
            first.textContent = 'Select a member';
            select.appendChild(first);
            (result.data || []).forEach(member => {
                const option = document.createElement('option');
                option.value = member.member_id;
                option.dataset.available = String(member.available_balance);
                option.textContent = `${member.full_name} (${member.member_id}) — ${formatAmount(member.available_balance)}`;
                select.appendChild(option);
            });
            if (select.options.length === 1) {
                first.textContent = 'No members have an available paid balance';
            }
            updateTransferAvailability();
        } catch (error) {
            select.replaceChildren();
            const option = document.createElement('option');
            option.value = '';
            option.textContent = 'Member balances could not be loaded';
            select.appendChild(option);
            setMessage('transfer-message', error.message, true);
            console.error('Unable to load transferable subscription balances:', error);
        }
    }

    function updateTransferAvailability() {
        const select = document.getElementById('transfer-member');
        const amount = document.getElementById('transfer-amount');
        const availableText = document.getElementById('transfer-available');
        if (!select || !amount || !availableText) return;
        const available = Number(select.selectedOptions[0]?.dataset.available || 0);
        amount.max = String(available);
        availableText.textContent = `Available balance: ${formatAmount(available)}`;
    }

    async function submitTransfer(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const memberId = document.getElementById('transfer-member')?.value;
        const amount = Number(document.getElementById('transfer-amount')?.value);
        if (!memberId || !Number.isFinite(amount) || amount <= 0) {
            setMessage('transfer-message', 'Select a member and enter a valid transfer amount.', true);
            return;
        }
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        try {
            const result = await requestJson('/api/executive-actions/subscription-transfers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ member_id: memberId, amount })
            });
            setMessage(
                'transfer-message',
                `${result.message} Reference: ${result.transfer_reference}.`
            );
            document.getElementById('transfer-amount').value = '';
            await loadTransferBalances();
        } catch (error) {
            setMessage('transfer-message', error.message, true);
            console.error('Unable to transfer subscription balance:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function publishAnnouncement(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        try {
            const result = await requestJson('/api/home/announcements', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: form.elements.namedItem('title').value,
                    content: form.elements.namedItem('content').value
                })
            });
            form.reset();
            setMessage('announcement-message', result.message || 'Announcement published.');
        } catch (error) {
            setMessage('announcement-message', error.message, true);
            console.error('Unable to publish announcement:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function loadHomeGallerySlots() {
        const container = document.getElementById('home-gallery-slots');
        if (!container) return;
        try {
            const result = await requestJson('/api/home/gallery');
            const images = (result.data || [])
                .filter(image => image.cloudinary_public_id)
                .sort((left, right) => Number(left.slot) - Number(right.slot));
            const occupiedSlots = new Set(images.map(image => Number(image.slot)));
            const nextSlot = Array.from(
                { length: 100 },
                (_, index) => index + 1
            ).find(slot => !occupiedSlots.has(slot));
            const count = document.getElementById('gallery-count');
            if (count) count.textContent = `${images.length} of 100 images stored.`;
            container.replaceChildren();

            images.forEach(current => {
                const slot = Number(current.slot);
                const card = document.createElement('article');
                card.className = 'home-gallery-slot';
                card.append(createCellHeading(`Image slot ${slot}`));
                const preview = document.createElement('img');
                preview.src = current.image_url;
                preview.alt = `Current Home Dashboard gallery image ${slot}`;
                preview.loading = 'lazy';
                card.appendChild(preview);
                const status = document.createElement('p');
                status.textContent = `Managed image · ${current.uploaded_by || 'Executive'}`;
                card.appendChild(status);
                card.appendChild(createGalleryUploadForm(slot, 'Replace image'));
                container.appendChild(card);
            });

            if (nextSlot) {
                const card = document.createElement('article');
                card.className = 'home-gallery-slot';
                card.append(createCellHeading('Add an image'));
                card.appendChild(createGalleryUploadForm(nextSlot, 'Upload image'));
                container.appendChild(card);
            } else if (!images.length) {
                container.textContent = 'The gallery could not find an available upload slot.';
            } else {
                const limit = document.createElement('p');
                limit.className = 'gallery-limit-message';
                limit.textContent = 'The gallery has reached its 100-image limit. Replace an existing image to update it.';
                container.appendChild(limit);
            }
        } catch (error) {
            container.textContent = 'Could not load gallery slots.';
            setMessage('gallery-message', error.message, true);
            console.error('Unable to load Home Dashboard gallery slots:', error);
        }
    }

    function createCellHeading(text) {
        const heading = document.createElement('h3');
        heading.textContent = text;
        return heading;
    }

    function createGalleryUploadForm(slot, buttonLabel) {
        const form = document.createElement('form');
        form.className = 'gallery-upload-form';
        const input = document.createElement('input');
        input.type = 'file';
        input.name = 'image';
        input.accept = 'image/jpeg,image/png,image/webp';
        input.required = true;
        input.setAttribute('aria-label', `Choose image for gallery slot ${slot}`);
        const button = document.createElement('button');
        button.type = 'submit';
        button.textContent = buttonLabel;
        form.append(input, button);
        form.addEventListener('submit', event => uploadHomeGalleryImage(event, slot, button));
        return form;
    }

    async function uploadHomeGalleryImage(event, slot, button) {
        event.preventDefault();
        const form = event.currentTarget;
        const file = form.elements.namedItem('image').files[0];
        if (!file) {
            setMessage('gallery-message', 'Choose an image before uploading.', true);
            return;
        }
        if (file.size > 5 * 1024 * 1024) {
            setMessage('gallery-message', 'Each image must be 5 MB or smaller.', true);
            return;
        }
        const body = new FormData();
        body.append('image', file);
        button.disabled = true;
        setMessage('gallery-message', `Uploading image ${slot}...`);
        try {
            await requestJson(`/api/home/gallery/${slot}`, {
                method: 'POST',
                body
            });
            setMessage('gallery-message', `Image ${slot} saved to the Home Dashboard gallery.`);
            await loadHomeGallerySlots();
        } catch (error) {
            setMessage('gallery-message', error.message, true);
            console.error(`Unable to upload Home Dashboard gallery image ${slot}:`, error);
        } finally {
            button.disabled = false;
        }
    }

    let sharingIsActive = false;
    async function loadSharingState() {
        const state = document.getElementById('sharing-state');
        const button = document.getElementById('toggle-sharing');
        if (!state || !button) return;
        try {
            const result = await requestJson('/api/sharing/admin/cycle');
            sharingIsActive = Boolean(result.data?.active);
            state.textContent = sharingIsActive
                ? 'Sharing cycle is active; member withdrawals are enabled.'
                : 'Sharing cycle is locked; member withdrawals are disabled.';
            button.textContent = sharingIsActive ? 'Lock sharing cycle' : 'Unlock sharing cycle';
        } catch (error) {
            state.textContent = error.message;
            button.disabled = true;
            console.error('Unable to load sharing cycle:', error);
        }
    }

    async function loadSharingWithdrawalQueue() {
        const body = document.getElementById('sharing-withdrawal-queue');
        if (!body) return;
        try {
            const result = await requestJson('/api/sharing/admin/withdrawals');
            const requests = result.data || [];
            body.replaceChildren();
            if (!requests.length) {
                appendEmptyRow(body, 6, 'No pending sharing withdrawal requests.');
                return;
            }

            const page = document.querySelector('.executive-actions-page');
            const canApprove = page?.dataset.canApproveSharing === 'true';
            const canDisburse = page?.dataset.canDisburseSharing === 'true';

            requests.forEach(request => {
                const row = document.createElement('tr');
                row.append(
                    createCell(`#${request.id}`),
                    createCell(`${request.full_name || 'Member'} (${request.member_id})`),
                    createCell(currencyFormat.format(Number(request.amount) || 0)),
                    createCell(request.status),
                    createCell(request.requested_on),
                );
                const actions = document.createElement('td');

                if (request.status.toLowerCase() === 'pending' && canApprove) {
                    const comment = document.createElement('input');
                    comment.maxLength = 1000;
                    comment.placeholder = 'Optional review note';
                    const approve = document.createElement('button');
                    approve.type = 'button';
                    approve.textContent = 'Approve';
                    approve.addEventListener('click', () =>
                        reviewSharingWithdrawal(request.id, 'approve', comment.value, approve)
                    );
                    const reject = document.createElement('button');
                    reject.type = 'button';
                    reject.textContent = 'Reject';
                    reject.className = 'reject-button';
                    reject.addEventListener('click', () =>
                        reviewSharingWithdrawal(request.id, 'reject', comment.value, reject)
                    );
                    actions.append(comment, approve, reject);
                } else if (request.status.toLowerCase() === 'approved' && canDisburse) {
                    const disburse = document.createElement('button');
                    disburse.type = 'button';
                    disburse.textContent = 'Mark Paid / Disbursed';
                    disburse.addEventListener('click', () =>
                        disburseSharingWithdrawal(request.id, disburse)
                    );
                    actions.appendChild(disburse);
                } else {
                    actions.textContent = request.status.toLowerCase() === 'pending'
                        ? 'Awaiting Chairperson approval'
                        : 'Awaiting Treasurer disbursement';
                }
                row.appendChild(actions);
                body.appendChild(row);
            });
        } catch (error) {
            appendEmptyRow(body, 6, 'Could not load sharing withdrawal requests.');
            setMessage('sharing-withdrawals-message', error.message, true);
            console.error('Unable to load sharing withdrawal queue:', error);
        }
    }

    async function reviewSharingWithdrawal(requestId, decision, comment, button) {
        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/sharing/admin/withdrawals/${encodeURIComponent(requestId)}/review`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ decision, comment })
                }
            );
            setMessage('sharing-withdrawals-message', result.message);
            await loadSharingWithdrawalQueue();
        } catch (error) {
            setMessage('sharing-withdrawals-message', error.message, true);
            console.error('Unable to review sharing withdrawal:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function disburseSharingWithdrawal(requestId, button) {
        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/sharing/admin/withdrawals/${encodeURIComponent(requestId)}/disburse`,
                { method: 'PUT' }
            );
            setMessage('sharing-withdrawals-message', result.message);
            await loadSharingWithdrawalQueue();
        } catch (error) {
            setMessage('sharing-withdrawals-message', error.message, true);
            console.error('Unable to disburse sharing withdrawal:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function toggleSharing(button) {
        button.disabled = true;
        try {
            const result = await requestJson('/api/sharing/admin/cycle-toggle', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: !sharingIsActive })
            });
            setMessage('sharing-message', result.message);
            await loadSharingState();
        } catch (error) {
            setMessage('sharing-message', error.message, true);
            console.error('Unable to change sharing cycle:', error);
        } finally {
            button.disabled = false;
        }
    }

    const overrideChoices = [
        '',
        'Full member / Active',
        'Partial member / Active',
        'Probation member / Active',
        'Full member / Inactive'
    ];

    async function loadMemberStatuses() {
        const body = document.getElementById('member-status-queue');
        if (!body) return;
        try {
            const result = await requestJson('/api/admin/members/status-report');
            body.replaceChildren();
            const members = result.data || [];
            if (!members.length) {
                appendEmptyRow(body, 9, 'No member status records.');
                return;
            }
            members.forEach(member => {
                const row = document.createElement('tr');
                if (member.account_suspended) row.classList.add('suspended-member-row');
                row.append(
                    createCell(`${member.full_name || ''} (${member.member_id || ''})`),
                    createCell(member.days_in_group),
                    createCell(currencyFormat.format(Number(member.total_welfare) || 0)),
                    createCell(currencyFormat.format(Number(member.welfare_balance) || 0)),
                    createCell(member.auto_welfare_classification),
                    createCell(currencyFormat.format(Number(member.subscription_debt) || 0)),
                );
                const finalStatusCell = document.createElement('td');
                finalStatusCell.appendChild(createMemberStatusIndicator(member.final_status));
                row.appendChild(finalStatusCell);
                const overrideCell = document.createElement('td');
                if (document.querySelector('.executive-actions-page')?.dataset.canOverrideMembers === 'true') {
                    const select = document.createElement('select');
                    select.className = 'member-override';
                    select.dataset.memberId = member.member_id;
                    overrideChoices.forEach(value => {
                        const option = document.createElement('option');
                        option.value = value;
                        option.textContent = value || 'Use automatic status';
                        option.selected = value === (member.manual_override || '');
                        select.appendChild(option);
                    });
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.textContent = 'Save';
                    button.addEventListener('click', () => updateMemberOverride(select, button));
                    overrideCell.append(select, button);
                } else {
                    overrideCell.textContent = member.manual_override || 'None';
                }
                row.appendChild(overrideCell);
                const accountAccessCell = document.createElement('td');
                if (document.querySelector('.executive-actions-page')?.dataset.canSuspendMembers === 'true') {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = member.account_suspended
                        ? 'restore-member-account'
                        : 'suspend-member-account';
                    button.textContent = member.account_suspended
                        ? 'Restore account'
                        : 'Suspend account';
                    button.addEventListener('click', () =>
                        updateMemberSuspension(member, button)
                    );
                    accountAccessCell.appendChild(button);
                    if (member.account_suspended && member.suspension_reason) {
                        const reason = document.createElement('small');
                        reason.textContent = `Reason: ${member.suspension_reason}`;
                        accountAccessCell.appendChild(reason);
                    }
                } else {
                    accountAccessCell.appendChild(createMemberStatusIndicator(
                        member.account_suspended ? 'Suspended' : 'Active'
                    ));
                }
                row.appendChild(accountAccessCell);
                body.appendChild(row);
            });
        } catch (error) {
            appendEmptyRow(body, 9, 'Could not load member status report.');
            setMessage('member-message', error.message, true);
            console.error('Unable to load member status report:', error);
        }
    }

    async function updateMemberSuspension(member, button) {
        const restoring = Boolean(member.account_suspended);
        const reason = window.prompt(
            restoring
                ? `Reason for restoring ${member.full_name || member.member_id}'s account:`
                : `Reason for suspending ${member.full_name || member.member_id}'s account:`
        );
        if (reason === null) return;
        if (!reason.trim()) {
            setMessage('member-message', 'Enter a reason to continue.', true);
            return;
        }

        button.disabled = true;
        try {
            const action = restoring ? 'restore' : 'suspend';
            const result = await requestJson(
                `/api/admin/members/${encodeURIComponent(member.member_id)}/${action}`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: reason.trim() })
                }
            );
            setMessage('member-message', result.message);
            await loadMemberStatuses();
        } catch (error) {
            setMessage('member-message', error.message, true);
            console.error('Unable to update member account suspension:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function updateMemberOverride(select, button) {
        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/admin/members/${encodeURIComponent(select.dataset.memberId)}/override-status`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ override_status: select.value || null })
                }
            );
            setMessage('member-message', result.message);
            await loadMemberStatuses();
        } catch (error) {
            setMessage('member-message', error.message, true);
            console.error('Unable to update member override:', error);
        } finally {
            button.disabled = false;
        }
    }

    function memberOptionText(member) {
        return `${member.full_name || 'Member'} (${member.member_id}) — ${formatAmount(member.available_savings)} available`;
    }

    function populateMemberSelect(select, members) {
        if (!select) return;
        select.replaceChildren();
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Select a member';
        select.appendChild(placeholder);
        members.forEach(member => {
            const option = document.createElement('option');
            option.value = member.member_id;
            option.textContent = memberOptionText(member);
            option.dataset.available = String(member.available_savings || 0);
            select.appendChild(option);
        });
        if (!members.length) placeholder.textContent = 'No member accounts found';
    }

    async function loadMemberFinanceDesk() {
        const ledger = document.getElementById('manual-subscription-ledger');
        const welfareLedger = document.getElementById('welfare-transfer-ledger');
        const loanLedger = document.getElementById('loan-repayment-ledger');
        const historicalLoanLedger = document.getElementById('historical-loan-ledger');
        if (!ledger) return;
        try {
            const result = await requestJson('/api/executive-actions/member-finances');
            const members = result.data?.members || [];
            const subscriptions = (result.data?.subscriptions || [])
                .filter(subscription => String(subscription.status || '').trim().toLowerCase() === 'paid');
            const monthlyTarget = Number(
                document.querySelector('.executive-actions-page')?.dataset.monthlySubscriptionTarget
                || 20000
            );
            memberFinanceAccounts = members;
            [
                'manual-subscription-member',
                'installment-member',
                'withdrawal-member',
                'historical-loan-member'
            ].forEach(id => populateMemberSelect(document.getElementById(id), members));
            prefillManualSubscriptionFromQuery(members);

            ledger.replaceChildren();
            if (!subscriptions.length) {
                appendEmptyRow(ledger, 5, 'No subscription records found.');
            } else {
                subscriptions.forEach(subscription => {
                    const row = document.createElement('tr');
                    row.append(
                        createCell(`${subscription.full_name || 'Member'} (${subscription.member_id})`),
                        createCell(new Date(subscription.billing_month).toLocaleDateString('en-GB', {
                            month: 'long',
                            year: 'numeric'
                        })),
                        createCell(currencyFormat.format(Number(subscription.amount_paid) || 0)),
                        createCell(
                            String(subscription.status || '').trim().toLowerCase() === 'paid'
                                && Number(subscription.amount_paid) < monthlyTarget
                                ? 'Partially Paid'
                                : subscription.status
                        )
                    );
                    const actionCell = document.createElement('td');
                    if (String(subscription.status || '').trim().toLowerCase() === 'paid') {
                        const button = document.createElement('button');
                        button.type = 'button';
                        button.className = 'member-finance-delete';
                        button.textContent = 'Remove entry';
                        button.addEventListener('click', () => removeSubscription(subscription, button));
                        actionCell.appendChild(button);
                    } else {
                        actionCell.textContent = '—';
                    }
                    row.appendChild(actionCell);
                    ledger.appendChild(row);
                });
            }

            const welfareTransfers = result.data?.welfare_transfers || [];
            welfareLedger?.replaceChildren();
            if (welfareLedger && !welfareTransfers.length) {
                appendEmptyRow(welfareLedger, 6, 'No welfare transfer records found.');
            } else {
                welfareTransfers.forEach(transfer => {
                    const row = document.createElement('tr');
                    row.append(
                        createCell(`${transfer.full_name || 'Member'} (${transfer.member_id})`),
                        createCell(transfer.created_at
                            ? new Date(transfer.created_at).toLocaleDateString('en-GB')
                            : '—'),
                        createCell(formatAmount(transfer.amount)),
                        createCell(formatAmount(transfer.arrears_paid)),
                        createCell(transfer.transfer_reference)
                    );
                    const actionCell = document.createElement('td');
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'member-finance-delete';
                    button.textContent = 'Remove transfer';
                    button.addEventListener('click', () => removeWelfareTransfer(transfer, button));
                    actionCell.appendChild(button);
                    row.appendChild(actionCell);
                    welfareLedger?.appendChild(row);
                });
            }

            const loanRepayments = result.data?.loan_repayments || [];
            loanLedger?.replaceChildren();
            if (loanLedger && !loanRepayments.length) {
                appendEmptyRow(loanLedger, 7, 'No loan installment records found.');
            } else {
                loanRepayments.forEach(repayment => {
                    const row = document.createElement('tr');
                    row.append(
                        createCell(`${repayment.full_name || 'Member'} (${repayment.member_id})`),
                        createCell(`#${repayment.loan_id}`),
                        createCell(repayment.recorded_at
                            ? new Date(repayment.recorded_at).toLocaleDateString('en-GB')
                            : '—'),
                        createCell(formatAmount(repayment.principal_paid)),
                        createCell(formatAmount(repayment.interest_paid)),
                        createCell(repayment.recorded_by || '—')
                    );
                    const actionCell = document.createElement('td');
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'member-finance-delete';
                    button.textContent = 'Remove installment';
                    button.addEventListener('click', () => removeLoanInstallment(repayment, button));
                    actionCell.appendChild(button);
                    row.appendChild(actionCell);
                    loanLedger?.appendChild(row);
                });
            }
            const historicalLoans = result.data?.historical_loans || [];
            historicalLoanLedger?.replaceChildren();
            if (historicalLoanLedger && !historicalLoans.length) {
                appendEmptyRow(historicalLoanLedger, 9, 'No historical loan imports found.');
            } else {
                historicalLoans.forEach(loan => {
                    const row = document.createElement('tr');
                    row.append(
                        createCell(`${loan.full_name || 'Member'} (${loan.member_id})`),
                        createCell(`#${loan.loan_id}`),
                        createCell(loan.source_reference),
                        createCell(loan.applied_date
                            ? new Date(loan.applied_date).toLocaleDateString('en-GB')
                            : '—'),
                        createCell(loan.balance_as_of_date
                            ? new Date(loan.balance_as_of_date).toLocaleDateString('en-GB')
                            : '—'),
                        createCell(formatAmount(loan.amount_requested)),
                        createCell(formatAmount(loan.outstanding_balance)),
                        createCell(loan.status)
                    );
                    const actionCell = document.createElement('td');
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'member-finance-delete';
                    const laterRepayments = Number(loan.subsequent_repayment_count || 0);
                    if (String(loan.status || '').trim().toLowerCase() === 'reversed') {
                        button.textContent = 'Already voided';
                        button.disabled = true;
                    } else if (laterRepayments > 0) {
                        button.textContent = 'Later activity';
                        button.disabled = true;
                        button.title = 'Remove later system repayments before voiding this import.';
                    } else {
                        button.textContent = 'Void import';
                        button.addEventListener('click', () => voidHistoricalLoan(loan, button));
                    }
                    actionCell.appendChild(button);
                    row.appendChild(actionCell);
                    historicalLoanLedger?.appendChild(row);
                });
            }
            updateInstallmentLoans();
            updateWithdrawalBalance();
        } catch (error) {
            appendEmptyRow(ledger, 5, 'Could not load subscription records.');
            if (welfareLedger) appendEmptyRow(welfareLedger, 6, 'Could not load welfare transfers.');
            if (loanLedger) appendEmptyRow(loanLedger, 7, 'Could not load loan installments.');
            if (historicalLoanLedger) appendEmptyRow(historicalLoanLedger, 9, 'Could not load historical loan imports.');
            setMessage('manual-subscription-message', error.message, true);
            console.error('Unable to load member financial accounts:', error);
        }
    }

    function updateInstallmentLoans() {
        const memberId = document.getElementById('installment-member')?.value;
        const loanSelect = document.getElementById('installment-loan');
        const outstandingText = document.getElementById('installment-outstanding');
        const amountInput = document.getElementById('installment-amount');
        if (!loanSelect || !outstandingText || !amountInput) return;
        loanSelect.replaceChildren();

        const selectedMember = memberFinanceAccounts.find(
            member => member.member_id === memberId
        );
        const loans = selectedMember?.loans || [];
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = loans.length ? 'Select an active loan' : 'No active loans for this member';
        loanSelect.appendChild(placeholder);
        loans.forEach(loan => {
            const option = document.createElement('option');
            option.value = loan.loan_id;
            option.dataset.outstanding = String(loan.outstanding_balance);
            option.textContent = `Loan #${loan.loan_id} — ${formatAmount(loan.outstanding_balance)} outstanding`;
            loanSelect.appendChild(option);
        });
        loanSelect.disabled = loans.length === 0;
        updateInstallmentOutstanding();
    }

    function updateInstallmentOutstanding() {
        const loanSelect = document.getElementById('installment-loan');
        const outstandingText = document.getElementById('installment-outstanding');
        const amountInput = document.getElementById('installment-amount');
        if (!loanSelect || !outstandingText || !amountInput) return;
        const outstanding = Number(loanSelect.selectedOptions[0]?.dataset.outstanding || 0);
        outstandingText.textContent = `Outstanding: ${formatAmount(outstanding)}`;
        amountInput.max = String(outstanding);
    }

    function addHistoricalRepaymentRow() {
        const body = document.getElementById('historical-loan-repayments');
        if (!body) return;
        if (body.rows.length >= 500) {
            setMessage('historical-loan-message', 'A historical import can contain at most 500 repayments.', true);
            return;
        }
        const row = document.createElement('tr');
        const dateCell = document.createElement('td');
        const paymentDate = document.createElement('input');
        paymentDate.type = 'date';
        paymentDate.className = 'historical-repayment-date';
        paymentDate.required = true;
        paymentDate.setAttribute('aria-label', 'Historical repayment date');
        dateCell.appendChild(paymentDate);

        const principalCell = document.createElement('td');
        const principalPaid = document.createElement('input');
        principalPaid.type = 'number';
        principalPaid.min = '0';
        principalPaid.step = '0.01';
        principalPaid.value = '0';
        principalPaid.className = 'historical-repayment-principal';
        principalPaid.required = true;
        principalPaid.setAttribute('aria-label', 'Historical principal repaid');
        principalCell.appendChild(principalPaid);

        const interestCell = document.createElement('td');
        const interestPaid = document.createElement('input');
        interestPaid.type = 'number';
        interestPaid.min = '0';
        interestPaid.step = '0.01';
        interestPaid.value = '0';
        interestPaid.className = 'historical-repayment-interest';
        interestPaid.required = true;
        interestPaid.setAttribute('aria-label', 'Historical interest repaid');
        interestCell.appendChild(interestPaid);

        const actionCell = document.createElement('td');
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'member-finance-delete';
        remove.textContent = 'Remove';
        remove.addEventListener('click', () => {
            row.remove();
            updateHistoricalLoanPreview();
        });
        actionCell.appendChild(remove);
        row.append(dateCell, principalCell, interestCell, actionCell);
        body.appendChild(row);
        row.addEventListener('input', updateHistoricalLoanPreview);
        updateHistoricalLoanPreview();
    }

    function updateHistoricalLoanPreview() {
        const preview = document.getElementById('historical-loan-balance-preview');
        if (!preview) return;
        const principal = Number(document.getElementById('historical-loan-principal')?.value);
        const unpaidInterest = Number(
            document.getElementById('historical-loan-unpaid-interest')?.value || 0
        );
        if (!Number.isFinite(principal) || principal <= 0
            || !Number.isFinite(unpaidInterest) || unpaidInterest < 0) {
            preview.textContent = 'Enter a valid principal and unpaid-interest amount to preview the balance.';
            return;
        }
        const principalPaid = [...document.querySelectorAll('.historical-repayment-principal')]
            .reduce((total, input) => total + (Number(input.value) || 0), 0);
        const interestPaid = [...document.querySelectorAll('.historical-repayment-interest')]
            .reduce((total, input) => total + (Number(input.value) || 0), 0);
        const principalOutstanding = principal - principalPaid;
        if (principalOutstanding < -0.005) {
            preview.textContent = 'Principal repayments exceed the original principal. Correct the entries before saving.';
            return;
        }
        const balance = Math.max(principalOutstanding, 0) + unpaidInterest;
        const status = balance <= 0.005 ? 'Cleared (Paid)' : 'Running (Approved)';
        preview.textContent =
            `Principal repaid: ${formatAmount(principalPaid)} · Interest repaid: ${formatAmount(interestPaid)} · ` +
            `Principal outstanding: ${formatAmount(Math.max(principalOutstanding, 0))} · ` +
            `Total outstanding: ${formatAmount(balance)} · Resulting status: ${status}.`;
    }

    async function submitHistoricalLoan(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type="submit"]');
        const repayments = [...document.querySelectorAll('#historical-loan-repayments tr')]
            .map(row => ({
                payment_date: row.querySelector('.historical-repayment-date').value,
                principal_paid: Number(row.querySelector('.historical-repayment-principal').value),
                interest_paid: Number(row.querySelector('.historical-repayment-interest').value)
            }));
        const payload = {
            member_id: document.getElementById('historical-loan-member').value,
            source_reference: document.getElementById('historical-loan-reference').value.trim(),
            issued_date: document.getElementById('historical-loan-issued-date').value,
            balance_as_of_date: document.getElementById('historical-loan-balance-date').value,
            principal: Number(document.getElementById('historical-loan-principal').value),
            unpaid_interest: Number(document.getElementById('historical-loan-unpaid-interest').value || 0),
            repayments,
            notes: document.getElementById('historical-loan-notes').value.trim()
        };
        if (!payload.member_id || !payload.source_reference || !payload.issued_date
            || !payload.balance_as_of_date || !(payload.principal > 0)) {
            setMessage('historical-loan-message', 'Complete the member, source reference, dates, and original principal.', true);
            return;
        }
        const principalPaid = repayments.reduce((total, item) => total + item.principal_paid, 0);
        const interestPaid = repayments.reduce((total, item) => total + item.interest_paid, 0);
        const principalOutstanding = payload.principal - principalPaid;
        const totalOutstanding = Math.max(principalOutstanding, 0) + payload.unpaid_interest;
        if (principalOutstanding < -0.005) {
            setMessage('historical-loan-message', 'Historical principal repayments exceed the original principal.', true);
            return;
        }
        const confirmation = [
            `Import this historical loan for ${document.getElementById('historical-loan-member').selectedOptions[0]?.textContent}?`,
            `Local-book reference: ${payload.source_reference}`,
            `Original issue date: ${payload.issued_date}`,
            `Balance verified as of: ${payload.balance_as_of_date}`,
            `Original principal: ${formatAmount(payload.principal)}`,
            `Principal repaid: ${formatAmount(principalPaid)}`,
            `Interest repaid: ${formatAmount(interestPaid)}`,
            `Interest still unpaid: ${formatAmount(payload.unpaid_interest)}`,
            `Current total outstanding: ${formatAmount(totalOutstanding)}`,
            `Resulting status: ${totalOutstanding <= 0.005 ? 'Cleared (Paid)' : 'Running (Approved)'}`,
            `Repayments to add: ${repayments.length}`,
            'This updates the principal and interest ledgers. A mistaken import can be voided only before any later system repayment is posted.'
        ].join('\n');
        if (!window.confirm(confirmation)) return;

        button.disabled = true;
        setMessage('historical-loan-message', 'Validating and recording historical loan...');
        try {
            const result = await requestJson('/api/executive-actions/historical-loans', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            form.reset();
            document.getElementById('historical-loan-repayments').replaceChildren();
            updateHistoricalLoanPreview();
            setMessage(
                'historical-loan-message',
                `${result.message} Loan #${result.loan_id}: ${result.status}; ` +
                `outstanding ${formatAmount(result.outstanding_balance)}.`
            );
            await loadMemberFinanceDesk();
        } catch (error) {
            setMessage('historical-loan-message', error.message, true);
            console.error('Unable to import historical loan:', error);
        } finally {
            button.disabled = false;
        }
    }

    function updateWithdrawalBalance() {
        const select = document.getElementById('withdrawal-member');
        const amount = document.getElementById('withdrawal-amount');
        const balance = document.getElementById('withdrawal-available');
        if (!select || !amount || !balance) return;
        const available = Number(select.selectedOptions[0]?.dataset.available || 0);
        amount.max = String(available);
        balance.textContent = `Available savings: ${formatAmount(available)}`;
    }

    function prefillManualSubscriptionFromQuery(members) {
        const url = new URL(window.location.href);
        const memberId = url.searchParams.get('manual_member_id');
        if (!memberId) return;
        const member = members.find(item => item.member_id === memberId);
        const memberInput = document.getElementById('manual-subscription-member');
        const amountInput = document.getElementById('manual-subscription-amount');
        if (member && memberInput && amountInput) {
            memberInput.value = memberId;
            const amount = url.searchParams.get('manual_amount');
            if (amount && Number.isFinite(Number(amount)) && Number(amount) > 0) {
                amountInput.value = amount;
            }
            document.getElementById('manual-subscription-note').value =
                'Manual entry following payment proof review';
        }
        url.searchParams.delete('manual_member_id');
        url.searchParams.delete('manual_amount');
        window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    }

    function clearManualSubscriptionPreview() {
        manualSubscriptionPreview = null;
        const preview = document.getElementById('manual-subscription-preview');
        if (!preview) return;
        preview.replaceChildren();
        preview.hidden = true;
    }

    async function confirmManualSubscription(button) {
        const selectedMember = document.getElementById('manual-subscription-member').value;
        const amount = Number(document.getElementById('manual-subscription-amount').value);
        if (
            !manualSubscriptionPreview
            || manualSubscriptionPreview.memberId !== selectedMember
            || manualSubscriptionPreview.amount !== amount
        ) {
            clearManualSubscriptionPreview();
            setMessage('manual-subscription-message', 'The payment details changed. Preview the allocation again.', true);
            return;
        }

        button.disabled = true;
        setMessage('manual-subscription-message', 'Posting the confirmed payment allocation...');
        try {
            const result = await requestJson('/api/executive-actions/member-subscriptions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    member_id: selectedMember,
                    amount,
                    note: document.getElementById('manual-subscription-note').value,
                    expected_allocations: manualSubscriptionPreview.allocations
                })
            });
            const allocationSummary = (result.allocations || [])
                .map(item => `${formatBillingMonth(item.billing_month)} ${formatAmount(item.amount)}`)
                .join('; ');
            document.getElementById('manual-subscription-form').reset();
            clearManualSubscriptionPreview();
            setMessage(
                'manual-subscription-message',
                `${result.message} Posted: ${allocationSummary}. Available savings: ${formatAmount(result.available_savings)}.`
            );
            await loadMemberFinanceDesk();
        } catch (error) {
            clearManualSubscriptionPreview();
            setMessage('manual-subscription-message', error.message, true);
            console.error('Unable to record manual subscription:', error);
        } finally {
            button.disabled = false;
        }
    }

    function showManualSubscriptionPreview(previewResult, memberId, amount) {
        const preview = document.getElementById('manual-subscription-preview');
        preview.replaceChildren();
        preview.hidden = false;
        const heading = document.createElement('h4');
        heading.textContent = `Allocation of ${formatAmount(amount)}`;
        preview.appendChild(heading);
        renderAllocationList(preview, previewResult.allocations || []);
        const confirmButton = document.createElement('button');
        confirmButton.type = 'button';
        confirmButton.className = 'member-finance-primary';
        confirmButton.textContent = 'Confirm and post payment';
        confirmButton.addEventListener('click', () =>
            confirmManualSubscription(confirmButton)
        );
        preview.appendChild(confirmButton);
        manualSubscriptionPreview = {
            memberId,
            amount,
            allocations: previewResult.allocations || []
        };
    }

    async function submitManualSubscription(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type="submit"]');
        const memberId = document.getElementById('manual-subscription-member').value;
        const amount = Number(document.getElementById('manual-subscription-amount').value);
        clearManualSubscriptionPreview();
        button.disabled = true;
        button.textContent = 'Preparing preview...';
        try {
            const result = await requestJson('/api/executive-actions/member-subscriptions/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    member_id: memberId,
                    amount
                })
            });
            showManualSubscriptionPreview(result, memberId, amount);
            setMessage('manual-subscription-message', 'Review the allocation, then confirm to update the ledger and savings.');
        } catch (error) {
            setMessage('manual-subscription-message', error.message, true);
            console.error('Unable to preview manual subscription allocation:', error);
        } finally {
            button.disabled = false;
            button.textContent = 'Preview allocation';
        }
    }

    async function removeSubscription(subscription, button) {
        const reason = window.prompt(
            `Why are you removing paid subscription #${subscription.id}?`
        );
        if (reason === null || !reason.trim()) return;
        if (!window.confirm('This permanently deletes the subscription and updates member savings. Continue?')) {
            return;
        }
        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/executive-actions/member-subscriptions/${encodeURIComponent(subscription.id)}`,
                {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: reason.trim() })
                }
            );
            setMessage('manual-subscription-message', result.message);
            await loadMemberFinanceDesk();
        } catch (error) {
            setMessage('manual-subscription-message', error.message, true);
            console.error('Unable to remove subscription entry:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function removeWelfareTransfer(transfer, button) {
        const reason = window.prompt(
            `Why are you removing welfare transfer #${transfer.id} for ${transfer.full_name || transfer.member_id}?`
        );
        if (reason === null || !reason.trim()) return;
        if (!window.confirm(
            `This permanently removes the UGX ${currencyFormat.format(Number(transfer.amount) || 0)} welfare transfer and reverses UGX ${currencyFormat.format(Number(transfer.arrears_paid) || 0)} in linked arrears payments. Continue?`
        )) {
            return;
        }
        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/executive-actions/member-welfare-transfers/${encodeURIComponent(transfer.id)}`,
                {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: reason.trim() })
                }
            );
            setMessage('manual-subscription-message', result.message);
            await loadMemberFinanceDesk();
        } catch (error) {
            setMessage('manual-subscription-message', error.message, true);
            console.error('Unable to remove welfare transfer:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function removeLoanInstallment(repayment, button) {
        const amount = Number(repayment.principal_paid || 0) + Number(repayment.interest_paid || 0);
        const reason = window.prompt(
            `Why are you removing loan installment #${repayment.repayment_id} for loan #${repayment.loan_id}?`
        );
        if (reason === null || !reason.trim()) return;
        if (!window.confirm(
            `This permanently removes the UGX ${currencyFormat.format(amount)} installment and restores that amount to the outstanding loan balance. Continue?`
        )) {
            return;
        }
        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/executive-actions/loan-installments/${encodeURIComponent(repayment.repayment_id)}`,
                {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: reason.trim() })
                }
            );
            setMessage(
                'installment-message',
                `${result.message} New outstanding balance: ${formatAmount(result.outstanding_balance)}.`
            );
            await loadMemberFinanceDesk();
        } catch (error) {
            setMessage('installment-message', error.message, true);
            console.error('Unable to remove loan installment:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function voidHistoricalLoan(loan, button) {
        const reason = window.prompt(
            `Why are you voiding historical loan #${loan.loan_id} for ${loan.full_name || loan.member_id}?`
        );
        if (reason === null) return;
        if (reason.trim().length < 8) {
            setMessage('historical-loan-message', 'Enter a correction reason of at least 8 characters.', true);
            return;
        }
        if (!window.confirm(
            `This will remove the imported repayments from loan and interest totals, mark the loan Reversed, and record the reason in the audit history. It does not represent a cash reversal. Continue?`
        )) return;

        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/executive-actions/historical-loans/${encodeURIComponent(loan.loan_id)}`,
                {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason: reason.trim() })
                }
            );
            setMessage('historical-loan-message', result.message);
            await loadMemberFinanceDesk();
        } catch (error) {
            setMessage('historical-loan-message', error.message, true);
            console.error('Unable to void historical loan import:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function submitLoanInstallment(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        try {
            const result = await requestJson('/api/executive-actions/loan-installments', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    loan_id: Number(document.getElementById('installment-loan').value),
                    amount: Number(document.getElementById('installment-amount').value),
                    note: document.getElementById('installment-note').value
                })
            });
            form.reset();
            setMessage(
                'installment-message',
                `${result.message} Interest: ${formatAmount(result.interest_paid)}; principal: ${formatAmount(result.principal_paid)}; remaining: ${formatAmount(result.outstanding_balance)}.`
            );
            await loadMemberFinanceDesk();
        } catch (error) {
            setMessage('installment-message', error.message, true);
            console.error('Unable to record loan installment:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function submitSavingsWithdrawal(event) {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        try {
            const result = await requestJson('/api/executive-actions/member-withdrawals', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    member_id: document.getElementById('withdrawal-member').value,
                    amount: Number(document.getElementById('withdrawal-amount').value),
                    reason: document.getElementById('withdrawal-reason').value
                })
            });
            form.reset();
            setMessage(
                'withdrawal-message',
                `${result.message} Available after reservation: ${formatAmount(result.available_savings)}.`
            );
            await loadMemberFinanceDesk();
        } catch (error) {
            setMessage('withdrawal-message', error.message, true);
            console.error('Unable to request member savings withdrawal:', error);
        } finally {
            button.disabled = false;
        }
    }

    async function loadMemberWithdrawalQueue() {
        const body = document.getElementById('member-withdrawal-queue');
        if (!body) return;
        try {
            const result = await requestJson('/api/executive-actions/member-withdrawals');
            const withdrawals = result.data || [];
            body.replaceChildren();
            if (!withdrawals.length) {
                appendEmptyRow(body, 6, 'No member withdrawals are awaiting approval.');
                return;
            }
            withdrawals.forEach(withdrawal => {
                const row = document.createElement('tr');
                row.append(
                    createCell(`${withdrawal.full_name || 'Member'} (${withdrawal.member_id})`),
                    createCell(currencyFormat.format(Number(withdrawal.amount) || 0)),
                    createCell(currencyFormat.format(Number(withdrawal.available_savings) || 0)),
                    createCell(withdrawal.reason),
                    createCell(withdrawal.requested_by)
                );
                const actionCell = document.createElement('td');
                const actions = document.createElement('div');
                actions.className = 'withdrawal-review-actions';
                [['Approve', 'approve', ''], ['Reject', 'reject', 'reject-button']].forEach(
                    ([label, decision, className]) => {
                        const button = document.createElement('button');
                        button.type = 'button';
                        button.textContent = label;
                        if (className) button.className = className;
                        button.addEventListener('click', () =>
                            reviewMemberWithdrawal(withdrawal, decision, button)
                        );
                        actions.appendChild(button);
                    }
                );
                actionCell.appendChild(actions);
                row.appendChild(actionCell);
                body.appendChild(row);
            });
        } catch (error) {
            appendEmptyRow(body, 6, 'Could not load pending member withdrawals.');
            setMessage('member-withdrawal-message', error.message, true);
            console.error('Unable to load member withdrawal requests:', error);
        }
    }

    async function reviewMemberWithdrawal(withdrawal, decision, button) {
        const comment = decision === 'reject'
            ? window.prompt('Enter a reason for rejecting this withdrawal:')
            : window.prompt('Optional approval note:');
        if (comment === null || (decision === 'reject' && !comment.trim())) return;
        button.disabled = true;
        try {
            const result = await requestJson(
                `/api/executive-actions/member-withdrawals/${encodeURIComponent(withdrawal.id)}/review`,
                {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ decision, comment: comment.trim() })
                }
            );
            setMessage('member-withdrawal-message', result.message);
            await loadMemberWithdrawalQueue();
        } catch (error) {
            setMessage('member-withdrawal-message', error.message, true);
            console.error('Unable to review member savings withdrawal:', error);
        } finally {
            button.disabled = false;
        }
    }

    const memberStatusToggle = document.getElementById('member-status-toggle');
    const memberStatusPanel = document.getElementById('member-status-panel');

    if (memberStatusToggle && memberStatusPanel) {
        memberStatusToggle.addEventListener('click', () => {
            const isCollapsed = memberStatusPanel.classList.toggle('is-collapsed');
            memberStatusToggle.textContent = isCollapsed ? 'Expand' : 'Collapse';
            memberStatusToggle.setAttribute('aria-expanded', String(!isCollapsed));
        });
    }

    document.getElementById('refresh-proofs')?.addEventListener('click', loadProofQueue);
    document.getElementById('refresh-loans')?.addEventListener('click', loadLoanQueue);
    document.getElementById('refresh-welfare')?.addEventListener('click', loadWelfareQueue);
    document.getElementById('refresh-balances')?.addEventListener('click', loadTransferBalances);
    document.getElementById('refresh-members')?.addEventListener('click', loadMemberStatuses);
    document.getElementById('member-generator-form')?.addEventListener('submit', submitMemberGenerator);
    document.getElementById('refresh-member-finances')?.addEventListener('click', loadMemberFinanceDesk);
    document.getElementById('refresh-member-withdrawals')?.addEventListener('click', loadMemberWithdrawalQueue);
    document.getElementById('refresh-emergency-reversal')?.addEventListener('click', loadLatestEmergencyAction);
    document.getElementById('transfer-member')?.addEventListener('change', updateTransferAvailability);
    document.getElementById('installment-member')?.addEventListener('change', updateInstallmentLoans);
    document.getElementById('installment-loan')?.addEventListener('change', updateInstallmentOutstanding);
    document.getElementById('withdrawal-member')?.addEventListener('change', updateWithdrawalBalance);
    document.getElementById('manual-subscription-member')?.addEventListener('change', clearManualSubscriptionPreview);
    document.getElementById('manual-subscription-amount')?.addEventListener('input', clearManualSubscriptionPreview);
    document.getElementById('transfer-form')?.addEventListener('submit', submitTransfer);
    document.getElementById('manual-subscription-form')?.addEventListener('submit', submitManualSubscription);
    document.getElementById('loan-installment-form')?.addEventListener('submit', submitLoanInstallment);
    document.getElementById('historical-loan-form')?.addEventListener('submit', submitHistoricalLoan);
    document.getElementById('add-historical-repayment')?.addEventListener('click', addHistoricalRepaymentRow);
    [
        'historical-loan-principal',
        'historical-loan-unpaid-interest'
    ].forEach(id => document.getElementById(id)?.addEventListener('input', updateHistoricalLoanPreview));
    document.getElementById('savings-withdrawal-form')?.addEventListener('submit', submitSavingsWithdrawal);
    document.getElementById('announcement-form')?.addEventListener('submit', publishAnnouncement);
    document.getElementById('emergency-reversal-form')?.addEventListener('submit', submitEmergencyReversal);
    loadHomeGallerySlots();
    document.getElementById('toggle-sharing')?.addEventListener('click', event => toggleSharing(event.currentTarget));
    document.getElementById('refresh-sharing-withdrawals')?.addEventListener('click', loadSharingWithdrawalQueue);

    loadProofQueue();
    loadLoanQueue();
    loadWelfareQueue();
    loadTransferBalances();
    loadSharingState();
    loadSharingWithdrawalQueue();
    loadMemberStatuses();
    loadMemberFinanceDesk();
    loadMemberWithdrawalQueue();
    loadLatestEmergencyAction();
})();
