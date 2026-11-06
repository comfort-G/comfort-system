async function loadNotifications() {
    const container = document.getElementById('notifications-container');
    if (!container) return;
    try {
        const response = await fetch('/api/notifications/', { credentials: 'include' });
        const result = await readApiJson(response, 'Could not load notifications. Please try again.');
        if (!response.ok) throw new Error(result.detail || 'Could not load notifications.');
        const items = result.data?.notifications || [];
        container.replaceChildren();
        if (items.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'notifications-empty';
            empty.textContent = 'You have no new notifications.';
            container.appendChild(empty);
            return;
        }

        items.forEach(notification => {
            const item = document.createElement('div');
            item.className = `notification-item ${notification.is_read ? 'is-read' : 'is-unread'}`;
            const content = document.createElement('div');
            content.className = 'notification-content';
            const title = document.createElement('h4');
            title.className = 'notification-title';
            title.textContent = notification.title || '';
            const message = document.createElement('p');
            message.className = 'notification-message';
            message.textContent = notification.message || '';
            const date = document.createElement('small');
            date.className = 'notification-date';
            date.textContent = notification.created_at ? notification.created_at.substring(0, 16) : '';
            content.append(title, message, date);
            const actions = document.createElement('div');
            actions.className = 'notification-actions';
            if (!notification.is_read) {
                const button = document.createElement('button');
                button.className = 'notification-read-button';
                button.textContent = 'Mark as Read';
                button.addEventListener('click', () => markAsRead(notification.id));
                actions.appendChild(button);
            } else {
                const label = document.createElement('span');
                label.className = 'notification-read-label';
                label.textContent = 'Read';
                actions.appendChild(label);
            }
            item.append(content, actions);
            container.appendChild(item);
        });
    } catch (error) {
        container.textContent = error.message || 'Notifications could not be loaded.';
        console.error('Error loading notifications:', error);
    }
}

async function markAsRead(id) {
    try {
        const response = await fetch(`/api/notifications/${encodeURIComponent(id)}/read`, {
            method: 'PUT',
            credentials: 'include'
        });
        if (!response.ok) throw new Error('Could not update notification.');
        await loadNotifications();
    } catch (error) {
        console.error('Error updating notification:', error);
    }
}

loadNotifications();
