/**
 * Order Detail AJAX updater - updates order details without page refresh
 * Handles admin, restaurant, and courier order detail pages
 */

class OrderDetailUpdater {
    constructor(role, orderId) {
        this.role = role;
        this.orderId = orderId;
        this.apiUrl = `/api/${role}/order/${orderId}`;
        this.currentStatus = null;
        this.lastLogsCount = 0;
        this.isUpdating = false;
    }

    /**
     * Initialize the updater
     */
    init() {
        console.log(`[order-detail-updater] Initialized for ${this.role} - Order #${this.orderId}`);

        // Store initial state
        this.currentStatus = this.getCurrentStatus();
        this.lastLogsCount = this.getLogsCount();

        // Start polling every 5 seconds
        window.autoRefresh.start('order-detail', this.apiUrl, (data, hasChanged) => {
            this.handleUpdate(data, hasChanged);
        }, 5000);
    }

    /**
     * Get current status from page
     */
    getCurrentStatus() {
        const statusBadge = document.querySelector('[data-order-status]');
        return statusBadge ? statusBadge.dataset.orderStatus : null;
    }

    /**
     * Get current logs count
     */
    getLogsCount() {
        const logsContainer = document.querySelector('[data-delivery-logs]');
        if (!logsContainer) return 0;
        return logsContainer.querySelectorAll('[data-log-entry]').length;
    }

    /**
     * Handle data update from server
     */
    handleUpdate(data, hasChanged) {
        if (!hasChanged && !data.auto_transitioned) {
            return;
        }

        console.log('[order-detail-updater] Changes detected, reloading page...');

        // Just reload the page to show all updates (metrics, buttons, logs, etc.)
        window.autoRefresh.showToast('Order updated - refreshing...', 'info');
        setTimeout(() => {
            window.location.reload();
        }, 500);
    }

    /**
     * Update order status badge
     */
    updateStatus(order) {
        const statusContainer = document.querySelector('[data-order-status]');
        if (!statusContainer) return;

        const statusClass = order.status === 'delivered' ? 'bg-green-100 text-green-800' :
                            order.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                            order.status === 'cancelled' ? 'bg-red-100 text-red-800' :
                            ['assigned', 'picked_up', 'in_transit'].includes(order.status) ? 'bg-blue-100 text-blue-800' :
                            'bg-gray-100 text-gray-800';

        const statusText = order.status.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());

        statusContainer.className = `inline-flex rounded-full px-4 py-2 text-sm font-semibold ${statusClass}`;
        statusContainer.textContent = statusText;
        statusContainer.dataset.orderStatus = order.status;

        window.autoRefresh.highlightElement(statusContainer.parentElement);
    }

    /**
     * Update action buttons based on status
     */
    updateActionButtons(order) {
        const actionsContainer = document.querySelector('[data-order-actions]');
        if (!actionsContainer) return;

        // For courier: show appropriate action buttons
        if (this.role === 'courier' && order.status !== 'delivered') {
            const buttons = this.generateCourierActionButtons(order);
            actionsContainer.innerHTML = buttons;
            window.autoRefresh.highlightElement(actionsContainer);
        }
    }

    /**
     * Generate courier action buttons HTML
     */
    generateCourierActionButtons(order) {
        if (order.status === 'assigned') {
            return `
                <button onclick="updateStatus('picked_up')"
                        class="w-full inline-flex justify-center items-center rounded-md border border-transparent bg-blue-600 px-6 py-3 text-base font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">
                    <svg class="h-5 w-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Mark as Picked Up
                </button>
            `;
        } else if (order.status === 'picked_up') {
            return `
                <button onclick="updateStatus('in_transit')"
                        class="w-full inline-flex justify-center items-center rounded-md border border-transparent bg-indigo-600 px-6 py-3 text-base font-semibold text-white shadow-sm hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2">
                    <svg class="h-5 w-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6" />
                    </svg>
                    Mark as In Transit
                </button>
            `;
        } else if (order.status === 'in_transit') {
            return `
                <form action="/courier/order/${order.id}/update" method="POST" enctype="multipart/form-data">
                    <input type="hidden" name="status" value="delivered">
                    <div class="mb-4 bg-green-50 border border-green-200 rounded-lg p-4">
                        <label class="block text-sm font-medium text-green-900 mb-2">
                            Upload Delivery Proof Photo (Optional)
                        </label>
                        <input type="file" name="delivery_proof" accept="image/*" capture="environment"
                               class="block w-full text-sm text-gray-900 border border-gray-300 rounded-lg cursor-pointer bg-white focus:outline-none">
                        <p class="mt-1 text-xs text-green-700">Take a photo of the delivered order</p>
                    </div>
                    <button type="submit"
                            class="w-full inline-flex justify-center items-center rounded-md border border-transparent bg-green-600 px-6 py-4 text-lg font-bold text-white shadow-lg hover:bg-green-700 focus:outline-none focus:ring-4 focus:ring-green-500 focus:ring-offset-2">
                        <svg class="h-6 w-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                        </svg>
                        Mark as Delivered
                    </button>
                </form>
            `;
        }

        return '';
    }

    /**
     * Update delivery logs
     */
    updateDeliveryLogs(logs) {
        const logsContainer = document.querySelector('[data-delivery-logs]');
        if (!logsContainer) return;

        // Clear and rebuild logs
        logsContainer.innerHTML = logs.map(log => this.createLogEntry(log)).join('');
        window.autoRefresh.highlightElement(logsContainer);
    }

    /**
     * Create log entry HTML
     */
    createLogEntry(log) {
        const icon = this.getLogIcon(log.event_type);
        const color = this.getLogColor(log.event_type);

        return `
            <div class="relative pb-8" data-log-entry>
                <div class="relative flex items-start space-x-3">
                    <div class="relative">
                        <div class="${color} h-8 w-8 rounded-full flex items-center justify-center ring-8 ring-white">
                            ${icon}
                        </div>
                    </div>
                    <div class="min-w-0 flex-1">
                        <div>
                            <div class="text-sm text-gray-900">
                                ${log.event_description}
                            </div>
                            <p class="mt-0.5 text-xs text-gray-500">
                                ${formatDateTime(log.timestamp)} · ${log.user_role || 'System'}
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Get icon for log type
     */
    getLogIcon(eventType) {
        const icons = {
            'order_created': '<svg class="h-5 w-5 text-white" fill="currentColor" viewBox="0 0 20 20"><path d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V7z"/></svg>',
            'auto_assignment': '<svg class="h-5 w-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>',
            'status_update': '<svg class="h-5 w-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
            'order_rejected': '<svg class="h-5 w-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>'
        };
        return icons[eventType] || icons['status_update'];
    }

    /**
     * Get color for log type
     */
    getLogColor(eventType) {
        const colors = {
            'order_created': 'bg-green-500',
            'auto_assignment': 'bg-blue-500',
            'status_update': 'bg-indigo-500',
            'order_rejected': 'bg-red-500'
        };
        return colors[eventType] || 'bg-gray-500';
    }

    /**
     * Update courier information
     */
    updateCourierInfo(order) {
        const courierElem = document.querySelector('[data-courier-info]');
        if (!courierElem) return;

        let newHTML = '';
        if (order.courier_name) {
            newHTML = order.courier_name;
        } else {
            newHTML = '<span class="text-yellow-600">Not assigned yet</span>';
        }

        if (courierElem.innerHTML !== newHTML) {
            courierElem.innerHTML = newHTML;
            window.autoRefresh.highlightElement(courierElem);
        }
    }

    /**
     * Update timestamps
     */
    updateTimestamps(order) {
        const timestampFields = [
            'assigned_at', 'picked_up_at', 'in_transit_at', 'delivered_at'
        ];

        timestampFields.forEach(field => {
            const elem = document.querySelector(`[data-timestamp="${field}"]`);
            if (elem && order[field]) {
                elem.textContent = formatDateTime(order[field]);
            }
        });
    }

    /**
     * Update order details
     */
    updateOrderDetails(order) {
        // Update estimated times if present
        if (order.estimated_total_time) {
            const estimateElem = document.querySelector('[data-estimated-time]');
            if (estimateElem) {
                estimateElem.textContent = `${order.estimated_total_time} min`;
            }
        }
    }
}

// Auto-initialize on order detail pages
(function() {
    const path = window.location.pathname;

    // Check if on order detail page
    if (!path.includes('/order/') || path.includes('/create')) {
        return;
    }

    // Determine role and order ID
    let role = null;
    const pathParts = path.split('/');
    const orderId = pathParts[pathParts.length - 1];

    if (path.includes('/admin/')) role = 'admin';
    else if (path.includes('/restaurant/')) role = 'restaurant';
    else if (path.includes('/courier/')) role = 'courier';

    if (role && orderId) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                setTimeout(() => {
                    const updater = new OrderDetailUpdater(role, orderId);
                    updater.init();
                }, 100);
            });
        } else {
            setTimeout(() => {
                const updater = new OrderDetailUpdater(role, orderId);
                updater.init();
            }, 100);
        }
    }
})();

console.log('Order detail updater loaded');
