/**
 * Socket Base - SocketIO client connection, reconnect logic, and notification bell.
 * Included on every page via base.html.
 */

// Connect to SocketIO
const socket = io({
    transports: ['websocket', 'polling']
});

// --- Connection status indicator ---
socket.on('connect', () => {
    const indicator = document.getElementById('connection-status');
    if (indicator) indicator.classList.add('hidden');
});

socket.on('disconnect', () => {
    const indicator = document.getElementById('connection-status');
    if (indicator) indicator.classList.remove('hidden');
});

// --- Notification Bell ---
let notifications = [];
let unreadCount = 0;

// Initial data from server on connect
socket.on('dashboard:data', (data) => {
    if (data.recent_notifications) {
        notifications = data.recent_notifications;
        renderNotifications();
    }
    if (data.unread_notifications_count !== undefined) {
        unreadCount = data.unread_notifications_count;
        updateBadge();
    }
});

// New notification arrives
socket.on('notification:new', (data) => {
    notifications.unshift(data);
    if (notifications.length > 20) notifications.pop();
    unreadCount++;
    updateBadge();
    renderNotifications();
    showToast(data);
});

function updateBadge() {
    const badge = document.getElementById('notification-badge');
    if (!badge) return;
    if (unreadCount > 0) {
        badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

function renderNotifications() {
    const list = document.getElementById('notification-list');
    const empty = document.getElementById('notification-empty');
    if (!list) return;

    if (notifications.length === 0) {
        list.innerHTML = '';
        if (empty) empty.classList.remove('hidden');
        return;
    }

    if (empty) empty.classList.add('hidden');
    list.innerHTML = notifications.map(n => `
        <a href="${n.link || '#'}"
           class="block px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${n.is_read ? '' : 'bg-blue-50'}"
           onclick="markRead(${n.id})">
            <p class="text-sm font-medium text-gray-900">${escapeHtml(n.title)}</p>
            <p class="text-xs text-gray-500 mt-1">${escapeHtml(n.message)}</p>
            <p class="text-xs text-gray-400 mt-1">${formatTime(n.created_at)}</p>
        </a>
    `).join('');
}

function markRead(id) {
    socket.emit('notification:mark_read', { notification_id: id });
    const n = notifications.find(n => n.id === id);
    if (n && !n.is_read) {
        n.is_read = true;
        unreadCount = Math.max(0, unreadCount - 1);
        updateBadge();
    }
}

function markAllRead() {
    socket.emit('notification:mark_all_read', {});
    notifications.forEach(n => n.is_read = true);
    unreadCount = 0;
    updateBadge();
    renderNotifications();
}

function showToast(notification) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'bg-white border border-gray-200 rounded-lg shadow-lg p-4 mb-2 max-w-sm animate-slide-in';
    toast.innerHTML = `
        <p class="text-sm font-medium text-gray-900">${escapeHtml(notification.title)}</p>
        <p class="text-xs text-gray-500 mt-1">${escapeHtml(notification.message)}</p>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// --- Notification dropdown toggle ---
document.addEventListener('DOMContentLoaded', () => {
    const bell = document.getElementById('notification-bell');
    const dropdown = document.getElementById('notification-dropdown');

    if (bell && dropdown) {
        bell.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('hidden');
        });

        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && !bell.contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        });
    }

    const markAllBtn = document.getElementById('mark-all-read');
    if (markAllBtn) {
        markAllBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            markAllRead();
        });
    }
});

// --- Utilities ---
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);

    if (diffMin < 1) return 'Just now';
    if (diffMin < 60) return `${diffMin} min ago`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours} hr ago`;
    return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}
