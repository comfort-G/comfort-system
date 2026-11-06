async function loadStatusReport() {
    const tbody = document.getElementById('members-table-body');
    if (!tbody) return;
    const message = document.getElementById('message');

    try {
        const response = await fetch('/api/admin/members/status-report', { credentials: 'include' });
        const result = await readApiJson(response, 'Could not load member status report. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not load member status report.');
        tbody.replaceChildren();

        (result.data || []).forEach(member => {
            const row = document.createElement('tr');
            const badgeClass = member.auto_welfare_classification === 'Partial member'
                ? 'badge-partial'
                : member.auto_welfare_classification === 'Probation member' ? 'badge-probation' : 'badge-full';
            const memberId = document.createElement('td');
            const memberIdStrong = document.createElement('strong');
            memberIdStrong.textContent = member.member_id || '';
            memberId.appendChild(memberIdStrong);
            const name = document.createElement('td');
            name.textContent = member.full_name || '';
            const days = document.createElement('td');
            days.textContent = `${member.days_in_group} days`;
            const welfare = document.createElement('td');
            welfare.textContent = Number(member.total_welfare).toLocaleString();
            const welfareBalance = document.createElement('td');
            welfareBalance.textContent = Number(member.welfare_balance).toLocaleString();
            const debt = document.createElement('td');
            debt.textContent = Number(member.subscription_debt).toLocaleString();
            const classification = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = badgeClass;
            badge.textContent = member.auto_welfare_classification || '';
            classification.appendChild(badge);
            const finalStatus = document.createElement('td');
            const finalStatusBadge = document.createElement('span');
            const statusText = member.final_status || 'Not recorded';
            const normalizedStatus = statusText.toLowerCase();
            const statusClass = normalizedStatus.includes('inactive')
                || normalizedStatus.includes('suspend')
                ? 'is-inactive'
                : normalizedStatus.includes('active') ? 'is-active' : 'is-unknown';
            finalStatusBadge.className = `member-status-indicator ${statusClass}`;
            const statusDot = document.createElement('span');
            statusDot.className = 'member-status-indicator-dot';
            statusDot.setAttribute('aria-hidden', 'true');
            finalStatusBadge.append(statusDot, document.createTextNode(statusText));
            finalStatus.appendChild(finalStatusBadge);
            if (member.manual_override) {
                const override = document.createElement('span');
                override.style.color = '#e67e22';
                override.style.fontSize = '11px';
                override.textContent = ' (Overridden)';
                finalStatus.appendChild(override);
            }
            const actions = document.createElement('td');
            const profileLink = document.createElement('a');
            profileLink.href = `/api/admin/members/profile/${encodeURIComponent(member.member_id)}`;
            profileLink.textContent = 'Profile';
            profileLink.style.color = '#1e7f43';
            profileLink.style.fontWeight = '700';
            profileLink.style.textDecoration = 'none';
            actions.appendChild(profileLink);
            row.append(memberId, name, days, welfare, welfareBalance, debt, classification, finalStatus, actions);
            tbody.appendChild(row);
        });
        if (!result.data || result.data.length === 0) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 9;
            cell.style.textAlign = 'center';
            cell.textContent = 'No member records found.';
            row.appendChild(cell);
            tbody.appendChild(row);
        }
    } catch (error) {
        if (message) {
            message.style.color = '#e74c3c';
            message.textContent = error.message || 'Access denied or failed to load report.';
        }
        console.error('Error loading member report:', error);
    }
}

const overrideButton = document.getElementById('chair-override-card')?.querySelector('button');
overrideButton?.addEventListener('click', async () => {
    const memberField = document.getElementById('override-member-id');
    const statusField = document.getElementById('override-status-select');
    const message = document.getElementById('override-message');
    if (!memberField || !statusField || !message) return;
    const memberId = memberField.value.trim();
    if (!memberId) {
        message.style.color = '#e74c3c';
        message.textContent = 'Please enter a valid member ID.';
        return;
    }

    try {
        const response = await fetch(`/api/admin/members/${encodeURIComponent(memberId)}/override-status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ override_status: statusField.value || null })
        });
        const result = await readApiJson(response, 'Could not update member status. Please try again.');
        message.style.color = response.ok ? '#27ae60' : '#e74c3c';
        message.textContent = response.ok ? result.message : result.detail || 'Override failed.';
        if (response.ok) await loadStatusReport();
    } catch (error) {
        message.style.color = '#e74c3c';
        message.textContent = error.message || 'Could not update member status. Please try again.';
        console.error('Error updating member override:', error);
    }
});

document.getElementById('announcement-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const message = document.getElementById('announcement-form-message');
    const submitButton = form.querySelector('button[type="submit"]');
    if (!(form instanceof HTMLFormElement) || !(submitButton instanceof HTMLButtonElement)) return;
    submitButton.disabled = true;
    if (message) message.textContent = 'Publishing...';

    try {
        const response = await fetch('/api/home/announcements', {
            method: 'POST',
            credentials: 'include',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                title: form.elements.namedItem('title').value,
                content: form.elements.namedItem('content').value
            })
        });
        const result = await readApiJson(response, 'Could not save the announcement. Please try again.');
        if (!response.ok) {
            throw new Error(result.detail || `Announcement could not be posted (${response.status}).`);
        }
        form.reset();
        if (message) message.textContent = 'Announcement published and will appear on the Home page.';
    } catch (error) {
        if (message) message.textContent = error.message || 'Announcement could not be posted.';
        console.error('Unable to publish announcement:', error);
    } finally {
        submitButton.disabled = false;
    }
});

loadStatusReport();
