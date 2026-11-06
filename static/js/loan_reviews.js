async function loadPendingLoans() {
    const tbody = document.getElementById('pending-loans-body');
    if (!tbody) return;
    const message = document.getElementById('message');

    try {
        const response = await fetch('/api/loans/pending-review', { credentials: 'include' });
        const result = await readApiJson(response, 'Could not load the loan review queue. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Access denied or failed to load queue.');
        tbody.replaceChildren();
        if (!Array.isArray(result.data) || result.data.length === 0) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 6;
            cell.style.textAlign = 'center';
            cell.textContent = 'No pending loan applications found.';
            row.appendChild(cell);
            tbody.appendChild(row);
            return;
        }

        result.data.forEach(loan => {
            const row = document.createElement('tr');
            const id = document.createElement('td');
            const strong = document.createElement('strong');
            strong.textContent = `#${loan.id}`;
            id.appendChild(strong);
            const member = document.createElement('td');
            member.textContent = loan.member_id || '';
            const amount = document.createElement('td');
            amount.textContent = Number(loan.amount_requested).toLocaleString();
            const purpose = document.createElement('td');
            purpose.textContent = loan.purpose || '';
            const date = document.createElement('td');
            date.textContent = loan.created_at || 'N/A';
            const actions = document.createElement('td');
            [['Approve', 'btn-approve', 'Approved'], ['Reject', 'btn-reject', 'Rejected']].forEach(([text, cssClass, decision]) => {
                const button = document.createElement('button');
                button.className = cssClass;
                button.textContent = text;
                button.addEventListener('click', () => reviewLoan(loan.id, decision));
                actions.appendChild(button);
            });
            row.append(id, member, amount, purpose, date, actions);
            tbody.appendChild(row);
        });
    } catch (error) {
        if (message) {
            message.style.color = '#e74c3c';
            message.textContent = error.message || 'Could not load pending loans.';
        }
        console.error('Error loading pending loans:', error);
    }
}

async function reviewLoan(loanId, decision) {
    const message = document.getElementById('message');
    if (!message) return;
    message.textContent = '';
    try {
        const response = await fetch(`/api/loans/${encodeURIComponent(loanId)}/review`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ decision })
        });
        const result = await readApiJson(response, 'Could not review this loan. Please try again.');
        message.style.color = response.ok ? '#27ae60' : '#e74c3c';
        message.textContent = response.ok ? result.message : result.detail || 'Action failed.';
        if (response.ok) await loadPendingLoans();
    } catch (error) {
        message.style.color = '#e74c3c';
        message.textContent = error.message || 'Could not review this loan. Please try again.';
        console.error('Error reviewing loan:', error);
    }
}

loadPendingLoans();
