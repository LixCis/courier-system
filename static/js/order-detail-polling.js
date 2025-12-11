/**
 * Universal order detail polling for all roles
 * SIMPLIFIED: Just reloads page when any data changes
 */

function initOrderDetailPolling() {
    // Extract order ID from URL path
    const pathParts = window.location.pathname.split('/');
    const orderId = pathParts[pathParts.length - 1];

    // Determine role from URL
    let role = 'admin';
    if (pathParts[1] === 'restaurant') role = 'restaurant';
    else if (pathParts[1] === 'courier') role = 'courier';

    const apiUrl = `/api/${role}/order/${orderId}`;

    console.log(`[order-detail] Starting polling for ${role} - Order #${orderId}`);

    // Reload when autoRefresh detects change OR when auto_transition flag is set
    window.autoRefresh.start('order-detail', apiUrl, (data, hasChanged) => {
        console.log(`[order-detail] Poll result:`, {
            hasChanged,
            auto_transitioned: data.auto_transitioned,
            status: data.order.status,
            logs_count: data.logs.length
        });

        // Force reload if this order was just auto-transitioned by Python
        if (data.auto_transitioned) {
            console.log('[order-detail] >> Auto-transition flag TRUE - reloading page!');
            window.autoRefresh.showToast('Order status updated - refreshing...', 'info');
            setTimeout(() => window.location.reload(), 500);
            return;
        }

        // Also reload on any other detected changes
        if (hasChanged) {
            console.log('[order-detail] >> hasChanged TRUE - reloading page!');
            window.autoRefresh.showToast('Order updated - refreshing...', 'info');
            setTimeout(() => window.location.reload(), 500);
        } else {
            console.log('[order-detail] No changes, continuing to poll...');
        }
    }, 2000);
}

// Auto-initialize if on order detail page
if (window.location.pathname.includes('/order/') &&
    !window.location.pathname.includes('/create') &&
    (window.location.pathname.includes('/admin/') ||
     window.location.pathname.includes('/restaurant/') ||
     window.location.pathname.includes('/courier/'))) {
    // Wait for DOM and autoRefresh to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            setTimeout(initOrderDetailPolling, 100);
        });
    } else {
        setTimeout(initOrderDetailPolling, 100);
    }
}
