let isSharingActive = false;

async function loadSharingDashboard() {
    const statusAlert = document.getElementById('sharing-status-alert');
    if (!statusAlert) return;
    try {
        const dashboardResponse = await fetch('/api/sharing/dashboard', { credentials: 'include' });
        const result = await readApiJson(dashboardResponse, 'Could not load sharing information. Please try again.');
        if (!dashboardResponse.ok) throw new Error(result.detail || 'Failed to load dashboard.');
        const data = result.data;
        isSharingActive = Boolean(data.is_sharing_active);
        const formatMoney = value => {
            const amount = Number(value);
            return Number.isFinite(amount) ? amount.toLocaleString() : '0';
        };
        const setText = (id, value) => {
            const element = document.getElementById(id);
            if (element) element.textContent = value;
        };
        setText('savings-payout', formatMoney(data.available_savings_payout));
        setText('borrower-payout', formatMoney(data.borrower_interest_payout));
        setText('general-pool', formatMoney(data.general_group_dividend));
        setText('total-payout', formatMoney(data.total_payout));
        const amountField = document.getElementById('withdraw-amount');
        if (amountField) {
            const availablePayout = Number(data.total_payout);
            amountField.max = Number.isFinite(availablePayout)
                ? Math.max(availablePayout, 0).toFixed(2)
                : '0.00';
        }
        setText('welfare-note', data.welfare_note || '');

        const withdrawalHistory = document.getElementById('sharing-withdrawal-history');
        if (withdrawalHistory) {
            withdrawalHistory.replaceChildren();
            const requests = data.withdrawal_requests || [];
            if (!requests.length) {
                const row = document.createElement('tr');
                const cell = document.createElement('td');
                cell.colSpan = 5;
                cell.textContent = 'No withdrawal requests yet.';
                row.appendChild(cell);
                withdrawalHistory.appendChild(row);
            } else {
                requests.forEach(request => {
                    const row = document.createElement('tr');
                    [
                        `#${request.id}`,
                        formatMoney(request.amount),
                        request.status || 'Unknown',
                        request.requested_on
                            ? new Date(request.requested_on).toLocaleString()
                            : '',
                        request.review_comment || ''
                    ].forEach(value => {
                        const cell = document.createElement('td');
                        cell.textContent = value;
                        row.appendChild(cell);
                    });
                    withdrawalHistory.appendChild(row);
                });
            }
        }

        const adminReserve = document.getElementById('admin-reserve-wrapper');
        if (typeof data.admin_cost_reserve === 'number' && adminReserve) {
            adminReserve.classList.remove('hidden');
            setText('admin-reserve', formatMoney(data.admin_cost_reserve));
        }
        const withdrawalSection = document.getElementById('withdrawal-section');
        if (isSharingActive) {
            statusAlert.className = 'alert-active';
            statusAlert.textContent = 'Year-End Sharing is currently ACTIVE. Withdrawals are enabled.';
            withdrawalSection?.classList.remove('hidden');
        } else {
            statusAlert.className = 'alert-locked';
            statusAlert.textContent = 'Year-End Sharing is currently LOCKED by the Chairperson.';
            withdrawalSection?.classList.add('hidden');
        }

    } catch (error) {
        statusAlert.textContent = error.message || 'Sharing dashboard could not be loaded.';
        console.error('Error loading sharing dashboard:', error);
    }
}

document.getElementById('withdrawal-section')?.querySelector('button')?.addEventListener('click', async () => {
    const amountField = document.getElementById('withdraw-amount');
    const message = document.getElementById('message');
    if (!amountField || !message) return;
    const amount = Number.parseFloat(amountField.value);
    if (!Number.isFinite(amount) || amount <= 0) {
        message.style.color = '#e74c3c';
        message.textContent = 'Please enter a valid withdrawal amount.';
        return;
    }
    try {
        const response = await fetch('/api/sharing/withdraw', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ amount })
        });
        const result = await readApiJson(response, 'Could not submit the withdrawal request. Please try again.');
        message.style.color = response.ok ? '#27ae60' : '#e74c3c';
        message.textContent = response.ok ? result.message : result.detail || 'Withdrawal failed.';
        if (response.ok) {
            amountField.value = '';
            await loadSharingDashboard();
        }
    } catch (error) {
        message.style.color = '#e74c3c';
        message.textContent = error.message || 'Could not submit the withdrawal request. Please try again.';
        console.error('Error submitting sharing withdrawal:', error);
    }
});

loadSharingDashboard();
