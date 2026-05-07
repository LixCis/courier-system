"""Background tasks for the Flask-SocketIO (gevent) app.

These must be started via `socketio.start_background_task(...)` so they run
as cooperative gevent greenlets instead of native threads.
"""
import time
from flask import current_app

from models import db, Order, User, DeliveryLog, Notification  # noqa: F401
from extensions import socketio, socketio_service, init_socketio_service
from common.utils import utcnow
from common.logging_config import get_logger

logger = get_logger(__name__)


def enhance_in_background(app, order_id, description):
    """Enhance an order's description with AI in the background."""
    from services.llm_service import enhance_order_description
    with app.app_context():
        try:
            ai_enhanced = enhance_order_description(description)
            if ai_enhanced:
                order = db.session.get(Order, order_id)
                if order:
                    order.ai_enhanced_description = ai_enhanced
                    db.session.commit()
                    logger.info(f"Description updated for order {order.order_number}")
                    init_socketio_service().emit_ai_description_ready(order)
        except Exception as e:
            logger.warning(f"Error enhancing order description: {e}")


def transition_to_in_transit_background(order_id, app):
    """Wait 3s then transition an order from picked_up to in_transit."""
    time.sleep(3)
    with app.app_context():
        try:
            order = db.session.get(Order, order_id)
            if order and order.status == 'picked_up':
                order.status = 'in_transit'
                order.in_transit_at = utcnow()
                log_entry = DeliveryLog(
                    order_id=order.id,
                    event_type='status_change',
                    event_description='Status automatically changed from picked_up to in_transit',
                    old_status='picked_up',
                    new_status='in_transit',
                    timestamp=utcnow()
                )
                db.session.add(log_entry)
                db.session.commit()
                logger.info(f"Order #{order.order_number} auto-transitioned to in_transit")
                init_socketio_service().emit_order_status_changed(order, 'picked_up', 'in_transit')
        except Exception as e:
            logger.warning(f"Auto-transition background error for order {order_id}: {e}")


def auto_transition_order_statuses():
    """Transition picked_up orders to in_transit after 3+ seconds.

    Called from page-load routes (synchronously). Returns the set of order IDs
    that were transitioned in this call or within the last 1s (for UI sync).
    Optimized: only scans orders recently marked as picked_up (within 10 minutes).
    """
    from datetime import timedelta
    now = utcnow()
    recent_cutoff = now - timedelta(minutes=10)

    # Only scan picked_up orders from the last 10 minutes to reduce DB load
    picked_up_orders = Order.query.filter_by(status='picked_up').filter(
        Order.picked_up_at >= recent_cutoff
    ).all()

    if picked_up_orders:
        logger.debug(f"Found {len(picked_up_orders)} recent orders with status 'picked_up'")

    transitions_made = 0
    transitioned_order_ids = set()

    for order in picked_up_orders:
        if order.picked_up_at:
            seconds = (utcnow() - order.picked_up_at).total_seconds()
            if seconds >= 3:
                old_status = order.status
                order.status = 'in_transit'
                order.in_transit_at = utcnow()
                logger.info(f"Auto-transition order #{order.order_number}: {old_status} → in_transit")

                db.session.add(DeliveryLog(
                    order_id=order.id,
                    event_type='status_change',
                    event_description=f'Status automatically changed from {old_status} to in_transit',
                    old_status=old_status,
                    new_status='in_transit',
                    timestamp=utcnow()
                ))
                transitions_made += 1
                transitioned_order_ids.add(order.id)

    if transitions_made > 0:
        db.session.commit()
        svc = init_socketio_service()
        for order in picked_up_orders:
            if order.id in transitioned_order_ids:
                try:
                    svc.emit_order_status_changed(order, 'picked_up', 'in_transit')
                except Exception as e:
                    logger.warning(f"SocketIO emit error for order {order.id}: {e}")

    # Catch orders transitioned within the last 1s (so UI reloads pick them up)
    recent_transit_cutoff = now - timedelta(seconds=1)
    recent = Order.query.filter(
        Order.status == 'in_transit',
        Order.in_transit_at >= recent_transit_cutoff
    ).all()
    for order in recent:
        transitioned_order_ids.add(order.id)

    return transitioned_order_ids


def analyze_delivery_photo_background(app, order_id, filepath, order_description):
    """Analyze delivery photo in the background after upload."""
    from services.image_analyzer import analyze_delivery_photo, get_analysis_for_db
    with app.app_context():
        try:
            analysis_result = analyze_delivery_photo(
                filepath, order_description=order_description, use_ai_vision=True
            )
            order = db.session.get(Order, order_id)
            if order:
                order.delivery_proof_analysis = get_analysis_for_db(analysis_result)
                db.session.commit()
                logger.info(f"Photo analysis complete for order {order.order_number}")
                init_socketio_service().emit_delivery_photo_analyzed(order)
        except Exception as e:
            logger.warning(f"Error analyzing delivery photo for order {order_id}: {e}")


def pregenerate_ai_insights(app):
    """Pre-generate AI insights for all users on startup (background)."""
    time.sleep(0.5)  # let app fully initialize

    from services.llm_service import llm_service
    from services.image_analyzer import _vision_analyzer

    logger.info("Pre-loading LLM model in background...")
    if llm_service.is_available():
        logger.info("LLM model ready")
    else:
        logger.warning("LLM model not available, AI features will be disabled")
        return

    logger.info("Warming up vision model in background...")
    if _vision_analyzer.warmup():
        logger.info("Vision model ready")
    else:
        logger.warning("Vision model not available (image analysis will be disabled)")

    with app.app_context():
        from services.ai_statistics import get_or_generate_ai_summary
        logger.info("Pre-generating insights for all users...")
        try:
            for courier in User.query.filter_by(role='courier').all():
                logger.info(f"Generating insights for courier: {courier.full_name}")
                get_or_generate_ai_summary(courier.id, 'courier_daily')

            for restaurant in User.query.filter_by(role='restaurant').all():
                logger.info(f"Generating insights for restaurant: {restaurant.full_name}")
                get_or_generate_ai_summary(restaurant.id, 'restaurant_weekly')

            logger.info("Generating system-wide insights for admin")
            get_or_generate_ai_summary(None, 'admin_system')
            logger.info("All insights pre-generated successfully")
        except Exception as e:
            logger.warning(f"Error pre-generating insights: {e}")
