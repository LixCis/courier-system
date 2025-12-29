"""
Order Assignment Algorithm Service

This module handles automatic assignment of orders to couriers.
It's designed to be modular and easily replaceable with AI-based algorithms.

Current Implementation: Simple First-Available Strategy
Future: Can be replaced with ML-based optimization
"""

from models import User, Order, DeliveryLog, db
from datetime import datetime


class AssignmentStrategy:
    """Base class for assignment strategies - allows easy swapping"""

    def assign_courier(self, order, excluded_courier_ids=None):
        """
        Assign a courier to an order

        Args:
            order: Order object to assign
            excluded_courier_ids: Optional list of courier IDs to exclude from assignment (e.g., who recently rejected)

        Returns: User object (courier) or None
        """
        raise NotImplementedError("Subclasses must implement assign_courier")


class FirstAvailableStrategy(AssignmentStrategy):
    """
    Simple strategy: Assigns to the first available courier
    This is the MVP implementation that can be easily replaced
    """

    def assign_courier(self, order, excluded_courier_ids=None):
        """
        Find the first available courier and assign the order

        Logic:
        1. Find couriers who are marked as available
        2. Exclude specific couriers if requested (e.g., who recently rejected)
        3. Check that courier has less than 2 active orders
        4. Return the first match
        """
        from sqlalchemy import func

        if excluded_courier_ids is None:
            excluded_courier_ids = []

        # Subquery to count active orders per courier
        active_orders_count = db.session.query(
            Order.courier_id,
            func.count(Order.id).label('active_count')
        ).filter(
            Order.status.in_(['assigned', 'picked_up', 'in_transit'])
        ).group_by(Order.courier_id).subquery()

        # Build query for available couriers with less than 2 active orders
        query = db.session.query(User).outerjoin(
            active_orders_count,
            User.id == active_orders_count.c.courier_id
        ).filter(
            User.role == 'courier',
            User.is_available == True,
            User.is_active == True,
            db.or_(
                active_orders_count.c.active_count == None,  # No active orders
                active_orders_count.c.active_count < 2  # Less than 2 active orders
            )
        )

        # Exclude specific couriers if requested
        if excluded_courier_ids:
            query = query.filter(User.id.notin_(excluded_courier_ids))

        available_courier = query.first()

        return available_courier


class LeastLoadedStrategy(AssignmentStrategy):
    """
    Alternative strategy: Assigns to courier with least active orders
    Can be activated by changing the strategy in AssignmentService
    """

    def assign_courier(self, order, excluded_courier_ids=None):
        """Find courier with fewest active orders (max 2 active orders allowed)"""
        from sqlalchemy import func

        if excluded_courier_ids is None:
            excluded_courier_ids = []

        # Build query for courier loads
        query = db.session.query(
            User.id,
            func.count(Order.id).label('order_count')
        ).outerjoin(Order,
            (User.id == Order.courier_id) &
            (Order.status.in_(['assigned', 'picked_up', 'in_transit']))
        ).filter(
            User.role == 'courier',
            User.is_available == True,
            User.is_active == True
        )

        # Exclude specific couriers if requested
        if excluded_courier_ids:
            query = query.filter(User.id.notin_(excluded_courier_ids))

        # Group by courier and filter those with less than 2 active orders
        courier_loads = query.group_by(User.id).having(
            func.count(Order.id) < 2
        ).order_by('order_count').first()

        if courier_loads:
            courier = User.query.get(courier_loads[0])
            return courier
        return None


class DistanceBasedStrategy(AssignmentStrategy):
    """
    Intelligent strategy: Assigns to closest available courier
    Uses geocoding to convert addresses to coordinates and calculates distance
    """

    def __init__(self):
        """Initialize with geocoding and distance calculation services"""
        from services.geocoding_service import GeocodingService
        from services.distance_calculator import haversine_distance
        self.geocoder = GeocodingService()
        self.distance_calc = haversine_distance

    def assign_courier(self, order, excluded_courier_ids=None):
        """
        Find closest available courier based on GPS distance

        Process:
        1. Geocode order pickup address (if not already done)
        2. Get all available couriers with less than 2 active orders (excluding specified couriers if provided)
        3. Calculate distance from each courier to pickup location
        4. Return courier with minimum distance
        5. Fall back to first available if no location data
        """
        from sqlalchemy import func

        if excluded_courier_ids is None:
            excluded_courier_ids = []

        # Geocode order addresses if needed (uses cache if already done)
        self.geocoder.geocode_order(order)

        # Subquery to count active orders per courier
        active_orders_count = db.session.query(
            Order.courier_id,
            func.count(Order.id).label('active_count')
        ).filter(
            Order.status.in_(['assigned', 'picked_up', 'in_transit'])
        ).group_by(Order.courier_id).subquery()

        # Build query for available couriers with less than 2 active orders
        query = db.session.query(User).outerjoin(
            active_orders_count,
            User.id == active_orders_count.c.courier_id
        ).filter(
            User.role == 'courier',
            User.is_available == True,
            User.is_active == True,
            db.or_(
                active_orders_count.c.active_count == None,  # No active orders
                active_orders_count.c.active_count < 2  # Less than 2 active orders
            )
        )

        # Exclude specific couriers if requested (e.g., who recently rejected)
        if excluded_courier_ids:
            query = query.filter(User.id.notin_(excluded_courier_ids))

        # Get all available couriers
        available = query.all()

        if not available:
            return None

        # If geocoding failed, fall back to first available
        if not order.pickup_latitude:
            print("Geocoding failed, using first available courier")
            return available[0]

        # Find closest courier based on distance with rejection penalty
        best_courier = None
        min_weighted_distance = float('inf')

        for courier in available:
            # Skip couriers without location data
            if not courier.last_known_latitude:
                continue

            # Calculate distance from courier to pickup location
            distance = self.distance_calc(
                courier.last_known_latitude,
                courier.last_known_longitude,
                order.pickup_latitude,
                order.pickup_longitude
            )

            if not distance:
                continue

            # Calculate rejection penalty (higher rejection rate = worse score)
            rejection_penalty = self._calculate_rejection_penalty(courier)

            # Apply penalty to distance (rejected orders make courier "appear" farther)
            weighted_distance = distance * rejection_penalty

            # Update best courier if this one has lowest weighted distance
            if weighted_distance < min_weighted_distance:
                min_weighted_distance = weighted_distance
                best_courier = courier

        # If no courier has location data, use first available
        if not best_courier:
            print("No courier location data available, using first available")
            return available[0]

        print(f"Assigned to {best_courier.full_name} (distance: {min_weighted_distance:.2f} km weighted)")
        return best_courier

    def _calculate_rejection_penalty(self, courier):
        """
        Calculate penalty multiplier based on rejection rate

        Returns:
            float: Penalty multiplier (1.0 = no penalty, higher = worse)

        Examples:
            0% rejection rate: 1.0x (no penalty)
            10% rejection: 1.1x
            20% rejection: 1.2x
            50% rejection: 1.5x
            100% rejection: 2.0x (very bad)
        """
        total = courier.total_deliveries or 0
        rejected = courier.rejected_orders or 0

        if total == 0:
            # New courier - no penalty
            return 1.0

        rejection_rate = rejected / total

        # Linear penalty: 1.0 + rejection_rate
        # This doubles the effective distance at 100% rejection
        penalty = 1.0 + rejection_rate

        return penalty


class AssignmentService:
    """
    Main service for order assignment
    Encapsulates the assignment logic and makes it easy to swap strategies
    """

    def __init__(self, strategy=None):
        """
        Initialize with a specific strategy
        Default: FirstAvailableStrategy (simple MVP)
        """
        self.strategy = strategy or FirstAvailableStrategy()

    def set_strategy(self, strategy):
        """Allow dynamic strategy switching"""
        self.strategy = strategy

    def _get_recently_rejected_couriers(self, order, timeout_minutes):
        """
        Get list of courier IDs who rejected this order within the timeout period

        Args:
            order: Order object
            timeout_minutes: Number of minutes to consider as "recent"

        Returns:
            list: Courier IDs who recently rejected (within timeout)
        """
        if not order.rejected_by_couriers:
            return []

        from datetime import datetime, timedelta

        excluded = []
        cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)

        for rejection in order.rejected_by_couriers:
            rejected_at = datetime.fromisoformat(rejection['rejected_at'])
            if rejected_at > cutoff_time:
                excluded.append(rejection['courier_id'])

        return excluded

    def auto_assign_order(self, order, exclude_courier_id=None):
        """
        Automatically assign an order to a courier

        Args:
            order: Order object to assign
            exclude_courier_id: Optional courier ID to exclude from assignment (e.g., courier who rejected)

        Returns:
            tuple (success: bool, message: str, courier: User or None)
        """
        if order.courier_id:
            return False, "Order already assigned", None

        # Calculate which couriers should be excluded based on recent rejections
        # Rejection timeout: 15 minutes
        REJECTION_TIMEOUT_MINUTES = 15
        excluded_couriers = self._get_recently_rejected_couriers(order, REJECTION_TIMEOUT_MINUTES)

        # Add the explicit exclude_courier_id if provided
        if exclude_courier_id and exclude_courier_id not in excluded_couriers:
            excluded_couriers.append(exclude_courier_id)

        # Try to assign with exclusions first
        courier = self.strategy.assign_courier(order, excluded_courier_ids=excluded_couriers)

        # If no courier found and we have exclusions, try without exclusions
        # (This handles case when all couriers rejected but timeout expired or no one else available)
        if not courier and excluded_couriers:
            print(f"No courier found with exclusions, trying without timeout restrictions...")
            courier = self.strategy.assign_courier(order, excluded_courier_ids=[exclude_courier_id] if exclude_courier_id else [])

        if not courier:
            return False, "No available couriers found", None

        # Assign the order
        order.courier_id = courier.id
        order.status = 'assigned'
        order.assigned_at = datetime.utcnow()

        # Calculate estimated delivery times
        from services.distance_calculator import calculate_delivery_estimates

        if (courier.last_known_latitude and order.pickup_latitude and order.delivery_latitude):
            estimates = calculate_delivery_estimates(
                courier.last_known_latitude,
                courier.last_known_longitude,
                order.pickup_latitude,
                order.pickup_longitude,
                order.delivery_latitude,
                order.delivery_longitude,
                vehicle_type=courier.vehicle_type or 'bike'
            )

            if estimates:
                order.estimated_pickup_time = estimates['pickup_time']
                order.estimated_delivery_time = estimates['delivery_time']
                order.estimated_total_time = estimates['total_time']

        # Log the assignment for AI analysis
        log_entry = DeliveryLog(
            order_id=order.id,
            event_type='auto_assignment',
            event_description=f'Order automatically assigned to {courier.full_name}',
            old_status='pending',
            new_status='assigned',
            user_id=courier.id,
            user_role='courier',
            timestamp=datetime.utcnow(),
            event_metadata={
                'assignment_strategy': self.strategy.__class__.__name__,
                'courier_name': courier.full_name,
                'courier_id': courier.id,
                'estimated_pickup_time': order.estimated_pickup_time,
                'estimated_delivery_time': order.estimated_delivery_time,
                'estimated_total_time': order.estimated_total_time
            }
        )

        db.session.add(log_entry)
        db.session.commit()

        return True, f"Order assigned to {courier.full_name}", courier


# Factory function for easy integration
def create_assignment_service(strategy_name='distance'):
    """
    Factory function to create assignment service with specified strategy

    Args:
        strategy_name: 'first_available', 'least_loaded', 'distance' (default)

    This makes it easy to switch strategies via configuration
    """
    strategies = {
        'first_available': FirstAvailableStrategy(),
        'least_loaded': LeastLoadedStrategy(),
        'distance': DistanceBasedStrategy(),
    }

    strategy = strategies.get(strategy_name, DistanceBasedStrategy())
    return AssignmentService(strategy)


# Default service instance - uses distance-based assignment
default_assignment_service = create_assignment_service('distance')
