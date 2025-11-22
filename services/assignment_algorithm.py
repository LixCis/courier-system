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

    def assign_courier(self, order):
        """
        Assign a courier to an order
        Returns: User object (courier) or None
        """
        raise NotImplementedError("Subclasses must implement assign_courier")


class FirstAvailableStrategy(AssignmentStrategy):
    """
    Simple strategy: Assigns to the first available courier
    This is the MVP implementation that can be easily replaced
    """

    def assign_courier(self, order):
        """
        Find the first available courier and assign the order

        Logic:
        1. Find couriers who are marked as available
        2. Optionally filter by those with fewest active orders
        3. Return the first match
        """
        # Find available couriers
        available_courier = User.query.filter_by(
            role='courier',
            is_available=True,
            is_active=True
        ).first()

        return available_courier


class LeastLoadedStrategy(AssignmentStrategy):
    """
    Alternative strategy: Assigns to courier with least active orders
    Can be activated by changing the strategy in AssignmentService
    """

    def assign_courier(self, order):
        """Find courier with fewest active orders"""
        from sqlalchemy import func

        # Get count of active orders per courier
        courier_loads = db.session.query(
            User.id,
            func.count(Order.id).label('order_count')
        ).outerjoin(Order,
            (User.id == Order.courier_id) &
            (Order.status.in_(['assigned', 'picked_up', 'in_transit']))
        ).filter(
            User.role == 'courier',
            User.is_available == True,
            User.is_active == True
        ).group_by(User.id).order_by('order_count').first()

        if courier_loads:
            courier = User.query.get(courier_loads[0])
            return courier
        return None


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

    def auto_assign_order(self, order):
        """
        Automatically assign an order to a courier

        Returns:
            tuple (success: bool, message: str, courier: User or None)
        """
        if order.courier_id:
            return False, "Order already assigned", None

        # Use the current strategy to find a courier
        courier = self.strategy.assign_courier(order)

        if not courier:
            return False, "No available couriers found", None

        # Assign the order
        order.courier_id = courier.id
        order.status = 'assigned'
        order.assigned_at = datetime.utcnow()

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
                'courier_id': courier.id
            }
        )

        db.session.add(log_entry)
        db.session.commit()

        return True, f"Order assigned to {courier.full_name}", courier


# Factory function for easy integration
def create_assignment_service(strategy_name='first_available'):
    """
    Factory function to create assignment service with specified strategy

    Args:
        strategy_name: 'first_available', 'least_loaded', or custom

    This makes it easy to switch strategies via configuration
    """
    strategies = {
        'first_available': FirstAvailableStrategy(),
        'least_loaded': LeastLoadedStrategy(),
    }

    strategy = strategies.get(strategy_name, FirstAvailableStrategy())
    return AssignmentService(strategy)


# Default service instance - can be easily replaced
default_assignment_service = create_assignment_service('first_available')
