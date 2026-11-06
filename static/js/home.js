(() => {
    const root = document.getElementById('home-dashboard');
    if (!root) return;

    const numberFormat = new Intl.NumberFormat('en-UG', {
        maximumFractionDigits: 0
    });
    const announcements = [];
    let announcementIndex = 0;
    const galleryImages = [];
    const GALLERY_SLIDESHOW_SIZE = 10;
    let galleryIndex = 0;
    let galleryShowAll = false;

    function setText(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value == null ? 'Not available' : String(value);
    }

    function formatMoney(value) {
        if (value == null || !Number.isFinite(Number(value))) return 'Not available';
        return `UGX ${numberFormat.format(Number(value))}`;
    }

    function formatDate(value) {
        if (!value) return 'Not recorded';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return 'Not recorded';
        return new Intl.DateTimeFormat('en-UG', {
            day: 'numeric',
            month: 'short',
            year: 'numeric'
        }).format(date);
    }

    function formatTimestamp(value) {
        if (!value) return 'Not recorded';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return 'Not recorded';
        return new Intl.DateTimeFormat('en-UG', {
            day: 'numeric',
            month: 'short',
            year: 'numeric',
            hour: 'numeric',
            minute: '2-digit'
        }).format(date);
    }

    function makeElement(tagName, className, text) {
        const element = document.createElement(tagName);
        if (className) element.className = className;
        if (text != null) element.textContent = text;
        return element;
    }

    function showError(message) {
        const error = document.getElementById('home-error');
        if (!error) return;
        error.textContent = message;
        error.hidden = false;
    }

    const executiveReminderEndpoints = {
        proofs: {
            label: 'Subscription payment proofs',
            href: '/api/executive-actions/view#proofs-heading',
            url: '/api/subscriptions/admin/pending-proofs'
        },
        loans: {
            label: 'Loan applications',
            href: '/api/executive-actions/view#loans-heading',
            url: '/api/loans/pending-review'
        },
        welfare: {
            label: 'Welfare requests',
            href: '/api/executive-actions/view#welfare-heading',
            url: '/api/welfare/admin/queue'
        },
        sharing: {
            label: 'Sharing withdrawals',
            href: '/api/executive-actions/view#sharing-withdrawals-heading',
            url: '/api/sharing/admin/withdrawals'
        },
        savingsWithdrawals: {
            label: 'Member savings withdrawals',
            href: '/api/executive-actions/view#member-withdrawal-review-heading',
            url: '/api/executive-actions/member-withdrawals'
        },
        securityAlerts: {
            label: 'Suspended account login alerts',
            href: '/api/notifications/view',
            url: '/api/notifications/'
        }
    };

    async function requestExecutiveQueue(url) {
        const response = await fetch(url, {
            credentials: 'include',
            headers: { Accept: 'application/json' }
        });
        if (!response.ok) {
            throw new Error(`Request failed (${response.status}).`);
        }
        const result = await readApiJson(response, 'Could not load this information. Please try again.');
        const records = url === executiveReminderEndpoints.securityAlerts.url
            ? result.data?.notifications
            : result.data;
        if (!Array.isArray(records)) {
            throw new Error('Queue response is missing its item list.');
        }
        return records;
    }

    function renderExecutiveReminders(items, errors) {
        const root = document.getElementById('executive-reminder');
        const list = document.getElementById('executive-reminder-list');
        const count = document.getElementById('executive-reminder-count');
        const status = document.getElementById('executive-reminder-status');
        const toggle = document.getElementById('executive-reminder-toggle');
        if (!root || !list || !count || !status || !toggle) return;

        list.replaceChildren();
        const total = items.reduce((sum, item) => sum + item.count, 0);
        count.textContent = String(total);
        toggle.classList.toggle('has-pending', total > 0);
        toggle.classList.toggle('has-error', errors.length > 0);
        status.textContent = errors.length
            ? 'Some action queues could not be checked. Refresh to try again.'
            : total
                ? `${total} pending action${total === 1 ? '' : 's'} require your attention.`
                : 'You have no pending executive actions.';

        items.forEach(item => {
            if (!item.count) return;
            const entry = makeElement('li', '');
            const link = document.createElement('a');
            link.className = 'executive-reminder-link';
            link.href = item.href;
            link.append(
                makeElement('span', '', `${item.count} ${item.label}`),
                makeElement('span', 'executive-reminder-link-arrow', 'Review →')
            );
            entry.append(link);
            list.append(entry);
        });

        errors.forEach(error => {
            list.append(makeElement(
                'li',
                'executive-reminder-error',
                `${error.label}: ${error.message}`
            ));
        });
    }

    async function loadExecutiveReminders(role) {
        const root = document.getElementById('executive-reminder');
        if (!root) return;
        const normalizedRole = String(role || '').trim().toLowerCase();
        const isChair = normalizedRole === 'chairperson';
        const isTreasurer = normalizedRole === 'treasurer';
        const isWelfare = ['welfare', 'welfare officer'].includes(normalizedRole);
        const isExecutive = [
            'chairperson',
            'vice chairperson',
            'treasurer',
            'secretary',
            'welfare',
            'welfare officer'
        ].includes(normalizedRole);
        const queues = [];

        if (isExecutive) {
            queues.push({
                key: 'securityAlerts',
                count: records => records.filter(record =>
                    !record.is_read
                    && String(record.title || '').trim().toLowerCase()
                    === 'suspended account login attempt'
                ).length
            });
        }
        if (isChair || isTreasurer || normalizedRole === 'secretary') {
            queues.push({
                key: 'loans',
                count: records => records.length
            });
        }
        if (isChair || isTreasurer) {
            queues.push({
                key: 'proofs',
                count: records => records.length
            });
            queues.push({
                key: 'sharing',
                count: records => records.filter(record =>
                    String(record.status || '').trim().toLowerCase()
                    === (isChair ? 'pending' : 'approved')
                ).length
            });
        }
        if (isChair || isTreasurer || isWelfare) {
            queues.push({
                key: 'welfare',
                count: records => records.filter(record => {
                    const stage = String(record.current_stage || '').trim().toLowerCase();
                    if (isChair) return stage === 'under review';
                    if (isTreasurer) {
                        return [
                            'submitted',
                            'executive approved',
                            'partially disbursed',
                            'funding shortfall'
                        ].includes(stage);
                    }
                    return stage === 'submitted';
                }).length
            });
        }
        if (isChair) {
            queues.push({
                key: 'savingsWithdrawals',
                count: records => records.length
            });
        }
        if (!queues.length) return;

        root.hidden = false;
        const results = await Promise.allSettled(queues.map(async queue => {
            const records = await requestExecutiveQueue(
                executiveReminderEndpoints[queue.key].url
            );
            return {
                label: executiveReminderEndpoints[queue.key].label,
                href: executiveReminderEndpoints[queue.key].href,
                count: queue.count(records)
            };
        }));
        const items = [];
        const errors = [];
        results.forEach((result, index) => {
            if (result.status === 'fulfilled') {
                items.push(result.value);
            } else {
                errors.push({
                    label: executiveReminderEndpoints[queues[index].key].label,
                    message: result.reason instanceof Error
                        ? result.reason.message
                        : 'An unexpected error occurred.'
                });
                console.error(
                    `Unable to load ${executiveReminderEndpoints[queues[index].key].label} reminder:`,
                    result.reason
                );
            }
        });
        renderExecutiveReminders(items, errors);
    }

    function setActivityStatus(status) {
        const pill = document.getElementById('activity-status');
        if (!pill) return;
        const normalized = String(status || '').toLowerCase();
        const isInactive = normalized.includes('inactive');
        const isActive = normalized.includes('active') && !isInactive;
        pill.classList.toggle('is-inactive', isInactive);
        pill.classList.toggle('is-active', isActive);
        pill.classList.toggle('is-unknown', !isInactive && !isActive);
        setText('activity-status-text', status || 'Not available');
    }

    function renderAnnouncement(record) {
        const card = document.getElementById('current-announcement');
        const controls = document.getElementById('announcement-controls');
        if (!card) return;
        card.replaceChildren();

        if (!record) {
            card.append(makeElement('h3', '', 'Welcome'));
            card.append(makeElement(
                'p',
                'announcement-content',
                'Welcome to the Comfort Group System, where you will get all you need to know about Comfort Group.'
            ));
            if (controls) controls.hidden = true;
            return;
        }

        card.append(makeElement('h3', '', record.title || 'Announcement'));
        card.append(makeElement('p', 'announcement-content', record.content || ''));
        const meta = makeElement(
            'p',
            'announcement-meta',
            `Posted by ${record.author || 'Comfort Group Committee'} · ${formatTimestamp(record.created_at)}`
        );
        card.append(meta);

        if (controls) {
            controls.hidden = announcements.length < 2;
            setText('announcement-position', `${announcementIndex + 1} / ${announcements.length}`);
        }
    }

    function renderAnnouncementHistory(records) {
        const list = document.getElementById('announcement-history-list');
        if (!list) return;
        list.replaceChildren();
        if (!records.length) {
            list.append(makeElement('p', 'empty-state', 'There are no older announcements.'));
            return;
        }
        records.forEach(record => {
            const item = makeElement('article', 'history-item');
            item.append(makeElement('h3', '', record.title || 'Announcement'));
            item.append(makeElement('p', '', record.content || ''));
            item.append(makeElement(
                'p',
                'announcement-meta',
                `Posted by ${record.author || 'Comfort Group Committee'} · ${formatTimestamp(record.created_at)}`
            ));
            list.append(item);
        });
    }

    function renderGallery() {
        const grid = document.getElementById('home-gallery-grid');
        const slide = document.getElementById('home-gallery-slide');
        const image = document.getElementById('home-gallery-image');
        const controls = document.getElementById('gallery-controls');
        const viewAllButton = document.getElementById('gallery-view-all');
        const emptyState = document.getElementById('home-gallery-empty');
        if (!grid || !slide || !image) return;
        grid.replaceChildren();

        if (!galleryImages.length) {
            slide.hidden = true;
            grid.hidden = true;
            if (controls) controls.hidden = true;
            if (viewAllButton) viewAllButton.hidden = true;
            if (emptyState) emptyState.hidden = false;
            return;
        }

        if (emptyState) emptyState.hidden = true;
        const slideCount = Math.min(galleryImages.length, GALLERY_SLIDESHOW_SIZE);
        galleryIndex = Math.min(galleryIndex, slideCount - 1);
        grid.hidden = !galleryShowAll;
        slide.hidden = galleryShowAll;

        if (galleryShowAll) {
            galleryImages.forEach((current, index) => {
                const card = makeElement('figure', 'home-gallery-card');
                const photo = document.createElement('img');
                photo.src = current.image_url;
                photo.alt = current.alt_text || `Comfort Group community image ${index + 1}`;
                photo.loading = 'lazy';
                card.append(photo);
                card.append(makeElement('figcaption', '', `Image ${index + 1}`));
                grid.append(card);
            });
        } else {
            const current = galleryImages[galleryIndex];
            image.src = current.image_url;
            image.alt = current.alt_text || `Comfort Group community image ${galleryIndex + 1}`;
        }

        if (controls) {
            controls.hidden = galleryShowAll || slideCount < 2;
            setText('gallery-position', `${galleryIndex + 1} / ${slideCount}`);
        }
        if (viewAllButton) {
            viewAllButton.hidden = galleryImages.length <= GALLERY_SLIDESHOW_SIZE;
            viewAllButton.textContent = galleryShowAll ? 'Show slideshow' : 'View all';
        }
    }

    async function loadGallery() {
        try {
            const response = await fetch('/api/home/gallery', {
                credentials: 'include',
                headers: { Accept: 'application/json' }
            });
            if (!response.ok) {
                throw new Error(`Gallery request failed (${response.status}).`);
            }
            const result = await readApiJson(response, 'Could not load the gallery. Please try again.');
            if (!Array.isArray(result.data)) {
                throw new Error('Gallery response is missing its image list.');
            }
            galleryImages.splice(0, galleryImages.length, ...result.data);
            renderGallery();
        } catch (error) {
            console.error('Unable to load Home Dashboard gallery:', error);
        }
    }

    function renderMembers(listId, members, inactive) {
        const list = document.getElementById(listId);
        if (!list) return;
        list.replaceChildren();
        if (!members || !members.length) {
            list.append(makeElement(
                'li',
                'empty-state',
                inactive ? 'No inactive members.' : 'No member records available.'
            ));
            return;
        }
        members.forEach(member => {
            const item = makeElement(
                'li',
                member.account_suspended
                    ? 'member-list-item is-suspended'
                    : 'member-list-item'
            );
            const name = makeElement('strong', '', member.full_name || member.member_id || 'Member');
            const details = makeElement(
                'span',
                '',
                `${member.member_id || 'No member ID'} · ${member.account_status || 'Status not recorded'}`
            );
            item.append(name, details);
            if (member.required_action && member.required_action !== 'No account action required.') {
                item.append(makeElement('small', 'required-action', member.required_action));
            } else if (inactive) {
                item.append(makeElement('small', 'required-action', 'Review account status with the member.'));
            }
            list.append(item);
        });
    }

    function renderRunningLoans(loans) {
        const list = document.getElementById('global-running-loan-list');
        if (!list) return;
        list.replaceChildren();

        if (!Array.isArray(loans) || loans.length === 0) {
            list.append(makeElement('li', 'empty-state', 'There are no running loans.'));
            return;
        }

        loans.forEach(loan => {
            const item = makeElement('li', '');
            const disclosure = makeElement('details', 'global-running-loan');
            const summary = makeElement('summary', 'global-running-loan-summary');
            const summaryCopy = makeElement('span', 'global-running-loan-summary-copy');
            summaryCopy.append(makeElement(
                'strong',
                'global-running-loan-member',
                loan.member_name || loan.member_id || 'Member not recorded'
            ));
            summaryCopy.append(makeElement(
                'span',
                'global-running-loan-reference',
                `Loan #${loan.loan_id} · ${loan.member_id} · ${loan.status}`
            ));
            summary.append(summaryCopy);
            summary.append(makeElement(
                'span',
                'global-running-loan-summary-balance',
                formatMoney(loan.outstanding_balance)
            ));
            disclosure.append(summary);

            const details = makeElement('dl', 'global-running-loan-details');
            [
                ['Requested', formatMoney(loan.amount_requested)],
                ['Outstanding', formatMoney(loan.outstanding_balance)],
                ['Interest accrued', formatMoney(loan.interest_accumulated)],
                ['Approved', formatDate(loan.approved_date)],
                ['Last interest date', formatDate(loan.last_interest_date)],
                ['Next due date', formatDate(loan.next_due_date)]
            ].forEach(([label, value]) => {
                const row = makeElement('div', '');
                row.append(makeElement('dt', '', label));
                row.append(makeElement('dd', '', value));
                details.append(row);
            });
            disclosure.append(details);
            item.append(disclosure);
            list.append(item);
        });
    }

    function renderSummary(data) {
        const profile = data.profile || {};
        const subscription = data.subscription || {};
        const loan = data.loan || {};
        const sharing = data.sharing || {};
        const membership = data.membership || {};
        const permissions = data.permissions || {};
        const financialPanel = document.getElementById('global-financial-panel');
        const globalFinancials = data.global_financials;
        const canViewGlobalFinancials = permissions.is_committee === true
            && globalFinancials != null;
        root.dataset.committee = canViewGlobalFinancials ? 'true' : 'false';
        if (financialPanel) financialPanel.hidden = !canViewGlobalFinancials;
        if (canViewGlobalFinancials) {
            setText('global-subscription-total', formatMoney(globalFinancials.total_subscription_contributions));
            setText('global-subscription-year', formatMoney(globalFinancials.current_year_subscription_contributions));
            setText('global-welfare-total', formatMoney(globalFinancials.welfare_account_balance));
            setText('global-member-savings', formatMoney(globalFinancials.total_member_savings));
            setText('global-unpaid-principal', formatMoney(globalFinancials.unpaid_loan_principal));
            setText('global-working-capital', formatMoney(globalFinancials.group_working_capital));
            setText('global-loan-balance', formatMoney(globalFinancials.running_loan_balance));
            setText('global-running-loans', globalFinancials.running_loan_count);
            setText('global-interest-collected', formatMoney(globalFinancials.total_loan_interest_collected));
            renderRunningLoans(globalFinancials.running_loans);
        }

        setText('welcome-heading', profile.full_name ? `Welcome back, ${profile.full_name}!` : 'Welcome back!');
        const avatarInitials = document.getElementById('profile-avatar-initials');
        const avatarImage = document.getElementById('profile-avatar-image');
        if (avatarInitials) avatarInitials.textContent = profile.avatar_initials || '--';
        if (avatarImage instanceof HTMLImageElement) {
            avatarImage.hidden = !profile.avatar_url;
            if (profile.avatar_url) avatarImage.src = profile.avatar_url;
        }
        if (avatarInitials) avatarInitials.hidden = Boolean(profile.avatar_url);
        setText('profile-role', profile.role || 'Role not assigned');
        setText('profile-tier', profile.membership_tier || 'Membership tier not available');
        loadExecutiveReminders(profile.role);
        setText('current-savings', formatMoney(subscription.current_savings));
        setActivityStatus(subscription.activity_status);
        setText('total-contributions', formatMoney(subscription.total_contributions));
        setText('member-welfare', formatMoney(subscription.welfare_balance));
        setText('pending-subscriptions', subscription.pending_items ?? 0);
        setText('subscription-arrears', formatMoney(subscription.arrears));
        const arrears = document.getElementById('subscription-arrears');
        if (arrears) arrears.closest('.arrears-stat')?.classList.toggle('has-arrears', Number(subscription.arrears) > 0);
        setText('loan-balance', formatMoney(loan.outstanding_balance));
        setText('loan-status', loan.status || 'Not recorded');
        setText('loan-due-date', loan.next_due_date ? formatDate(loan.next_due_date) : 'No due date recorded');
        setText('loan-reconciliation', loan.reconciliation_status || 'Not recorded');
        setText('sharing-overview', sharing.overview || 'Year-end sharing information is not yet available.');

        setText('member-count-total', membership.total ?? 'Not available');
        setText('member-count-active', membership.active ?? 'Not available');
        setText('member-count-inactive', membership.inactive ?? 'Not available');
        renderMembers('active-member-list', membership.active_members, false);
        renderMembers('inactive-member-list', membership.inactive_members, true);

        announcements.splice(
            0,
            announcements.length,
            ...(data.announcements?.current ? [data.announcements.current] : []),
            ...(data.announcements?.history || [])
        );
        announcementIndex = 0;
        renderAnnouncement(announcements[announcementIndex]);
        renderAnnouncementHistory(announcements.slice(1));

    }

    async function loadHomeSummary() {
        try {
            const response = await fetch('/api/home/summary', {
                credentials: 'include',
                headers: { Accept: 'application/json' }
            });
            if (!response.ok) {
                throw new Error(`Dashboard request failed (${response.status}).`);
            }
            const result = await readApiJson(response, 'Could not load the dashboard. Please try again.');
            if (!result.data) throw new Error('Dashboard response is missing its data payload.');
            renderSummary(result.data);
        } catch (error) {
            showError('Dashboard information could not be loaded. Please refresh the page or sign in again.');
            console.error('Unable to load home dashboard:', error);
        }
    }

    document.getElementById('announcement-previous')?.addEventListener('click', () => {
        if (!announcements.length) return;
        announcementIndex = (announcementIndex - 1 + announcements.length) % announcements.length;
        renderAnnouncement(announcements[announcementIndex]);
    });

    document.getElementById('announcement-next')?.addEventListener('click', () => {
        if (!announcements.length) return;
        announcementIndex = (announcementIndex + 1) % announcements.length;
        renderAnnouncement(announcements[announcementIndex]);
    });

    document.getElementById('gallery-previous')?.addEventListener('click', () => {
        const slideCount = Math.min(galleryImages.length, GALLERY_SLIDESHOW_SIZE);
        if (slideCount < 2) return;
        galleryIndex = (galleryIndex - 1 + slideCount) % slideCount;
        renderGallery();
    });

    document.getElementById('gallery-next')?.addEventListener('click', () => {
        const slideCount = Math.min(galleryImages.length, GALLERY_SLIDESHOW_SIZE);
        if (slideCount < 2) return;
        galleryIndex = (galleryIndex + 1) % slideCount;
        renderGallery();
    });

    document.getElementById('gallery-view-all')?.addEventListener('click', () => {
        galleryShowAll = !galleryShowAll;
        renderGallery();
    });

    document.getElementById('executive-reminder-toggle')?.addEventListener('click', event => {
        const toggle = event.currentTarget;
        const panel = document.getElementById('executive-reminder-panel');
        if (!panel) return;
        const isExpanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!isExpanded));
        panel.hidden = isExpanded;
    });

    document.getElementById('executive-reminder-refresh')?.addEventListener('click', () => {
        const role = document.getElementById('profile-role')?.textContent;
        loadExecutiveReminders(role);
    });

    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        const toggle = document.getElementById('executive-reminder-toggle');
        const panel = document.getElementById('executive-reminder-panel');
        if (!toggle || !panel || panel.hidden) return;
        panel.hidden = true;
        toggle.setAttribute('aria-expanded', 'false');
        toggle.focus();
    });

    window.setInterval(() => {
        const slideCount = Math.min(galleryImages.length, GALLERY_SLIDESHOW_SIZE);
        if (slideCount < 2 || galleryShowAll) return;
        galleryIndex = (galleryIndex + 1) % slideCount;
        renderGallery();
    }, 4000);

    window.setInterval(() => {
        const role = document.getElementById('profile-role')?.textContent;
        if (role && role !== 'Role not assigned' && role !== 'Loading role...') {
            loadExecutiveReminders(role);
        }
    }, 90000);

    loadHomeSummary();
    loadGallery();
})();
