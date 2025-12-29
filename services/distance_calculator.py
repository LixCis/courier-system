"""
Distance Calculator Service

Calculates straight-line distance between two GPS coordinates using the Haversine formula.
This is used for courier assignment optimization.
"""

from math import radians, cos, sin, asin, sqrt, ceil


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance in kilometers between two GPS points using Haversine formula

    Args:
        lat1, lon1: Latitude and longitude of first point (decimal degrees)
        lat2, lon2: Latitude and longitude of second point (decimal degrees)

    Returns:
        float: Distance in kilometers, or None if any coordinate is missing

    Example:
        >>> haversine_distance(50.0755, 14.4378, 50.0875, 14.4214)  # Prague locations
        1.23  # km
    """
    # Check if all coordinates are provided
    if not all([lat1, lon1, lat2, lon2]):
        return None

    # Earth radius in kilometers
    R = 6371.0

    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))

    # Calculate distance
    distance = R * c

    return distance


def estimate_travel_time(distance_km, vehicle_type='bike'):
    """
    Estimate travel time based on distance and vehicle type
    Uses conservative speeds accounting for traffic, stops, parking

    Args:
        distance_km (float): Distance in kilometers
        vehicle_type (str): Type of vehicle ('bike', 'scooter', 'motorcycle', 'car', 'van')

    Returns:
        int: Estimated time in minutes (with safety buffer)

    Speed assumptions (accounting for urban traffic):
    - bike: 12 km/h (slow but flexible)
    - scooter: 18 km/h
    - motorcycle: 25 km/h
    - car: 20 km/h (slower in city traffic)
    - van: 20 km/h

    Safety buffer: +20% extra time for unexpected delays
    """
    if not distance_km:
        return 0

    # Average speeds in km/h (conservative for urban delivery)
    speed_map = {
        'bike': 12,
        'scooter': 18,
        'motorcycle': 25,
        'car': 20,
        'van': 20
    }

    # Default to bike speed if vehicle type unknown
    speed_kmh = speed_map.get(vehicle_type, 12)

    # Calculate base time in minutes
    base_time_minutes = (distance_km / speed_kmh) * 60

    # Add 20% safety buffer for traffic, lights, parking
    buffered_time = base_time_minutes * 1.2

    # Add 2-minute base overhead for parking/getting organized
    total_time = buffered_time + 2

    # Round up to nearest minute
    return ceil(total_time)


def calculate_delivery_estimates(courier_lat, courier_lon, pickup_lat, pickup_lon,
                                 delivery_lat, delivery_lon, vehicle_type='bike'):
    """
    Calculate estimated pickup and delivery times for an order

    Args:
        courier_lat/lon: Courier's current location
        pickup_lat/lon: Restaurant pickup location
        delivery_lat/lon: Customer delivery location
        vehicle_type: Courier's vehicle type

    Returns:
        dict with:
        - pickup_time: Minutes for courier to reach restaurant
        - delivery_time: Minutes from restaurant to customer
        - total_time: Total estimated time
        - pickup_distance: Distance to restaurant (km)
        - delivery_distance: Distance to customer (km)
    """
    # Calculate distances
    pickup_distance = haversine_distance(courier_lat, courier_lon, pickup_lat, pickup_lon)
    delivery_distance = haversine_distance(pickup_lat, pickup_lon, delivery_lat, delivery_lon)

    if not pickup_distance or not delivery_distance:
        return None

    # Calculate times
    pickup_time = estimate_travel_time(pickup_distance, vehicle_type)
    delivery_time = estimate_travel_time(delivery_distance, vehicle_type)

    # Add 3-minute buffer for order preparation/pickup at restaurant
    pickup_time += 3

    return {
        'pickup_time': pickup_time,
        'delivery_time': delivery_time,
        'total_time': pickup_time + delivery_time,
        'pickup_distance': round(pickup_distance, 2),
        'delivery_distance': round(delivery_distance, 2)
    }
