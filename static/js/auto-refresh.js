/**
 * Auto-refresh polling system for real-time updates
 * Supports different intervals for different priorities
 */

class AutoRefresh {
    constructor() {
        this.intervals = {};
        this.lastData = {};
        this.isPageVisible = true;
        this.toastContainer = null;

        // Setup page visibility detection
        document.addEventListener('visibilitychange', () => {
            this.isPageVisible = !document.hidden;
            if (this.isPageVisible) {
                console.log('Page visible - resuming polling');
                this.refreshAll();
            } else {
                console.log('Page hidden - polling continues but with lower priority');
            }
        });

        // Create toast container
        this.createToastContainer();
    }

    /**
     * Start polling for a specific endpoint
     * @param {string} name - Unique name for this polling task
     * @param {string} url - API endpoint URL
     * @param {function} callback - Function to call with data
     * @param {number} interval - Polling interval in milliseconds
     */
    start(name, url, callback, interval = 1000) {
        // Clear existing interval if any
        this.stop(name);

        // Initial fetch
        this.fetchAndUpdate(name, url, callback);

        // Setup interval
        this.intervals[name] = setInterval(() => {
            // Only poll if page is visible or it's high priority
            if (this.isPageVisible || interval >= 5000) {
                this.fetchAndUpdate(name, url, callback);
            }
        }, interval);

        console.log(`Started polling: ${name} (${interval}ms interval)`);
    }

    /**
     * Stop polling for a specific task
     */
    stop(name) {
        if (this.intervals[name]) {
            clearInterval(this.intervals[name]);
            delete this.intervals[name];
            console.log(`Stopped polling: ${name}`);
        }
    }

    /**
     * Stop all polling
     */
    stopAll() {
        Object.keys(this.intervals).forEach(name => this.stop(name));
    }

    /**
     * Refresh all active pollers immediately
     */
    refreshAll() {
        Object.keys(this.intervals).forEach(name => {
            // Trigger immediate fetch by clearing and restarting
            const interval = this.intervals[name];
            if (interval) {
                clearInterval(interval);
                // Re-setup will happen automatically
            }
        });
    }

    /**
     * Fetch data and call callback if changed
     */
    async fetchAndUpdate(name, url, callback) {
        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'same-origin'
            });

            if (!response.ok) {
                if (response.status === 401 || response.status === 403) {
                    console.warn(`Unauthorized access for ${name} - stopping polling`);
                    this.stop(name);
                    return;
                }
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();

            // Check if data changed
            const dataStr = JSON.stringify(data);
            const hasChanged = this.lastData[name] !== dataStr;

            if (hasChanged) {
                const isFirstLoad = !this.lastData[name];

                // Debug logging
                if (!isFirstLoad) {
                    console.log(`[${name}] Data changed, updating...`);
                    console.log('Old data:', this.lastData[name]);
                    console.log('New data:', dataStr);
                }

                this.lastData[name] = dataStr;

                // Call callback with data and change info
                callback(data, !isFirstLoad);
            } else {
                // Log no change for debugging
                // console.log(`[${name}] No change detected`);
            }

        } catch (error) {
            console.error(`Error fetching ${name}:`, error);
            // Don't stop on errors, just log them
        }
    }

    /**
     * Create toast container for notifications
     */
    createToastContainer() {
        this.toastContainer = document.createElement('div');
        this.toastContainer.id = 'toast-container';
        this.toastContainer.className = 'fixed top-4 right-4 z-50 space-y-2';
        document.body.appendChild(this.toastContainer);
    }

    /**
     * Show toast notification
     */
    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        const colors = {
            info: 'bg-blue-600',
            success: 'bg-green-600',
            warning: 'bg-yellow-600',
            error: 'bg-red-600'
        };

        toast.className = `${colors[type]} text-white px-4 py-3 rounded-lg shadow-lg transition-all transform translate-x-0 opacity-100`;
        toast.textContent = message;

        this.toastContainer.appendChild(toast);

        // Auto remove after 3 seconds
        setTimeout(() => {
            toast.classList.add('opacity-0', 'translate-x-full');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    /**
     * Highlight element with animation
     */
    highlightElement(element) {
        if (!element) return;

        element.classList.add('highlight-flash');
        setTimeout(() => {
            element.classList.remove('highlight-flash');
        }, 1000);
    }

    /**
     * Fade in new element
     */
    fadeInElement(element) {
        if (!element) return;

        element.classList.add('opacity-0');
        setTimeout(() => {
            element.classList.remove('opacity-0');
            element.classList.add('transition-opacity', 'duration-500');
        }, 10);
    }
}

// Global instance
window.autoRefresh = new AutoRefresh();

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    window.autoRefresh.stopAll();
});

/**
 * Status badge color mapping
 */
const STATUS_COLORS = {
    'pending': 'bg-yellow-100 text-yellow-800',
    'assigned': 'bg-blue-100 text-blue-800',
    'picked_up': 'bg-indigo-100 text-indigo-800',
    'in_transit': 'bg-purple-100 text-purple-800',
    'delivered': 'bg-green-100 text-green-800',
    'cancelled': 'bg-red-100 text-red-800'
};

const STATUS_LABELS = {
    'pending': 'Pending',
    'assigned': 'Assigned',
    'picked_up': 'Picked Up',
    'in_transit': 'In Transit',
    'delivered': 'Delivered',
    'cancelled': 'Cancelled'
};

/**
 * Create status badge HTML
 */
function createStatusBadge(status, size = 'default') {
    const sizeClasses = size === 'large' ? 'px-3 py-1.5 text-sm' : 'px-2.5 py-0.5 text-xs';
    return `<span class="inline-flex items-center rounded-full font-medium ${STATUS_COLORS[status]} ${sizeClasses}">
        ${STATUS_LABELS[status] || status}
    </span>`;
}

/**
 * Format date/time
 */
function formatDateTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleString('cs-CZ', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Format relative time (e.g., "5 minutes ago")
 */
function formatRelativeTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'právě teď';
    if (diffMins < 60) return `před ${diffMins} min`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `před ${diffHours} h`;
    const diffDays = Math.floor(diffHours / 24);
    return `před ${diffDays} dny`;
}

/**
 * Format currency
 */
function formatCurrency(value) {
    return new Intl.NumberFormat('cs-CZ', {
        style: 'currency',
        currency: 'CZK'
    }).format(value || 0);
}

console.log('Auto-refresh system loaded');
