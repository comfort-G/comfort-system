function addEmptyLedgerRow(tbody, text) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 4;
    cell.style.textAlign = 'center';
    cell.textContent = text;
    row.appendChild(cell);
    tbody.replaceChildren(row);
}

async function loadLedger() {
    const tbody = document.getElementById('ledger-table-body');
    if (!tbody) return;
    const errorMessage = document.getElementById('error-message');

    try {
        const response = await fetch('/api/subscriptions/ledger', { credentials: 'include' });
        const result = await readApiJson(response, 'Could not load the subscription ledger. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Failed to load ledger.');

        const data = result.data;
        const total = document.getElementById('total-paid');
        const currentSavings = document.getElementById('current-savings');
        const arrears = document.getElementById('subscription-arrears');
        const arrearsPeriod = document.getElementById('arrears-period');
        const pending = document.getElementById('pending-count');
        const monthlyTarget = Number(data.monthly_subscription_target || 20000);
        if (total) total.textContent = Number(data.total_paid_contributions || 0).toLocaleString();
        if (currentSavings) currentSavings.textContent = Number(data.current_savings || 0).toLocaleString();
        if (arrears) arrears.textContent = Number(data.subscription_arrears || 0).toLocaleString();
        if (arrearsPeriod) {
            arrearsPeriod.textContent = `${data.arrears_period || 'January through current month'} · UGX ${Number(data.monthly_subscription_target || 0).toLocaleString()} per month`;
        }
        if (pending) pending.textContent = String(data.pending_proofs_count);
        tbody.replaceChildren();

        if (!Array.isArray(data.history) || data.history.length === 0) {
            addEmptyLedgerRow(tbody, 'No subscription records found.');
            return;
        }

        data.history.forEach(item => {
            const row = document.createElement('tr');
            const date = document.createElement('td');
            date.textContent = item.payment_date || 'N/A';
            const amount = document.createElement('td');
            amount.textContent = Number(item.amount).toLocaleString();
            const statusCell = document.createElement('td');
            const badge = document.createElement('span');
            const normalizedStatus = String(item.status || '').trim().toLowerCase();
            const partialPayment = normalizedStatus === 'paid'
                && Number(item.amount) < monthlyTarget;
            badge.className = partialPayment
                ? 'badge-partial'
                : normalizedStatus === 'paid'
                    ? 'badge-paid'
                    : 'badge-pending';
            badge.textContent = partialPayment
                ? 'Partially paid'
                : normalizedStatus === 'paid'
                    ? 'Paid'
                    : item.status || '';
            statusCell.appendChild(badge);
            const notes = document.createElement('td');
            notes.textContent = item.notes || '-';
            row.append(date, amount, statusCell, notes);
            tbody.appendChild(row);
        });
    } catch (error) {
        addEmptyLedgerRow(tbody, 'Subscription history could not be loaded.');
        if (errorMessage) errorMessage.textContent = error.message || 'A network error occurred while loading your ledger.';
        console.error('Error loading subscription ledger:', error);
    }
}

async function submitPaymentProof(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const fileInput = document.getElementById('payment-proof-file');
    const message = document.getElementById('payment-proof-message');
    const submitButton = form.querySelector('button[type="submit"]');
    if (!fileInput || !message || !submitButton) return;

    message.textContent = '';
    message.classList.remove('is-error', 'is-success');
    if (!fileInput.files || fileInput.files.length === 0) {
        message.textContent = 'Select your transaction SMS screenshot before uploading.';
        message.classList.add('is-error');
        return;
    }

    const formData = new FormData();
    formData.append('image', fileInput.files[0]);
    submitButton.disabled = true;
    submitButton.textContent = 'Uploading proof...';
    message.textContent = 'Uploading your proof for Treasurer review...';

    try {
        const response = await fetch('/api/subscriptions/submit-proof-upload', {
            method: 'POST',
            credentials: 'include',
            body: formData
        });
        const result = await readApiJson(response, 'Could not upload payment proof. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Payment proof upload failed.');

        message.textContent = result.message || 'Payment proof submitted for Treasurer review.';
        message.classList.add('is-success');
        form.reset();
        await loadLedger();
    } catch (error) {
        message.textContent = error.message || 'A network error occurred while uploading your proof.';
        message.classList.add('is-error');
        console.error('Error submitting subscription payment proof:', error);
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = 'Upload payment proof';
    }
}

const paymentProofForm = document.getElementById('payment-proof-form');
if (paymentProofForm) {
    paymentProofForm.addEventListener('submit', submitPaymentProof);
}

loadLedger();
