async function loadLoansDashboard() {
    const snapshot = document.getElementById('snapshot-content');
    const tbody = document.getElementById('loan-history-body');
    if (!snapshot || !tbody) return;

    try {
        const response = await fetch('/api/loans/my-loans', { credentials: 'include' });
        const result = await readApiJson(response, 'Could not load loan dashboard. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not load loan dashboard.');
        const data = result.data;
        const loan = data.latest_loan_snapshot;
        snapshot.replaceChildren();

        if (loan) {
            [
                ['Loan ID:', `#${loan.id}`],
                ['Amount Requested:', `UGX ${Number(loan.amount_requested).toLocaleString()}`],
                ['Outstanding Balance:', `UGX ${Number(loan.outstanding_balance || 0).toLocaleString()}`],
                ['Mobile Money Number:', loan.mobile_money_number || 'Not provided'],
                ['Status:', loan.status || ''],
                ['Purpose:', loan.purpose || '']
            ].forEach(([label, value]) => {
                const paragraph = document.createElement('p');
                const strong = document.createElement('strong');
                strong.textContent = `${label} `;
                paragraph.append(strong, document.createTextNode(value));
                snapshot.appendChild(paragraph);
            });
        } else {
            const message = document.createElement('p');
            message.textContent = 'You currently have no active or pending loans.';
            snapshot.appendChild(message);
        }

        tbody.replaceChildren();
        if (!Array.isArray(data.loan_history) || data.loan_history.length === 0) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 7;
            cell.style.textAlign = 'center';
            cell.textContent = 'No past loan records found.';
            row.appendChild(cell);
            tbody.appendChild(row);
            return;
        }

        data.loan_history.forEach(item => {
            const row = document.createElement('tr');
            const normalizedStatus = String(item.status || '').trim().toLowerCase();
            const badgeClass = ['approved', 'active'].includes(normalizedStatus)
                ? 'badge-approved'
                : normalizedStatus === 'rejected' ? 'badge-rejected' : 'badge-pending';
            const values = [
                item.created_at || 'N/A',
                Number(item.amount_requested).toLocaleString(),
                `UGX ${Number(item.outstanding_balance || 0).toLocaleString()}`,
                item.mobile_money_number || '—',
                item.purpose || ''
            ];
            values.forEach(value => {
                const cell = document.createElement('td');
                cell.textContent = value;
                row.appendChild(cell);
            });
            const statusCell = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = badgeClass;
            badge.textContent = item.status || '';
            statusCell.appendChild(badge);
            row.appendChild(statusCell);
            const reasonCell = document.createElement('td');
            reasonCell.textContent = normalizedStatus === 'rejected'
                ? item.rejection_reason || 'No reason was recorded. Contact an executive for details.'
                : '—';
            row.appendChild(reasonCell);
            tbody.appendChild(row);
        });
    } catch (error) {
        snapshot.textContent = 'Loan status is unavailable.';
        console.error('Error loading loans dashboard:', error);
    }
}

const loanForm = document.getElementById('loan-form');
if (loanForm) {
    loanForm.addEventListener('submit', async event => {
        event.preventDefault();
        const amountField = document.getElementById('amount');
        const purposeField = document.getElementById('purpose');
        const mobileMoneyNumberField = document.getElementById('mobile-money-number');
        const message = document.getElementById('message');
        if (!amountField || !purposeField || !mobileMoneyNumberField || !message) return;
        message.textContent = '';

        try {
            const response = await fetch('/api/loans/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    amount: Number.parseFloat(amountField.value),
                    purpose: purposeField.value.trim(),
                    mobile_money_number: mobileMoneyNumberField.value.trim()
                })
            });
            const result = await readApiJson(response, 'Loan application failed. Please try again.');
            message.style.color = response.ok ? '#27ae60' : '#e74c3c';
            message.textContent = response.ok
                ? result.message
                : result.detail || 'Loan application failed.';
            if (response.ok) {
                loanForm.reset();
                await loadLoansDashboard();
            }
        } catch (error) {
            message.style.color = '#e74c3c';
            message.textContent = error.message || 'Loan application failed. Please try again.';
            console.error('Error submitting loan application:', error);
        }
    });
}

loadLoansDashboard();
