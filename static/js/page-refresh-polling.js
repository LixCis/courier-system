/**
 * Universal page refresh polling for pages that don't have specific polling
 * SIMPLIFIED: Just reloads page when data changes
 */

(function() {
    // Don't initialize on pages that already have specific polling
    const path = window.location.pathname;

    // Skip if on dashboard (has specific polling)
    if (path.endsWith('/dashboard')) return;

    // Skip if on order detail (has specific polling)
    if (path.includes('/order/') && !path.includes('/orders')) return;

    // Skip if not authenticated
    if (!document.querySelector('nav')) return;

    // Determine role and API endpoint
    let role = null;
    let apiUrl = null;

    if (path.includes('/admin/')) {
        role = 'admin';
        apiUrl = '/api/admin/dashboard-data';
    } else if (path.includes('/restaurant/')) {
        role = 'restaurant';
        apiUrl = '/api/restaurant/dashboard-data';
    } else if (path.includes('/courier/')) {
        role = 'courier';
        apiUrl = '/api/courier/dashboard-data';
    }

    if (!apiUrl) {
        console.log('[page-refresh] No API URL determined, skipping');
        return;
    }

    console.log(`[page-refresh] Started for ${role} on ${path}`);

    // SIMPLIFIED: Just reload when autoRefresh detects any change
    window.autoRefresh.start('page-refresh', apiUrl, (data, hasChanged) => {
        console.log(`[page-refresh] hasChanged=${hasChanged}`);

        if (hasChanged) {
            console.log('[page-refresh] Change detected - reloading page...');

            // Show notification
            const notification = document.createElement('div');
            notification.className = 'fixed top-20 right-4 bg-blue-600 text-white px-4 py-2 rounded-lg shadow-lg z-50 text-sm';
            notification.textContent = 'Updates available - refreshing...';
            document.body.appendChild(notification);

            // Reload after short delay
            setTimeout(() => {
                window.location.reload();
            }, 500);
        }
    }, 3000);
})();
