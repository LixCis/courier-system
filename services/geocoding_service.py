"""
Geocoding Service

Converts street addresses to GPS coordinates using the free Nominatim API (OpenStreetMap).
Implements rate limiting and caching to comply with Nominatim's usage policy.
"""

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import time


class GeocodingService:
    """
    Geocoding service using Nominatim (OpenStreetMap)

    Features:
    - Free, no API key required
    - Automatic rate limiting (1 request per second as per ToS)
    - Caches results in database to minimize API calls
    - Graceful error handling
    """

    def __init__(self):
        """Initialize geocoder with required User-Agent"""
        self.geolocator = Nominatim(user_agent="courier-system-v1")
        self.last_request = 0

    def geocode_address(self, address):
        """
        Convert address string to GPS coordinates

        Args:
            address (str): Street address to geocode

        Returns:
            tuple: (latitude, longitude) or (None, None) if geocoding fails

        Example:
            >>> service = GeocodingService()
            >>> lat, lon = service.geocode_address("Wenceslas Square, Prague")
            >>> print(lat, lon)
            50.0814 14.4266
        """
        try:
            # Rate limit: 1 request per second (Nominatim ToS requirement)
            now = time.time()
            elapsed = now - self.last_request
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)

            self.last_request = time.time()

            # Geocode the address
            location = self.geolocator.geocode(address, timeout=5)

            if location:
                return location.latitude, location.longitude

        except GeocoderTimedOut:
            print(f"Geocoding timeout for '{address}'")
        except Exception as e:
            print(f"Geocoding failed for '{address}': {e}")

        return None, None

    def geocode_order(self, order):
        """
        Geocode order's pickup and delivery addresses if not already done

        NOTE: With map-based order creation, GPS coordinates are always provided
        from the frontend, so this method typically does nothing. It only geocodes
        if coordinates are missing (legacy data or external integrations).

        Stores coordinates directly in the Order object and commits to database.
        Uses existing coordinates if already geocoded (cache).

        Args:
            order (Order): Order object to geocode

        Returns:
            None (modifies order object in place and commits to database)

        Example:
            >>> service = GeocodingService()
            >>> order = Order.query.get(1)
            >>> service.geocode_order(order)
            >>> print(order.pickup_latitude, order.pickup_longitude)
            50.0755 14.4378
        """
        from models import db

        # Geocode pickup address if not already done (fallback for legacy/external data)
        if not order.pickup_latitude and order.pickup_address:
            lat, lon = self.geocode_address(order.pickup_address)
            if lat:
                order.pickup_latitude = lat
                order.pickup_longitude = lon
                print(f"Geocoded pickup address: {order.pickup_address} -> ({lat}, {lon})")

        # Geocode delivery address if not already done (fallback for legacy/external data)
        if not order.delivery_latitude and order.delivery_address:
            lat, lon = self.geocode_address(order.delivery_address)
            if lat:
                order.delivery_latitude = lat
                order.delivery_longitude = lon
                print(f"Geocoded delivery address: {order.delivery_address} -> ({lat}, {lon})")

        # Save to database
        db.session.commit()

    def reverse_geocode(self, latitude, longitude):
        """
        Convert GPS coordinates to a human-readable address

        Args:
            latitude (float): Latitude coordinate
            longitude (float): Longitude coordinate

        Returns:
            str: Address string or None if reverse geocoding fails

        Example:
            >>> service = GeocodingService()
            >>> address = service.reverse_geocode(49.8209, 18.2625)
            >>> print(address)
            'Ostrava, Czech Republic'
        """
        try:
            now = time.time()
            elapsed = now - self.last_request
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)

            self.last_request = time.time()

            location = self.geolocator.reverse((latitude, longitude), timeout=5)

            if location:
                return location.address

        except GeocoderTimedOut:
            print(f"Reverse geocoding timeout for ({latitude}, {longitude})")
        except Exception as e:
            print(f"Reverse geocoding failed for ({latitude}, {longitude}): {e}")

        return None
