/**
 * Dashboard AJAX updater - updates order lists without page refresh
 * Handles admin, restaurant, and courier dashboards
 */

class DashboardUpdater {
    constructor(role) {
        this.role = role;
        this.apiUrl = `/api/${role}/dashboard-data`;
        this.ordersContainer = null;
        this.lastOrderIds = new Set();
        this.isUpdating = false;
    }

    /**
     * Initialize the updater
     */
    init() {
        // Find the orders container based on role
        this.ordersContainer = this.findOrdersContainer();

        if (!this.ordersContainer) {
            console.warn(`[dashboard-updater] No orders container found for ${this.role}`);
            return;
        }

        console.log(`[dashboard-updater] Initialized for ${this.role}`);

        // Store initial order IDs
        this.updateOrderIdSet();

        // Start polling every 10 seconds
        window.autoRefresh.start('dashboard', this.apiUrl, (data, hasChanged) => {
            this.handleUpdate(data, hasChanged);
        }, 10000);
    }

    /**
     * Find the container element that holds order list
     */
    findOrdersContainer() {
        // Try multiple selectors
        const selectors = [
            '#orders-list',
            '[data-orders-list]',
            '.orders-list',
            'table tbody' // For admin tables
        ];

        for (const selector of selectors) {
            const elem = document.querySelector(selector);
            if (elem) return elem;
        }

        return null;
    }

    /**
     * Update internal set of order IDs
     */
    updateOrderIdSet() {
        this.lastOrderIds.clear();
        const orderElements = this.ordersContainer.querySelectorAll('[data-order-id]');
        orderElements.forEach(elem => {
            this.lastOrderIds.add(parseInt(elem.dataset.orderId));
        });
    }

    /**
     * Handle data update from server
     */
    handleUpdate(data, hasChanged) {
        if (!hasChanged) {
            console.log('[dashboard-updater] No changes detected');
            return;
        }

        if (this.isUpdating) {
            console.log('[dashboard-updater] Update already in progress, skipping');
            return;
        }

        console.log('[dashboard-updater] Changes detected, updating UI...');
        this.isUpdating = true;

        try {
            this.updateOrdersList(data);
            this.updateStats(data);
            window.autoRefresh.showToast('Dashboard updated', 'success');
        } catch (error) {
            console.error('[dashboard-updater] Error updating:', error);
        } finally {
            this.isUpdating = false;
        }
    }

    /**
     * Update the orders list
     */
    updateOrdersList(data) {
        const orders = data.orders || [];

        if (this.role === 'admin') {
            this.updateAdminOrdersTable(orders);
        } else {
            this.updateOrderCards(orders);
        }

        // Update stored order IDs
        this.updateOrderIdSet();
    }

    /**
     * Update admin table view
     */
    updateAdminOrdersTable(orders) {
        const tbody = this.ordersContainer;
        const currentIds = new Set(orders.map(o => o.id));

        // Remove deleted orders
        tbody.querySelectorAll('tr[data-order-id]').forEach(row => {
            const orderId = parseInt(row.dataset.orderId);
            if (!currentIds.has(orderId)) {
                row.remove();
            }
        });

        // Add/update orders
        orders.forEach(order => {
            const existingRow = tbody.querySelector(`tr[data-order-id="${order.id}"]`);

            if (existingRow) {
                // Update existing row
                this.updateOrderRow(existingRow, order);
            } else {
                // Add new row
                const newRow = this.createOrderRow(order);
                tbody.insertBefore(newRow, tbody.firstChild);
                window.autoRefresh.highlightElement(newRow);
            }
        });
    }

    /**
     * Update order cards view (restaurant/courier)
     */
    updateOrderCards(orders) {
        const container = this.ordersContainer;
        const currentIds = new Set(orders.map(o => o.id));

        // Remove deleted orders
        container.querySelectorAll('[data-order-id]').forEach(card => {
            const orderId = parseInt(card.dataset.orderId);
            if (!currentIds.has(orderId)) {
                card.remove();
            }
        });

        // Add/update orders
        orders.forEach(order => {
            const existingCard = container.querySelector(`[data-order-id="${order.id}"]`);

            if (existingCard) {
                // Update existing card
                this.updateOrderCard(existingCard, order);
            } else {
                // Add new card
                const newCard = this.createOrderCard(order);
                container.insertBefore(newCard, container.firstChild);
                window.autoRefresh.highlightElement(newCard);

                // Show notification for new order
                if (!this.lastOrderIds.has(order.id)) {
                    window.autoRefresh.showToast(`New order: #${order.order_number}`, 'info');
                }
            }
        });
    }

    /**
     * Update existing order row (admin)
     */
    updateOrderRow(row, order) {
        // Update status badge
        const statusCell = row.querySelector('[data-status]');
        if (statusCell && statusCell.dataset.status !== order.status) {
            statusCell.innerHTML = createStatusBadge(order.status);
            statusCell.dataset.status = order.status;
            window.autoRefresh.highlightElement(row);
        }

        // Update courier name
        const courierCell = row.querySelector('[data-courier]');
        if (courierCell) {
            const courierName = order.courier_name || '-';
            if (courierCell.textContent !== courierName) {
                courierCell.textContent = courierName;
                window.autoRefresh.highlightElement(courierCell);
            }
        }
    }

    /**
     * Update existing order card (restaurant/courier)
     */
    updateOrderCard(card, order) {
        // Update status badge
        const statusBadge = card.querySelector('[data-status]');
        if (statusBadge && statusBadge.dataset.status !== order.status) {
            const statusClass = order.status === 'delivered' ? 'bg-green-100 text-green-800' :
                                order.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                                ['assigned', 'picked_up', 'in_transit'].includes(order.status) ? 'bg-blue-100 text-blue-800' :
                                'bg-gray-100 text-gray-800';

            const statusText = order.status.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase());

            statusBadge.className = `inline-flex rounded-full px-3 py-1 text-xs font-semibold leading-5 ${statusClass}`;
            statusBadge.textContent = statusText;
            statusBadge.dataset.status = order.status;

            window.autoRefresh.highlightElement(card);

            // Show notification
            window.autoRefresh.showToast(
                `Order #${order.order_number} is now ${statusText}`,
                'info'
            );
        }

        // Update time info
        const timeElem = card.querySelector('[data-time]');
        if (timeElem && order.created_at) {
            timeElem.textContent = formatDateTime(order.created_at);
        }

        // Update courier info (restaurant view)
        const courierElem = card.querySelector('[data-courier]');
        if (courierElem && this.role === 'restaurant') {
            let newContent = '';
            if (order.courier_name) {
                newContent = `Courier: ${order.courier_name}`;
            } else {
                newContent = '<span class="text-yellow-600">Waiting for courier assignment</span>';
            }

            if (courierElem.innerHTML !== newContent) {
                courierElem.innerHTML = newContent;
                window.autoRefresh.highlightElement(courierElem);
            }
        }
    }

    /**
     * Create new order row HTML (admin)
     */
    createOrderRow(order) {
        const tr = document.createElement('tr');
        tr.dataset.orderId = order.id;
        tr.className = 'hover:bg-gray-50 cursor-pointer fade-in';
        tr.onclick = () => window.location.href = `/admin/order/${order.id}`;

        tr.innerHTML = `
            <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-900">${order.order_number}</td>
            <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500">${order.restaurant_name}</td>
            <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500" data-courier>${order.courier_name || '-'}</td>
            <td class="whitespace-nowrap px-3 py-4 text-sm" data-status="${order.status}">${createStatusBadge(order.status)}</td>
            <td class="whitespace-nowrap px-3 py-4 text-sm text-gray-500">${formatDateTime(order.created_at)}</td>
        `;

        return tr;
    }

    /**
     * Create new order card HTML (restaurant/courier)
     */
    createOrderCard(order) {
        const li = document.createElement('li');
        li.dataset.orderId = order.id;
        li.className = 'fade-in';

        const viewUrl = this.role === 'restaurant'
            ? `/restaurant/order/${order.id}`
            : `/courier/order/${order.id}`;

        let cardHTML = `
            <a href="${viewUrl}" class="block hover:bg-gray-50">
                <div class="px-4 py-4 sm:px-6">
                    <div class="flex items-center justify-between">
                        <div class="flex-1">
                            <p class="text-sm font-medium text-${this.role === 'restaurant' ? 'green' : 'blue'}-600">${order.order_number}</p>
        `;

        if (this.role === 'restaurant') {
            cardHTML += `
                            <p class="text-sm text-gray-500 mt-1">Customer: ${order.customer_name}</p>
                            <p class="text-xs text-gray-400 mt-1">${order.delivery_address || ''}</p>
            `;
        } else if (this.role === 'courier') {
            cardHTML += `
                            <p class="text-sm text-gray-500 mt-1">${order.restaurant_name}</p>
            `;
        }

        cardHTML += `
                        </div>
                        <div class="ml-2 flex-shrink-0">
                            <span data-status="${order.status}" class="inline-flex rounded-full px-3 py-1 text-xs font-semibold leading-5
                                ${order.status === 'delivered' ? 'bg-green-100 text-green-800' :
                                  order.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                                  order.status in ['assigned', 'picked_up', 'in_transit'] ? 'bg-blue-100 text-blue-800' :
                                  'bg-gray-100 text-gray-800'}">
                                ${order.status.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
                            </span>
                        </div>
                    </div>
                    <div class="mt-2 sm:flex sm:justify-between">
                        <div class="sm:flex">
                            <p class="flex items-center text-sm text-gray-500">
                                <span data-courier>
        `;

        if (this.role === 'restaurant') {
            if (order.courier_name) {
                cardHTML += `Courier: ${order.courier_name}`;
            } else {
                cardHTML += `<span class="text-yellow-600">Waiting for courier assignment</span>`;
            }
        } else if (this.role === 'courier') {
            cardHTML += `<span class="font-medium">Pickup:</span> ${order.pickup_address || ''}`;
        }

        cardHTML += `
                                </span>
                            </p>
                        </div>
                        <div class="mt-2 flex items-center text-sm text-gray-500 sm:mt-0">
                            <p data-time>${formatDateTime(order.created_at)}</p>
                        </div>
                    </div>
                </div>
            </a>
        `;

        li.innerHTML = cardHTML;
        return li;
    }

    /**
     * Update statistics/counts on dashboard
     */
    updateStats(data) {
        // Update stats if present in data
        if (data.stats) {
            Object.keys(data.stats).forEach(key => {
                const elem = document.querySelector(`[data-stat="${key}"]`);
                if (elem) {
                    elem.textContent = data.stats[key];
                }
            });
        }
    }
}

// Auto-initialize on dashboard pages
(function() {
    const path = window.location.pathname;

    // Determine role
    let role = null;
    if (path.includes('/admin/dashboard')) role = 'admin';
    else if (path.includes('/restaurant/dashboard')) role = 'restaurant';
    else if (path.includes('/courier/dashboard')) role = 'courier';

    if (role) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                setTimeout(() => {
                    const updater = new DashboardUpdater(role);
                    updater.init();
                }, 100);
            });
        } else {
            setTimeout(() => {
                const updater = new DashboardUpdater(role);
                updater.init();
            }, 100);
        }
    }
})();

console.log('Dashboard updater loaded');
