async function readApiJson(
    response,
    fallbackMessage = 'Server error or maintenance mode. Please try again.'
) {
    const contentType = response.headers.get('content-type')?.toLowerCase() || '';
    const isJson = contentType.includes('application/json') || contentType.includes('+json');

    if (!response.ok) {
        if (isJson) {
            let payload;
            try {
                payload = await response.json();
            } catch (error) {
                if (!(error instanceof SyntaxError)) throw error;
            }
            const detail = payload?.detail || payload?.message;
            if (typeof detail === 'string') throw new Error(detail);
            if (Array.isArray(detail)) {
                const messages = detail
                    .map(item => typeof item === 'string' ? item : item?.msg)
                    .filter(message => typeof message === 'string' && message);
                if (messages.length) throw new Error(messages.join('; '));
            }
            throw new Error(fallbackMessage);
        }

        await response.text();
        throw new Error(fallbackMessage);
    }

    if (!isJson) {
        await response.text();
        throw new Error('The server returned an unexpected response. Please try again.');
    }

    return response.json();
}

document.getElementById('logout-button')?.addEventListener('click', async () => {
    try {
        const response = await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'include'
        });
        if (response.ok) {
            window.location.href = '/api/auth/page';
        } else {
            window.alert('Logout failed.');
        }
    } catch (error) {
        console.error('Logout error:', error);
    }
});

const sidebar = document.querySelector('.sidebar');
const sidebarToggle = document.getElementById('sidebar-toggle');

function setSidebarOpen(isOpen) {
    if (!sidebar || !sidebarToggle) return;

    sidebar.classList.toggle('is-open', isOpen);
    sidebarToggle.setAttribute('aria-expanded', String(isOpen));
    sidebarToggle.setAttribute(
        'aria-label',
        isOpen ? 'Close navigation menu' : 'Open navigation menu'
    );
}

sidebarToggle?.addEventListener('click', () => {
    setSidebarOpen(!sidebar?.classList.contains('is-open'));
});

document.querySelectorAll('.sidebar-menu a').forEach(link => {
    link.addEventListener('click', () => setSidebarOpen(false));
});

document.addEventListener('keydown', event => {
    if (event.key === 'Escape') setSidebarOpen(false);
});

const roleRestrictedNavigation = [
    {
        linkId: 'nav-executive-actions',
        roles: ['chairperson', 'treasurer', 'secretary', 'welfare', 'welfare officer']
    },
    {
        linkId: 'nav-audit',
        roles: ['chairperson', 'treasurer', 'secretary']
    },
    {
        linkId: 'nav-member-profiles',
        roles: ['chairperson', 'treasurer', 'secretary']
    },
    {
        linkId: 'nav-treasurer-reports',
        roles: ['treasurer', 'chairperson', 'secretary']
    }
];

(async () => {
    if (!roleRestrictedNavigation.some(({ linkId }) => document.getElementById(linkId))) {
        return;
    }

    try {
        const response = await fetch('/api/auth/me', { credentials: 'include' });
        if (!response.ok) {
            throw new Error(`Could not load the current user role (HTTP ${response.status}).`);
        }

        const payload = await readApiJson(response, 'Could not load the current user role. Please try again.');
        const role = String(payload?.user?.role || '').toLowerCase();

        roleRestrictedNavigation.forEach(({ linkId, roles }) => {
            const link = document.getElementById(linkId);
            const menuItem = link?.closest('li');
            if (menuItem) menuItem.hidden = !roles.includes(role);
        });
    } catch (error) {
        console.warn('Could not determine role for sidebar visibility:', error);
    }
})();

const currentPath = window.location.pathname;
document.querySelectorAll('.sidebar-menu a').forEach(link => {
    const href = link.getAttribute('href');
    if (href === currentPath || (href && currentPath.startsWith(`${href}/`))) {
        link.classList.add('active');
    }
});

function getCollapsibleLabel(target) {
    const section = target.closest('section, .card, .report-panel, .action-panel');
    const heading = section?.querySelector('h2, h3, h4');
    if (heading?.textContent.trim()) return heading.textContent.trim();

    let current = target;
    while (current && current !== document.body) {
        let previous = current.previousElementSibling;
        while (previous) {
            const precedingHeading = previous.matches('h1, h2, h3, h4')
                ? previous
                : previous.querySelector('h1, h2, h3, h4');
            if (precedingHeading?.textContent.trim()) {
                return precedingHeading.textContent.trim();
            }
            previous = previous.previousElementSibling;
        }
        current = current.parentElement;
    }

    const caption = target.querySelector('caption');
    if (caption?.textContent.trim()) return caption.textContent.trim();
    return 'records';
}

function addCollapseControl(target, type) {
    if (!target || target.dataset.collapseControl === 'true') return;

    const label = getCollapsibleLabel(target);
    target.classList.add('collapsible-sheet-content');
    if (!target.id) {
        target.id = `collapsible-${type}-${Math.random().toString(36).slice(2, 10)}`;
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sheet-collapse-toggle';
    button.textContent = label;
    button.dataset.collapseLabel = label;
    button.setAttribute('aria-controls', target.id);
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', label);
    target.hidden = true;
    button.addEventListener('click', () => {
        const collapsed = button.getAttribute('aria-expanded') === 'true';
        target.hidden = collapsed;
        button.setAttribute('aria-expanded', String(!collapsed));
    });

    target.parentElement?.insertBefore(button, target);
    target.dataset.collapseControl = 'true';
}

document.querySelectorAll(
    '.table-wrap, .audit-table-scroll, .report-table-wrap, .family-table-wrap'
).forEach(target => addCollapseControl(target, 'table'));

document.querySelectorAll('table').forEach(table => {
    const wrapper = table.closest(
        '.table-wrap, .audit-table-scroll, .report-table-wrap, .family-table-wrap'
    );
    addCollapseControl(wrapper || table, 'table');
});

document.querySelectorAll(
    'main ul, main ol, #notifications-container, #global-running-loan-list'
).forEach(target => {
    if (target.closest('details')) return;
    addCollapseControl(target, 'list');
});
