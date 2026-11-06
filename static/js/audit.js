const auditPageSize = 100;
let auditOffset = 0;
let welfareAuditOffset = 0;

function appendAuditCell(row, value) {
    const cell = document.createElement('td');
    cell.textContent = value === null || value === undefined || value === '' ? '—' : String(value);
    row.appendChild(cell);
}

function formatAuditDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function showAuditEmptyRow(body, colspan, message) {
    if (!body) return;
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = colspan;
    cell.className = 'audit-empty';
    cell.textContent = message;
    row.appendChild(cell);
    body.replaceChildren(row);
}

async function loadAuditTable(options) {
    const body = document.getElementById(options.bodyId);
    const count = document.getElementById(options.countId);
    const error = document.getElementById(options.errorId);
    const moreButton = document.getElementById(options.moreButtonId);
    if (!body || !count || !error || !moreButton) return 0;
    error.textContent = '';
    moreButton.disabled = true;

    try {
        const response = await fetch(
            `${options.url}?limit=${auditPageSize}&offset=${options.offset}`,
            { credentials: 'include' }
        );
        const result = await readApiJson(response, 'Could not load audit records. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not load audit records.');
        const records = Array.isArray(result.data) ? result.data : [];
        const loadedCount = Number(result.count) || records.length;
        const totalLoaded = options.offset + loadedCount;
        count.textContent = `${totalLoaded} record${totalLoaded === 1 ? '' : 's'} loaded`;

        if (records.length === 0) {
            if (!options.append) showAuditEmptyRow(body, options.columns.length, options.emptyMessage);
            return loadedCount;
        }
        if (!options.append) body.replaceChildren();
        records.forEach(record => {
            const row = document.createElement('tr');
            options.columns.forEach(column => {
                const value = column.format ? column.format(record) : record[column.key];
                appendAuditCell(row, value);
            });
            body.appendChild(row);
        });
        moreButton.disabled = loadedCount < auditPageSize;
        return loadedCount;
    } catch (loadError) {
        count.textContent = 'Unavailable';
        error.textContent = loadError.message || 'A network error occurred.';
        if (!options.append) showAuditEmptyRow(body, options.columns.length, 'Audit records could not be loaded.');
        console.error('Error loading audit records:', loadError);
        return 0;
    }
}

async function loadAdministrativeAuditLogs(append = false) {
    if (!append) auditOffset = 0;
    const offset = auditOffset;
    const loaded = await loadAuditTable({
        url: '/api/audit/logs',
        bodyId: 'audit-log-body',
        countId: 'audit-log-count',
        errorId: 'audit-log-error',
        moreButtonId: 'audit-load-more',
        offset,
        append,
        emptyMessage: 'No administrative audit records found.',
        columns: [
            { key: 'created_at', format: record => formatAuditDate(record.created_at) },
            { key: 'action' },
            { key: 'entity_type', format: record => `${record.entity_type || '—'}${record.entity_id ? ` #${record.entity_id}` : ''}` },
            { key: 'actor_name', format: record => `${record.actor_name || '—'}${record.actor_role ? ` (${record.actor_role})` : ''}` },
            { key: 'details' },
            { key: 'previous_value' },
            { key: 'new_value' }
        ]
    });
    auditOffset = offset + loaded;
}

async function loadWelfareAuditLogs(append = false) {
    if (!append) welfareAuditOffset = 0;
    const offset = welfareAuditOffset;
    const loaded = await loadAuditTable({
        url: '/api/audit/welfare-logs',
        bodyId: 'welfare-audit-body',
        countId: 'welfare-audit-count',
        errorId: 'welfare-audit-error',
        moreButtonId: 'welfare-audit-load-more',
        offset,
        append,
        emptyMessage: 'No welfare audit records found.',
        columns: [
            { key: 'created_at', format: record => formatAuditDate(record.created_at) },
            { key: 'request_id', format: record => record.request_id ? `#${record.request_id}` : '—' },
            { key: 'action' },
            { key: 'user_name', format: record => `${record.user_name || record.user_id || '—'}${record.role ? ` (${record.role})` : ''}` },
            { key: 'previous_status', format: record => `${record.previous_status || '—'} → ${record.new_status || '—'}` },
            { key: 'details' },
            { key: 'payment_reference' },
            { key: 'ip_address' }
        ]
    });
    welfareAuditOffset = offset + loaded;
}

function loadAuditLogs() {
    loadAdministrativeAuditLogs();
    loadWelfareAuditLogs();
}

document.getElementById('audit-export-form')?.addEventListener('submit', event => {
    event.preventDefault();
    const form = event.currentTarget;
    const startDate = form.elements.start_date.value;
    const endDate = form.elements.end_date.value;
    const error = document.getElementById('audit-export-error');
    if (error) error.textContent = '';
    if (!startDate || !endDate) {
        if (error) error.textContent = 'Select both a start date and an end date.';
        return;
    }
    if (startDate > endDate) {
        if (error) error.textContent = 'The start date must be on or before the end date.';
        return;
    }
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    window.location.assign(`/api/audit/pdf?${params.toString()}`);
});

document.getElementById('audit-refresh')?.addEventListener('click', loadAuditLogs);
document.getElementById('audit-load-more')?.addEventListener('click', () => loadAdministrativeAuditLogs(true));
document.getElementById('welfare-audit-load-more')?.addEventListener('click', () => loadWelfareAuditLogs(true));
loadAuditLogs();
