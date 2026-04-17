"""
Order Scheduler Service

Background scheduler that periodically checks for pending orders
and attempts to auto-assign them when couriers become available.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from models import Order, db
from datetime import datetime


class OrderScheduler:
    """Background scheduler for auto-assigning pending orders"""

    def __init__(self, app):
        """
        Initialize scheduler with Flask app context

        Args:
            app: Flask application instance
        """
        self.app = app
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()

    def start(self):
        """Start the scheduler jobs"""
        # Check for pending orders every 30 seconds
        self.scheduler.add_job(
            func=self.assign_pending_orders,
            trigger='interval',
            seconds=30,
            id='assign_pending_orders',
            name='Auto-assign pending orders',
            replace_existing=True
        )
        print("Order scheduler started - checking pending orders every 30 seconds")

    def assign_pending_orders(self):
        """
        Check for pending orders and attempt to auto-assign them

        This runs periodically in the background to handle:
        1. Orders waiting because all couriers were busy
        2. Orders where rejection timeout expired
        3. New orders that need assignment
        """
        with self.app.app_context():
            try:
                # Find all pending orders (not yet assigned)
                pending_orders = Order.query.filter_by(status='pending').order_by(Order.created_at).all()

                if not pending_orders:
                    return

                print(f"Found {len(pending_orders)} pending orders, attempting assignment...")

                from services.assignment_algorithm import default_assignment_service

                assigned_count = 0
                for order in pending_orders:
                    # Try to auto-assign
                    success, message, courier = default_assignment_service.auto_assign_order(order)

                    if success:
                        assigned_count += 1
                        print(f"✓ Order {order.order_number} assigned to {courier.full_name}")
                        # Emit WebSocket event
                        try:
                            import app as app_module
                            if hasattr(app_module, 'socketio_service'):
                                app_module.socketio_service.emit_order_assigned(order)
                        except Exception as e:
                            print(f"[SocketIO] Error emitting order:assigned from scheduler: {e}")
                    else:
                        print(f"✗ Order {order.order_number}: {message}")

                if assigned_count > 0:
                    print(f"Successfully assigned {assigned_count} pending orders")

            except Exception as e:
                print(f"Error in scheduler: {e}")
                import traceback
                traceback.print_exc()

    def shutdown(self):
        """Shutdown the scheduler gracefully"""
        self.scheduler.shutdown()
        print("Order scheduler stopped")


# Global scheduler instance
_scheduler_instance = None


def init_scheduler(app):
    """
    Initialize and start the global scheduler

    Args:
        app: Flask application instance

    Returns:
        OrderScheduler instance
    """
    global _scheduler_instance

    if _scheduler_instance is None:
        _scheduler_instance = OrderScheduler(app)
        _scheduler_instance.start()

    return _scheduler_instance


def get_scheduler():
    """Get the global scheduler instance"""
    return _scheduler_instance
