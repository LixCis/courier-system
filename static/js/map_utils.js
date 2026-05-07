/**
 * Map Utilities - Leaflet map initialization, marker management, and OSRM routing.
 * Included on every page via base.html. Functions are called by page-specific scripts.
 */

// Ostrava center coordinates
const OSTRAVA_CENTER = [49.8209, 18.2625];
const DEFAULT_ZOOM = 13;

// Custom marker icons using Leaflet divIcon (no external images needed)
function createIcon(color, label) {
    return L.divIcon({
        className: 'custom-marker',
        html: `<div style="
            background-color: ${color};
            width: 28px; height: 28px;
            border-radius: 50%;
            border: 3px solid white;
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
            display: flex; align-items: center; justify-content: center;
            color: white; font-size: 12px; font-weight: bold;
        ">${label || ''}</div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -16]
    });
}

const ICONS = {
    courierAvailable: createIcon('#10b981', ''),      // green
    courierBusy: createIcon('#f59e0b', ''),            // orange
    courierUnavailable: createIcon('#9ca3af', ''),     // gray
    pickup: createIcon('#3b82f6', 'P'),                // blue with P
    delivery: createIcon('#ef4444', 'D'),              // red with D
    courierPosition: createIcon('#6366f1', 'C')        // indigo with C
};

function getCourierIcon(courier) {
    if (!courier.is_available) return ICONS.courierUnavailable;
    if (courier.active_orders_count > 0) return ICONS.courierBusy;
    return ICONS.courierAvailable;
}

/**
 * Initialize a Leaflet map in a container.
 * @param {string} containerId - DOM element ID
 * @param {object} options - { center, zoom, fitBounds }
 * @returns {L.Map}
 */
function initMap(containerId, options = {}) {
    const center = options.center || OSTRAVA_CENTER;
    const zoom = options.zoom || DEFAULT_ZOOM;

    const map = L.map(containerId).setView(center, zoom);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(map);

    return map;
}

/**
 * Draw a driving route between two points using OSRM.
 * @param {L.Map} map
 * @param {Array} start - [lat, lng]
 * @param {Array} end - [lat, lng]
 * @param {object} options - { color, weight, dashArray, containerId }
 * @returns {Promise<L.Polyline|null>}
 */
async function drawRoute(map, start, end, options = {}) {
    const color = options.color || '#3b82f6';
    const weight = options.weight || 4;
    const containerId = options.containerId;

    // Show loading spinner if container provided
    if (containerId) {
        const container = document.getElementById(containerId);
        if (container) {
            const spinner = document.createElement('div');
            spinner.id = `${containerId}-spinner`;
            spinner.className = 'absolute inset-0 flex items-center justify-center bg-white bg-opacity-50 rounded-lg z-10';
            spinner.innerHTML = '<svg class="animate-spin h-6 w-6 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>';
            container.style.position = 'relative';
            container.appendChild(spinner);
        }
    }

    try {
        const url = `https://router.project-osrm.org/route/v1/driving/${start[1]},${start[0]};${end[1]},${end[0]}?overview=full&geometries=geojson`;
        const response = await fetch(url);
        const data = await response.json();

        if (data.code === 'Ok' && data.routes.length > 0) {
            const coords = data.routes[0].geometry.coordinates.map(c => [c[1], c[0]]);
            const polyline = L.polyline(coords, {
                color: color,
                weight: weight,
                opacity: 0.7,
                dashArray: options.dashArray || null
            }).addTo(map);

            // Remove spinner on success
            if (containerId) {
                const spinner = document.getElementById(`${containerId}-spinner`);
                if (spinner) spinner.remove();
            }
            return polyline;
        }
    } catch (e) {
        console.warn('OSRM routing failed, drawing straight line:', e);
    }

    // Fallback: straight line
    const polyline = L.polyline([start, end], {
        color: color,
        weight: weight,
        opacity: 0.5,
        dashArray: '10, 10'
    }).addTo(map);

    // Show error toast if container provided
    if (containerId) {
        const spinner = document.getElementById(`${containerId}-spinner`);
        if (spinner) spinner.remove();
        showRouteErrorToast();
    }
    return polyline;
}

/**
 * Show toast message when route unavailable
 */
function showRouteErrorToast() {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'bg-yellow-50 border border-yellow-200 rounded-lg shadow-lg p-4 mb-2 max-w-sm animate-slide-in';
    toast.innerHTML = `
        <p class="text-sm font-medium text-yellow-800">Route unavailable</p>
        <p class="text-xs text-yellow-700 mt-1">Showing direct line between locations</p>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

/**
 * Add order pickup + delivery markers and route to a map.
 * @param {L.Map} map
 * @param {object} order - { pickup_latitude, pickup_longitude, delivery_latitude, delivery_longitude, ... }
 * @param {object} options - { routeColor }
 * @returns {Promise<{pickupMarker, deliveryMarker, route}>}
 */
async function addOrderToMap(map, order, options = {}) {
    const result = { pickupMarker: null, deliveryMarker: null, route: null };

    if (order.pickup_latitude && order.pickup_longitude) {
        result.pickupMarker = L.marker(
            [order.pickup_latitude, order.pickup_longitude],
            { icon: ICONS.pickup }
        ).addTo(map);
        result.pickupMarker.bindPopup(`<b>Pickup</b><br>${order.pickup_address || order.restaurant_name || ''}`);
    }

    if (order.delivery_latitude && order.delivery_longitude) {
        result.deliveryMarker = L.marker(
            [order.delivery_latitude, order.delivery_longitude],
            { icon: ICONS.delivery }
        ).addTo(map);
        result.deliveryMarker.bindPopup(`<b>Delivery</b><br>${order.delivery_address || ''}<br>${order.customer_name || ''}`);
    }

    if (result.pickupMarker && result.deliveryMarker) {
        result.route = await drawRoute(
            map,
            [order.pickup_latitude, order.pickup_longitude],
            [order.delivery_latitude, order.delivery_longitude],
            { color: options.routeColor || '#3b82f6', containerId: options.containerId }
        );

        // Fit map to show both markers
        const bounds = L.latLngBounds(
            [order.pickup_latitude, order.pickup_longitude],
            [order.delivery_latitude, order.delivery_longitude]
        );
        map.fitBounds(bounds.pad(0.2));
    }

    return result;
}

/**
 * Fit map bounds to include all given markers.
 * @param {L.Map} map
 * @param {Array<L.Marker>} markers
 */
function fitMapToMarkers(map, markers) {
    const validMarkers = markers.filter(m => m !== null);
    if (validMarkers.length === 0) return;

    if (validMarkers.length === 1) {
        map.setView(validMarkers[0].getLatLng(), 15);
        return;
    }

    const group = L.featureGroup(validMarkers);
    map.fitBounds(group.getBounds().pad(0.15));
}
